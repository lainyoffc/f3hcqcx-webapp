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

app = FastAPI(title="F3hcqcx Reviews API", version="2.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://lainyoffc.github.io"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_bot = None
_bot_module = None


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field(min_length=5, max_length=500)


def get_bot():
    global _bot, _bot_module
    if _bot is None and BOT_TOKEN:
        import importlib
        _bot_module = importlib.import_module("bot")
        _bot = _bot_module.bot
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
        try:
            me = bot.get_me()
            print(f"[telegram] bot connected: @{me.username} ({me.id})")
        except Exception as exc:
            print(f"[telegram] get_me failed: {exc}")
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


@app.get("/api/telegram-status")
def telegram_status():
    bot = get_bot()
    if not bot:
        return {"ok": False, "configured": False}
    try:
        me = bot.get_me()
        webhook = bot.get_webhook_info()
        return {
            "ok": True,
            "configured": True,
            "bot_id": me.id,
            "username": me.username,
            "first_name": me.first_name,
            "webhook_url": webhook.url,
            "pending_updates": webhook.pending_update_count,
            "last_error": webhook.last_error_message,
        }
    except Exception as exc:
        return {"ok": False, "configured": True, "error": str(exc)}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    bot = get_bot()
    if not bot:
        return {"ok": False, "error": "BOT_TOKEN is not configured"}

    data = await request.json()
    import telebot
    update = telebot.types.Update.de_json(data)

    try:
        # Explicitly dispatch /start so the main menu works even if the
        # framework dispatcher misses a webhook update.
        if update and update.message and (update.message.text or "").split()[0].lower().split("@")[0] == "/start":
            if _bot_module and hasattr(_bot_module, "start_handler"):
                print(f"[telegram] direct /start from {update.message.from_user.id}")
                _bot_module.start_handler(update.message)
                return {"ok": True}

        # Explicitly persist channel posts. This avoids relying on the
        # dispatcher for the critical review-sync path.
        if update and update.channel_post:
            try:
                from channel_sync import sync_channel_post
                sync_channel_post(update.channel_post)
                print(f"[telegram] channel_post handled #{update.channel_post.message_id}")
            except Exception as exc:
                print(f"[telegram] channel sync error: {exc}")
            return {"ok": True}

        print(f"[telegram] update received: {update.update_id if update else 'unknown'}")
        bot.process_new_updates([update])
        return {"ok": True}
    except Exception as exc:
        print(f"[telegram] update processing failed: {exc}")
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
