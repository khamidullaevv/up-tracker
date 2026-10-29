import asyncio
import logging
import os
import sqlite3
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
AFFILIATE_LINK = os.getenv("AFFILIATE_LINK", "https://example.com/?ref=YOUR_ID")
OFFER_NAME = os.getenv("OFFER_NAME", "Название вашего оффера")
CHANNEL_URL = os.getenv("CHANNEL_URL", "")  # Ссылка на ваш канал (можно оставить пустой)
REMINDER_AFTER_HOURS = int(os.getenv("REMINDER_AFTER_HOURS", "24"))

TEXT_WELCOME = (
    "Привет, {name}!\n\n"
    "Здесь вы найдёте полезные материалы и выгодные предложения по теме «{offer}».\n\n"
    "Выберите, что вам интересно:"
)

TEXT_HOW = (
    "Как это работает\n\n"
    "1. Вы переходите по ссылке на сайт сервиса.\n"
    "2. Регистрируетесь и пользуетесь.\n"
    "3. Если нужна помощь, пишите сюда.\n\n"
    "Ссылка партнёрская: сервис может выплатить автору бота вознаграждение, "
    "для вас цена не меняется."
)

TEXT_MATERIALS = (
    "Полезные материалы\n\n"
    "Здесь добавьте свой контент: чек-лист, мини-гайд, подборку советов.\n"
    "Замените этот текст в файле bot.py (переменная TEXT_MATERIALS)."
)

TEXT_OFFER = (
    "«{offer}»\n\n"
    "Нажмите кнопку ниже, чтобы перейти на страницу предложения.\n"
    "Реклама. Ссылка партнёрская."
)

TEXT_REMINDER = (
    "Вы смотрели предложение «{offer}», но так и не перешли.\n"
    "Если остались вопросы, нажмите «Узнать больше» ниже."
)

DB_PATH = "bot.db"
router = Router()


# ================= БАЗА ДАННЫХ =================
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                source TEXT DEFAULT 'direct',
                joined_at INTEGER,
                clicked INTEGER DEFAULT 0,
                reminded INTEGER DEFAULT 0
            );
            
            CREATE TABLE IF NOT EXISTS clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                ts INTEGER
            );
            """
        )


def add_user(user_id: int, username: str | None, source: str):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, source, joined_at) VALUES (?, ?, ?, ?)",
            (user_id, username, source, int(time.time())),
        )


def log_click(user_id: int):
    with db() as conn:
        conn.execute("INSERT INTO clicks (user_id, ts) VALUES (?, ?)", (user_id, int(time.time())))
        conn.execute("UPDATE users SET clicked = 1 WHERE user_id = ?", (user_id,))


# ================= КЛАВИАТУРЫ =================
def main_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💎 Узнать больше", callback_data="offer")],
        [InlineKeyboardButton(text="📚 Материалы", callback_data="materials")],
        [InlineKeyboardButton(text="⚙️ Как это работает", callback_data="how")],
    ]
    if CHANNEL_URL:
        rows.append([InlineKeyboardButton(text="📢 Наш канал", url=CHANNEL_URL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def offer_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Перейти на сайт", url=AFFILIATE_LINK)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu")],
        ]
    )


# ================= ОБРАБОТЧИКИ =================
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    # Метки источника: t.me/ВАШ_БОТ?start=tiktok -> source = "tiktok"
    source = (command.args or "direct")[:50]
    add_user(message.from_user.id, message.from_user.username, source)
    await message.answer(
        TEXT_WELCOME.format(name=message.from_user.first_name, offer=OFFER_NAME),
        reply_markup=main_kb(),
    )


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    await call.message.edit_text(
        TEXT_WELCOME.format(name=call.from_user.first_name, offer=OFFER_NAME),
        reply_markup=main_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "offer")
async def cb_offer(call: CallbackQuery):
    log_click(call.from_user.id)  # Считаем интерес к офферу
    await call.message.edit_text(
        TEXT_OFFER.format(offer=OFFER_NAME),
        reply_markup=offer_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "materials")
async def cb_materials(call: CallbackQuery):
    await call.message.edit_text(TEXT_MATERIALS, reply_markup=offer_kb())
    await call.answer()


@router.callback_query(F.data == "how")
async def cb_how(call: CallbackQuery):
    await call.message.edit_text(TEXT_HOW, reply_markup=offer_kb())
    await call.answer()


# ================= АДМИНКА =================
def is_admin(message: Message) -> bool:
    return message.from_user.id == ADMIN_ID


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message):
        return

    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        clicked = conn.execute("SELECT COUNT(*) FROM users WHERE clicked = 1").fetchone()[0]
        clicks = conn.execute("SELECT COUNT(*) FROM clicks").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE joined_at > ?", (int(time.time()) - 86400,)
        ).fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*) as c, SUM(clicked) as k FROM users GROUP BY source"
        ).fetchall()

    conv = f"{(clicked / total * 100):.1f}%" if total else "0%"
    lines = [
        "📊 Статистика",
        f"Пользователей: {total} (за 24ч: {today})",
        f"Открыли оффер: {clicked} ({conv})",
        f"Всего нажатий: {clicks}",
        "",
        "Источники (пришло / открыли оффер):",
    ]
    for r in by_source:
        lines.append(f"  • {r['source']}: {r['c']} / {r['k'] or 0}")

    await message.answer("\n".join(lines))


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot):
    if not is_admin(message):
        return
    if not command.args:
        await message.answer("Использование: /broadcast текст рассылки")
        return

    with db() as conn:
        ids = [r[0] for r in conn.execute("SELECT user_id FROM users")]

    ok = 0
    fail = 0
    for uid in ids:
        try:
            await bot.send_message(uid, command.args, reply_markup=main_kb())
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)  # Лимиты Telegram

    await message.answer(f"Рассылка завершена. Доставлено: {ok}, ошибок: {fail}")


# ================= АВТО-НАПОМИНАНИЕ =================
async def reminder_loop(bot: Bot):
    """Раз в 10 минут напоминает тем, кто не открыл оффер за N часов (один раз)."""
    while True:
        try:
            border = int(time.time()) - REMINDER_AFTER_HOURS * 3600
            with db() as conn:
                ids = [
                    r[0] for r in conn.execute(
                        "SELECT user_id FROM users WHERE clicked = 0 AND reminded = 0 AND joined_at < ?",
                        (border,)
                    )
                ]

            for uid in ids:
                try:
                    await bot.send_message(
                        uid,
                        TEXT_REMINDER.format(offer=OFFER_NAME),
                        reply_markup=offer_kb(),
                    )
                except Exception:
                    pass
                with db() as conn:
                    conn.execute("UPDATE users SET reminded = 1 WHERE user_id = ?", (uid,))
                await asyncio.sleep(0.05)
        except Exception as e:
            logging.exception("reminder_loop error: %s", e)

        await asyncio.sleep(600)


# ================= ЗАПУСК =================
async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("Укажите BOT_TOKEN в файле .env")
    
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())