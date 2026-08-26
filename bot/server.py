import os
import hmac
import hashlib
import json
import time
from contextlib import suppress
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from reviews_store import init_db, list_reviews, stats, upsert_channel_review

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram/webhook")

app = FastAPI(title="F3hcqcx Reviews API", version="2.2.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://lainyoffc.github.io"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Import bot.py so /start, callbacks and channel handlers are registered on
# the same TeleBot instance used by the webhook. bot.py only starts polling
# under __main__, so importing it here does not start a second polling loop.
_bot = None
if BOT_TOKEN:
    try:
        from bot import bot as _bot
    except Exception as exc:
        print(f"[telegram] bot import failed: {exc}")


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field(min_length=5, max_length=500)


def get_bot():
    return _bot


def verify_telegram_init_data(init_data: str) -> dict:
    if not BOT_TOKEN or not init_data:
        raise HTTPException(status_code=401, detail="Telegram authorization is required")
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            raise ValueError("hash missing")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            raise ValueError("invalid signature")
        auth_date = int(pairs.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > 86400:
            raise ValueError("initData expired")
        user = json.loads(pairs.get("user", "{}"))
        if not user.get("id"):
            raise ValueError("telegram user missing")
        return user
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid Telegram initData")


@app.on_event("startup")
def startup():
    init_db()
    bot = get_bot()
    if bot and WEBHOOK_URL:
        with suppress(Exception):
            bot.remove_webhook()
        bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}", drop_pending_updates=False)
        print(f"[telegram] webhook set: {WEBHOOK_URL}{WEBHOOK_PATH}")
    elif not BOT_TOKEN:
        print("[telegram] BOT_TOKEN is not configured; API will run without Telegram webhook")
    elif not bot:
        print("[telegram] bot failed to initialize; webhook is disabled")
    elif not WEBHOOK_URL:
        print("[telegram] WEBHOOK_URL is not configured; Telegram webhook is disabled")


@app.on_event("shutdown")
def shutdown():
    bot = get_bot()
    if bot:
        with suppress(Exception):
            bot.remove_webhook()


@app.get("/api/health")
def health():
    bot = get_bot()
    return {
        "ok": True,
        "service": "f3hcqcx-reviews",
        "database": True,
        "telegram_webhook": bool(bot and WEBHOOK_URL),
    }


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    bot = get_bot()
    if not bot:
        return {"ok": False, "error": "BOT_TOKEN is not configured or bot failed to initialize"}
    data = await request.json()
    import telebot
    update = telebot.types.Update.de_json(data)
    bot.process_new_updates([update])
    return {"ok": True}


@app.get("/api/reviews")
def reviews(offset: int = 0, limit: int = 50, rating: int | None = None):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    items = list_reviews(limit, offset, rating)
    return {"reviews": items, "stats": stats(), "has_more": len(items) == limit}


@app.get("/api/reviews/stats")
def reviews_stats():
    return stats()


@app.post("/api/reviews")
def create_review(payload: ReviewCreate, request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_telegram_init_data(init_data)
    text = payload.text.strip()
    username = f"@{user['username']}" if user.get("username") else None
    user_name = user.get("first_name") or user.get("username") or "Клиент"
    message_id = int(time.time() * 1000)
    row = upsert_channel_review(
        chat_id=0,
        message_id=message_id,
        text=text,
        rating=payload.rating,
        date=time_to_datetime(time.time()),
        username=username,
        user_name=user_name,
        product="Telegram Stars",
    )
    return {"ok": True, "review": row}


def time_to_datetime(timestamp: float):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
