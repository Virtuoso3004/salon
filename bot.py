import os
import re

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from salon_data import FAQ, SALON, SERVICES

TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["RENDER_EXTERNAL_URL"]
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "lumiere_secret_2026")

router = Router()

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💅 Записаться")],
        [KeyboardButton(text="💰 Прайс"), KeyboardButton(text="📍 Контакты")],
    ],
    resize_keyboard=True,
)


# ---------- вспомогательные функции ----------

def tokenize(text: str) -> list[str]:
    """Разбивает текст на слова: строчные, ё -> е."""
    text = text.lower().replace("ё", "е")
    return re.findall(r"[a-zа-я0-9]+", text)


def has_stem(tokens: list[str], stems: list[str]) -> bool:
    """Есть ли в тексте слово, начинающееся с любого из stems."""
    return any(t.startswith(s) for t in tokens for s in stems)


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def service_line(s: dict) -> str:
    return f"• {s['name']} — <b>{money(s['price'])}</b> ({s['minutes']} мин)"


def price_list() -> str:
    lines = "\n".join(service_line(s) for s in SERVICES)
    return f"💰 <b>Прайс {SALON['name']}</b>\n\n{lines}"


def contacts_text() -> str:
    return (
        f"📍 <b>{SALON['name']}</b>\n\n"
        f"Адрес: {SALON['address']}\n"
        f"Телефон: {SALON['phone']}\n"
        f"Режим работы: {SALON['hours']}\n"
        f"Instagram: {SALON['instagram']}"
    )


def find_answer(text: str) -> str | None:
    """Ищет ответ на вопрос клиента. Если не нашёл, вернёт None."""
    tokens = tokenize(text)

    # 1) Спрашивают про конкретную услугу
    found = [s for s in SERVICES if has_stem(tokens, s["stems"])]
    if found:
        lines = "\n".join(service_line(s) for s in found)
        return f"Вот что нашёл:\n\n{lines}\n\nХотите записаться? Нажмите «💅 Записаться»."

    # 2) Спрашивают про цены вообще
    if has_stem(tokens, ["прайс", "цен", "стоимост", "расценк", "сколько"]):
        return price_list()

    # 3) Ищем лучший ответ в списке частых вопросов
    best_answer, best_score = None, 0
    for keywords, answer in FAQ:
        score = sum(1 for k in keywords if has_stem(tokens, [k]))
        if score > best_score:
            best_answer, best_score = answer, score
    return best_answer


# ---------- обработчики сообщений ----------

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        f"Здравствуйте! Я администратор салона красоты <b>{SALON['name']}</b> ✨\n"
        "Помогу записаться и отвечу на вопросы.",
        reply_markup=MENU,
    )


@router.message(F.text == "💅 Записаться")
async def booking_stub(message: Message):
    await message.answer("Онлайн-запись откроется совсем скоро 💅", reply_markup=MENU)


@router.message(F.text == "💰 Прайс")
async def price(message: Message):
    await message.answer(price_list(), reply_markup=MENU)


@router.message(F.text == "📍 Контакты")
async def contacts(message: Message):
    await message.answer(contacts_text(), reply_markup=MENU)


@router.message()
async def any_message(message: Message):
    if not message.text:
        await message.answer("Я понимаю только текстовые сообщения 🙂", reply_markup=MENU)
        return
    answer = find_answer(message.text)
    if answer is None:
        answer = (
            "Не нашёл ответ на этот вопрос 🤔\n"
            f"Позвоните нам: {SALON['phone']}, и мы всё подскажем."
        )
    await message.answer(answer, reply_markup=MENU)


# ---------- запуск ----------

async def health(request):
    return web.Response(text="ok")


async def on_startup(bot: Bot):
    await bot.set_webhook(f"{BASE_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET)


def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    app = web.Application()
    app.router.add_get("/", health)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(
        app, path=WEBHOOK_PATH
    )
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)


main()