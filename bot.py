import os

from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

TOKEN = os.environ["BOT_TOKEN"]
# Render сам сообщает адрес вашего сервиса в этой переменной
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


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Здравствуйте! Я администратор салона красоты Lumière ✨\n"
        "Помогу записаться и отвечу на вопросы.",
        reply_markup=MENU,
    )


@router.message()
async def fallback(message: Message):
    await message.answer(
        "Скоро я научусь отвечать на любые вопросы 🙂",
        reply_markup=MENU,
    )


async def health(request):
    # Страница-проверка "я жив", понадобится для будильника
    return web.Response(text="ok")


async def on_startup(bot: Bot):
    await bot.set_webhook(
        f"{BASE_URL}{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
    )


def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    app = web.Application()
    app.router.add_get("/", health)
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)


main()