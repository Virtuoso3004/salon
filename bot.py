import html
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import storage
from salon_data import (
    BOOKING_DAYS, FAQ, MASTERS, SALON, SERVICES,
    SLOT_STEP, TIMEZONE, WORK_END, WORK_START,
)

TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["RENDER_EXTERNAL_URL"]
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "lumiere_secret_2026")
ADMIN_ID = int(os.environ["ADMIN_ID"]) if os.environ.get("ADMIN_ID") else None
BASE_DIR = Path(__file__).parent

router = Router()

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💅 Записаться", web_app=WebAppInfo(url=f"{BASE_URL}/app"))],
        [KeyboardButton(text="💰 Прайс"), KeyboardButton(text="📍 Контакты")],
    ],
    resize_keyboard=True,
)


# ---------- вспомогательные функции ----------

def tokenize(text: str) -> list[str]:
    text = text.lower().replace("ё", "е")
    return re.findall(r"[a-zа-я0-9]+", text)


def has_stem(tokens: list[str], stems: list[str]) -> bool:
    return any(t.startswith(s) for t in tokens for s in stems)


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def fmt_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


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
    tokens = tokenize(text)

    found = [s for s in SERVICES if has_stem(tokens, s["stems"])]
    if found:
        lines = "\n".join(service_line(s) for s in found)
        return f"Вот что нашёл:\n\n{lines}\n\nХотите записаться? Нажмите «💅 Записаться»."

    if has_stem(tokens, ["прайс", "цен", "стоимост", "расценк", "сколько"]):
        return price_list()

    best_answer, best_score = None, 0
    for keywords, answer in FAQ:
        score = sum(1 for k in keywords if has_stem(tokens, [k]))
        if score > best_score:
            best_answer, best_score = answer, score
    return best_answer


# ---------- расчёт свободного времени ----------

def now_local() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def free_slots(master_id: int, service_id: int, date_str: str) -> list[int]:
    """Свободные времена начала записи (в минутах от полуночи)."""
    master = next((m for m in MASTERS if m["id"] == master_id), None)
    service = next((s for s in SERVICES if s["id"] == service_id), None)
    if not master or not service or service_id not in master["services"]:
        return []
    try:
        day = date.fromisoformat(date_str)
    except ValueError:
        return []

    now = now_local()
    today = now.date()
    if day < today or day > today + timedelta(days=BOOKING_DAYS):
        return []

    duration = service["minutes"]
    taken = storage.busy(master_id, date_str)
    now_min = now.hour * 60 + now.minute
    result = []
    t = WORK_START
    while t + duration <= WORK_END:
        in_past = day == today and t < now_min + 30  # записаться можно минимум за 30 мин
        overlap = any(t < e and s < t + duration for s, e in taken)
        if not in_past and not overlap:
            result.append(t)
        t += SLOT_STEP
    return result


# ---------- обработчики сообщений ----------

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        f"Здравствуйте! Я администратор салона красоты <b>{SALON['name']}</b> ✨\n"
        "Помогу записаться и отвечу на вопросы.",
        reply_markup=MENU,
    )


@router.message(F.web_app_data)
async def on_booking(message: Message):
    """Сюда приходит запись из мини-приложения."""
    try:
        data = json.loads(message.web_app_data.data)
        master_id = int(data["master"])
        service_id = int(data["service"])
        date_str = str(data["date"])
        hh, mm = str(data["time"]).split(":")
        start_min = int(hh) * 60 + int(mm)
        name = str(data["name"]).strip()[:60]
        phone = str(data["phone"]).strip()[:25]
    except Exception:
        await message.answer("Не удалось прочитать запись 😔 Попробуйте ещё раз.", reply_markup=MENU)
        return

    digits = re.sub(r"\D", "", phone)
    if not name or not 10 <= len(digits) <= 15:
        await message.answer("Проверьте имя и телефон и попробуйте ещё раз.", reply_markup=MENU)
        return

    if start_min not in free_slots(master_id, service_id, date_str):
        await message.answer(
            "Это время уже занято 😔 Откройте запись снова и выберите другое.",
            reply_markup=MENU,
        )
        return

    service = next(s for s in SERVICES if s["id"] == service_id)
    master = next(m for m in MASTERS if m["id"] == master_id)
    storage.add({
        "user_id": message.from_user.id,
        "name": name,
        "phone": phone,
        "service_id": service_id,
        "master_id": master_id,
        "date": date_str,
        "start": start_min,
        "end": start_min + service["minutes"],
    })

    pretty_date = date.fromisoformat(date_str).strftime("%d.%m.%Y")
    await message.answer(
        "✅ <b>Вы записаны!</b>\n\n"
        f"💅 {service['name']}\n"
        f"👩 Мастер: {master['name']}\n"
        f"📅 {pretty_date}, {fmt_time(start_min)}\n"
        f"💰 {money(service['price'])}\n\n"
        f"📍 {SALON['address']}\n"
        "Ждём вас!",
        reply_markup=MENU,
    )

    if ADMIN_ID:
        username = f"@{message.from_user.username}" if message.from_user.username else "—"
        await message.bot.send_message(
            ADMIN_ID,
            "🔔 <b>Новая запись</b>\n\n"
            f"👤 {html.escape(name)} ({html.escape(username)})\n"
            f"📞 {html.escape(phone)}\n"
            f"💅 {service['name']}\n"
            f"👩 {master['name']}\n"
            f"📅 {pretty_date}, {fmt_time(start_min)}",
        )


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


# ---------- веб-часть (мини-приложение и его API) ----------

async def health(request):
    return web.Response(text="ok")


async def webapp_page(request):
    return web.FileResponse(
        BASE_DIR / "webapp" / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


async def api_config(request):
    return web.json_response({
        "salon": SALON["name"],
        "today": now_local().date().isoformat(),
        "days": BOOKING_DAYS,
        "services": [
            {"id": s["id"], "name": s["name"], "price": s["price"], "minutes": s["minutes"]}
            for s in SERVICES
        ],
        "masters": MASTERS,
    })


async def api_slots(request):
    try:
        master_id = int(request.query["master"])
        service_id = int(request.query["service"])
        date_str = request.query["date"]
    except (KeyError, ValueError):
        return web.json_response({"slots": []})
    slots = [fmt_time(t) for t in free_slots(master_id, service_id, date_str)]
    return web.json_response({"slots": slots})


# ---------- запуск ----------

async def on_startup(bot: Bot):
    await bot.set_webhook(f"{BASE_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET)


def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/app", webapp_page)
    app.router.add_get("/api/config", api_config)
    app.router.add_get("/api/slots", api_slots)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(
        app, path=WEBHOOK_PATH
    )
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)


main()