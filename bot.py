import os
import json
import random
import logging
from datetime import datetime, time as dt_time, timezone, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

USERS_FILE    = os.path.join(os.path.dirname(__file__), "users_data.json")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings_data.json")
MOSCOW_TZ     = timezone(timedelta(hours=3))


# ─── Хранилище участников ─────────────────────────────────────────────────────

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_users(data: dict) -> None:
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register_user(chat_id: int, user, registered: bool = False) -> None:
    """Сохраняет пользователя в хранилище по chat_id."""
    data = load_users()
    key = str(chat_id)
    if key not in data:
        data[key] = {}
    uid = str(user.id)
    existing = data[key].get(uid, {})
    data[key][uid] = {
        "id": user.id,
        "first_name": user.first_name or "",
        "username": user.username or "",
        # Не снимаем флаг, если он уже был выставлен через /reg
        "registered": registered or existing.get("registered", False),
        "wins": existing.get("wins", 0),
    }
    save_users(data)


def increment_wins(chat_id: int, user_id: int) -> None:
    data = load_users()
    key = str(chat_id)
    uid = str(user_id)
    if key in data and uid in data[key]:
        data[key][uid]["wins"] = data[key][uid].get("wins", 0) + 1
        save_users(data)


def get_chat_users(chat_id: int) -> list:
    data = load_users()
    return list(data.get(str(chat_id), {}).values())


def get_registered_users(chat_id: int) -> list:
    """Возвращает только тех, кто явно зарегистрировался через /reg."""
    return [u for u in get_chat_users(chat_id) if u.get("registered")]


def remove_user(chat_id: int, user_id: int) -> bool:
    """Удаляет пользователя из хранилища. Возвращает True если был удалён."""
    data = load_users()
    key = str(chat_id)
    uid = str(user_id)
    if key in data and uid in data[key]:
        del data[key][uid]
        save_users(data)
        return True
    return False


# ─── Настройки чата ───────────────────────────────────────────────────────────

def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_settings(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_auto_kpacaba(chat_id: int) -> bool:
    return load_settings().get(str(chat_id), {}).get("auto_kpacaba", False)


def set_auto_kpacaba(chat_id: int, enabled: bool) -> None:
    data = load_settings()
    key = str(chat_id)
    if key not in data:
        data[key] = {}
    data[key]["auto_kpacaba"] = enabled
    save_settings(data)


def today_moscow() -> str:
    """Возвращает сегодняшнюю дату по МСК в формате YYYY-MM-DD."""
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")


def get_last_kpacaba_date(chat_id: int) -> str:
    return load_settings().get(str(chat_id), {}).get("last_kpacaba_date", "")


def set_last_kpacaba_date(chat_id: int) -> None:
    data = load_settings()
    key = str(chat_id)
    if key not in data:
        data[key] = {}
    data[key]["last_kpacaba_date"] = today_moscow()
    save_settings(data)


# ─── Планировщик ──────────────────────────────────────────────────────────────

async def auto_kpacaba_job(context) -> None:
    chat_id = context.job.chat_id
    users = get_registered_users(chat_id)
    if not users:
        return
    if get_last_kpacaba_date(chat_id) == today_moscow():
        return  # уже выбирали вручную сегодня
    chosen = random.choice(users)
    increment_wins(chat_id, chosen["id"])
    set_last_kpacaba_date(chat_id)
    mention = f"@{chosen['username']}" if chosen["username"] else chosen["first_name"]
    await context.bot.send_message(
        chat_id=chat_id,
        text=random_kpacaba_text(mention),
    )


def schedule_auto_kpacaba(app, chat_id: int) -> None:
    job_name = f"auto_kpacaba_{chat_id}"
    for job in app.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    app.job_queue.run_daily(
        auto_kpacaba_job,
        time=dt_time(hour=18, minute=0, tzinfo=MOSCOW_TZ),
        chat_id=chat_id,
        name=job_name,
    )


def cancel_auto_kpacaba(app, chat_id: int) -> None:
    job_name = f"auto_kpacaba_{chat_id}"
    for job in app.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()


# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def settings_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    auto = get_auto_kpacaba(chat_id)
    status = "✅ ВКЛ" if auto else "❌ ВЫКЛ"
    buttons = [
        [InlineKeyboardButton(f"🤖 Авто-красавчик в 18:00: {status}", callback_data="toggle_auto")],
        [InlineKeyboardButton("▶️ Запустить сейчас", callback_data="run_now")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")],
    ]
    return InlineKeyboardMarkup(buttons)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📋 О боте", callback_data="about")],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
            InlineKeyboardButton("❓ Помощь", callback_data="help"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


# ─── Команды ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    register_user(update.effective_chat.id, user)
    await update.message.reply_text(
        f"Йоу, {user.first_name}! 👑\n\n"
        "Добро пожаловать в *Битву Красавчиков* — единственное место, где случайность решает, кто сегодня бог.\n\n"
        "🎰 Каждый день бот выбирает одного участника и провозглашает его *КРАСАВЧИКОМ ДНЯ*. "
        "Это может быть ты. Или не ты. Но точно кто-то достойный.\n\n"
        "📋 Как стать частью легенды:\n"
        "1️⃣ Напиши /reg — и ты в игре\n"
        "2️⃣ Жди, пока /kpacaba не назовёт твоё имя\n"
        "3️⃣ Прими славу достойно 💅\n\n"
        "Трусы пишут /getout. Легенды остаются. Ты уже знаешь, кто ты.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *Список команд:*\n\n"
        "/start — главное меню\n"
        "/help — эта справка\n"
        "/about — информация о боте\n"
        "/reg — зарегистрироваться для участия в /kpacaba\n"
        "/kpacaba — выбрать красавчика дня 👑\n"
        "/statistics — статистика побед 📊\n"
        "/getout — выйти из игры 🚶\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👑 *БИТВА КРАСАВЧИКОВ* 👑\n\n"
        "Каждый день среди участников чата разгорается невидимая война за звание "
        "*Красавчика Дня* — и победителя выбирает не голосование, не внешность и даже не связи. "
        "Его выбирает *судьба*. Беспощадная. Случайная. Справедливая.\n\n"
        "🎰 *Как это работает:*\n"
        "1️⃣ Напиши /reg — брось вызов судьбе и войди в игру\n"
        "2️⃣ Каждый день кто-то получает корону через /kpacaba\n"
        "3️⃣ Следи за статистикой — /statistics покажет, кто настоящая легенда\n"
        "4️⃣ Включи авто-режим ⚙️ — и бот сам выберет красавчика в 18:00 по МСК\n\n"
        "🏆 *Зачем участвовать?*\n"
        "Потому что быть красавчиком дня — это не просто титул. "
        "Это признание. Это история. Это то, о чём ты будешь рассказывать внукам.\n\n"
        "Трусы не регистрируются. Легенды — уже внутри. 😤\n\n"
        "_Сделано с любовью и рандомом._",
        parse_mode="Markdown",
    )


async def reg_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat

    if user.is_bot:
        return

    register_user(chat.id, user, registered=True)

    mention = f"@{user.username}" if user.username else user.first_name
    await update.message.reply_text(
        f"✅ {mention}, ты зарегистрирован(а) как участник!\n"
        "Теперь тебя могут выбрать командой /kpacaba 👑"
    )


async def kpacaba_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat

    if get_last_kpacaba_date(chat.id) == today_moscow():
        await update.message.reply_text(
            "⏳ Красавчик сегодня уже выбран!\n"
            "Возвращайся завтра — трон не вечен. 👑"
        )
        return

    users = get_registered_users(chat.id)

    if not users:
        await update.message.reply_text(
            "😔 Никто ещё не зарегистрировался.\n"
            "Пусть участники напишут /reg — тогда смогу выбрать красавчика!"
        )
        return

    chosen = random.choice(users)
    increment_wins(chat.id, chosen["id"])
    set_last_kpacaba_date(chat.id)

    # Формируем упоминание: @username или просто имя
    if chosen["username"]:
        mention = f"@{chosen['username']}"
    else:
        mention = chosen["first_name"]

    await update.message.reply_text(random_kpacaba_text(mention))


KPACABA_TEMPLATES = [
    "🌟 СТОП! ВНИМАНИЕ! ВСЕ СЮДА! 🌟\n\nАлгоритм просчитал все варианты вселенной и пришёл к единственно верному выводу:\n\n👑 {mention} 👑\n\nСЕГОДНЯШНИЙ КРАСАВЧИК ДНЯ. Завидуйте молча.",
    "📯 ГЛАШАТАЙ ОБЪЯВЛЯЕТ! 📯\n\nПосле долгих раздумий, медитаций и гадания на кофейной гуще...\n\n👑 {mention} 👑\n\nТы избран(а)! Прими корону с достоинством. Или без — главное прими.",
    "🎰 БАРАБАНЫ БЬЮТ... КОНВЕРТ ВСКРЫТ... 🎰\n\nИ красавчиком дня становится...\n\n👑 {mention} 👑\n\nПоздравляем! Остальные — просто массовка.",
    "🔮 ОРАКУЛ ВЕЩАЕТ: 🔮\n\nЗвёзды выстроились, петух прокукарекал, бабуля на рынке одобрила —\n\n👑 {mention} 👑\n\nСегодня ТЫ. Завтра — может кто-то другой. Но сегодня — точно ты.",
    "⚡ ЭКСТРЕННОЕ СООБЩЕНИЕ ⚡\n\nПрерываем программу для важного объявления.\nКрасавчик дня определён:\n\n👑 {mention} 👑\n\nВернитесь к своим делам. Ничего важнее сегодня не будет.",
    "🎬 РЕЖИССЁР КРИЧИТ «СТОП»! 🎬\n\nСреди всего этого балагана нашёлся один по-настоящему достойный:\n\n👑 {mention} 👑\n\nОскар за лучшую роль красавчика вручён. Речь — по желанию.",
    "🧬 НАУКА РЕШИЛА 🧬\n\nУчёные провели исследование, собрали данные, поспорили и всё-таки сошлись во мнении:\n\n👑 {mention} 👑\n\nКрасавчик дня по всем научным критериям. Оспорить невозможно.",
    "🏆 ТУРНИР КРАСАВЧИКОВ ЗАВЕРШЁН 🏆\n\nПобедитель определён в жестокой борьбе с самим собой:\n\n👑 {mention} 👑\n\nПьедестал твой. Второго места нет — остальные просто зрители.",
    "🌅 НОВЫЙ ДЕНЬ — НОВАЯ ЛЕГЕНДА 🌅\n\nСолнце взошло, птички запели, и вселенная шепнула одно имя:\n\n👑 {mention} 👑\n\nИди и неси красоту в массы. Мы верим в тебя.",
    "🎺 ФАНФАРЫ! ФАНФАРЫ! 🎺\n\nЭтот момент вошёл в историю чата. Запомните, где вы были, когда узнали:\n\n👑 {mention} 👑\n\nВеличайший красавчик этого дня. Этой эпохи. Этого чата.",
    "😤 НЕ СПРАШИВАЙ ПОЧЕМУ 😤\n\nПросто прими как данность:\n\n👑 {mention} 👑\n\nСегодня красавчик — ты. Бот сказал — бот знает. Точка.",
    "🪄 МАГИЯ СЛУЧАЙНОСТИ СРАБОТАЛА 🪄\n\nИз всей честной компании судьба ткнула пальцем в:\n\n👑 {mention} 👑\n\nПальцу виднее. Поздравляем!",
]


def random_kpacaba_text(mention: str) -> str:
    return random.choice(KPACABA_TEMPLATES).format(mention=mention)


GETOUT_PHRASES = [
    "У него был шанс стать легендой... но он выбрал диван. 🛋️",
    "Ушёл непобеждённым. Ну, или просто ушёл. 🚶",
    "Говорят, настоящие красавчики сами себя не недооценивают. Этот — оценил. 🪞",
    "Он мог бы войти в историю. Вместо этого — вышел из чата. 📖",
    "Корона была так близко... но пальто оказалось ближе. 🧥",
    "Не каждый рождён для величия. Некоторые рождены просто уйти. 🌅",
    "Испугался конкуренции? Мудрое решение. 🏳️",
]


async def getout_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat

    if user.is_bot:
        return

    was_registered = remove_user(chat.id, user.id)
    mention = f"@{user.username}" if user.username else user.first_name

    if not was_registered:
        await update.message.reply_text(
            f"🤔 {mention}, ты и так не участвуешь.\n"
            "Напиши /reg чтобы вступить в игру."
        )
        return

    phrase = random.choice(GETOUT_PHRASES)
    await update.message.reply_text(
        f"👋 {mention} покидает игру.\n\n"
        f"_{phrase}_",
        parse_mode="Markdown",
    )


async def statistics_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    users = get_registered_users(chat.id)

    if not users:
        await update.message.reply_text(
            "📊 Статистика пуста — никто ещё не зарегистрировался.\n"
            "Напиши /reg чтобы вступить в игру!"
        )
        return

    sorted_users = sorted(users, key=lambda u: u.get("wins", 0), reverse=True)

    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(sorted_users):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        name = f"@{u['username']}" if u["username"] else u["first_name"]
        wins = u.get("wins", 0)
        lines.append(f"{prefix} {name} — {wins} раз(а)")

    await update.message.reply_text(
        "📊 *Статистика красавчиков:*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


# ─── Обработчик кнопок ────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id
    await query.answer()

    if query.data == "settings":
        await query.edit_message_text(
            "⚙️ *Настройки*",
            parse_mode="Markdown",
            reply_markup=settings_keyboard(chat_id),
        )
        return

    if query.data == "toggle_auto":
        new_val = not get_auto_kpacaba(chat_id)
        set_auto_kpacaba(chat_id, new_val)
        if new_val:
            schedule_auto_kpacaba(context.application, chat_id)
        else:
            cancel_auto_kpacaba(context.application, chat_id)
        await query.edit_message_text(
            "⚙️ *Настройки*",
            parse_mode="Markdown",
            reply_markup=settings_keyboard(chat_id),
        )
        return

    if query.data == "run_now":
        users = get_registered_users(chat_id)
        if not users:
            await query.answer("😔 Никто не зарегистрировался!", show_alert=True)
            return
        chosen = random.choice(users)
        increment_wins(chat_id, chosen["id"])
        mention = f"@{chosen['username']}" if chosen["username"] else chosen["first_name"]
        await context.bot.send_message(
            chat_id=chat_id,
            text=random_kpacaba_text(mention),
        )
        return

    if query.data == "back_to_main":
        await query.edit_message_text(
            "Главное меню:",
            reply_markup=main_menu_keyboard(),
        )
        return

    responses = {
        "about": (
            "👑 *БИТВА КРАСАВЧИКОВ* 👑\n\n"
            "Каждый день среди участников чата разгорается невидимая война за звание "
            "*Красавчика Дня* — и победителя выбирает не голосование, не внешность и даже не связи. "
            "Его выбирает *судьба*. Беспощадная. Случайная. Справедливая.\n\n"
            "🎰 *Как это работает:*\n"
            "1️⃣ Напиши /reg — брось вызов судьбе и войди в игру\n"
            "2️⃣ Каждый день кто-то получает корону через /kpacaba\n"
            "3️⃣ Следи за статистикой — /statistics покажет, кто настоящая легенда\n"
            "4️⃣ Включи авто-режим ⚙️ — и бот сам выберет красавчика в 18:00 по МСК\n\n"
            "🏆 *Зачем участвовать?*\n"
            "Потому что быть красавчиком дня — это не просто титул. "
            "Это признание. Это история. Это то, о чём ты будешь рассказывать внукам.\n\n"
            "Трусы не регистрируются. Легенды — уже внутри. 😤\n\n"
            "_Сделано с любовью и рандомом._"
        ),
        "help": (
            "📖 *Список команд:*\n\n"
            "/start — главное меню\n"
            "/help — справка\n"
            "/about — о боте\n"
            "/reg — зарегистрироваться для /kpacaba\n"
            "/kpacaba — красавчик дня 👑\n"
            "/statistics — статистика побед 📊\n"
            "/getout — выйти из игры 🚶"
        ),
    }

    text = responses.get(query.data, "Неизвестная команда.")
    await query.edit_message_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ─── Трекинг участников группы ────────────────────────────────────────────────

async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запоминает каждого, кто написал сообщение в чате."""
    user = update.effective_user
    chat = update.effective_chat
    if user and not user.is_bot:
        register_user(chat.id, user)

    # Эхо только в личных чатах
    if chat.type == "private":
        await update.message.reply_text(
            f"Ты написал: {update.message.text}\n\n"
            "Воспользуйся /start для открытия меню."
        )


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def set_commands(app) -> None:
    await app.bot.set_my_commands([
        BotCommand("start",      "Главное меню"),
        BotCommand("reg",        "Зарегистрироваться для /kpacaba"),
        BotCommand("kpacaba",    "Выбрать красавчика дня 👑"),
        BotCommand("statistics", "Статистика побед 📊"),
        BotCommand("about",      "О боте"),
        BotCommand("getout",     "Выйти из игры 🚶"),
        BotCommand("help",       "Список команд"),
    ])
    # Восстанавливаем авто-задания после перезапуска
    settings = load_settings()
    for chat_id_str, chat_settings in settings.items():
        if chat_settings.get("auto_kpacaba"):
            schedule_auto_kpacaba(app, int(chat_id_str))


def main() -> None:
    if not TOKEN:
        raise ValueError("Не задан BOT_TOKEN в файле .env")

    app = Application.builder().token(TOKEN).post_init(set_commands).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("reg", reg_command))
    app.add_handler(CommandHandler("kpacaba",    kpacaba_command))
    app.add_handler(CommandHandler("statistics", statistics_command))
    app.add_handler(CommandHandler("getout",     getout_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_user))

    logger.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
