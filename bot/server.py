import os
from contextlib import suppress

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from reviews_store import init_db, list_reviews, stats

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram/webhook")

app = FastAPI(title="F3hcqcx Reviews API", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://lainyoffc.github.io"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_bot = None


def get_bot():
    global _bot
    if _bot is None and BOT_TOKEN:
        import telebot
        from channel_sync import register_channel_handlers

        _bot = telebot.TeleBot(BOT_TOKEN)
        register_channel_handlers(_bot)
    return _bot


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
        return {"ok": False, "error": "BOT_TOKEN is not configured"}

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


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
