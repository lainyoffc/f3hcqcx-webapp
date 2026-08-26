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
PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET", "")

app = FastAPI(title="F3hcqcx Reviews API", version="2.6.1")
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
    user_name: str = Field(min_length=2, max_length=50)
    product: str = Field(min_length=2, max_length=80)


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


def cleanup_test_review():
    from reviews_store import DATABASE_URL, _conn
    if not DATABASE_URL:
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reviews WHERE id = %s", ("channel-0-1787741758314",))
            conn.commit()
    except Exception as exc:
        print(f"[reviews] setup test cleanup skipped: {exc}")


def load_orders():
    path = os.path.join(os.path.dirname(__file__), "orders.json")
    if not os.path.exists(path):
        return {"orders": [], "users": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"orders": [], "users": {}}
    except (OSError, json.JSONDecodeError):
        return {"orders": [], "users": {}}


def save_orders(data):
    path = os.path.join(os.path.dirname(__file__), "orders.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_order_by_platega_transaction(transaction_id: str):
    data = load_orders()
    for order in data.get("orders", []):
        if str(order.get("platega_transaction_id", "")) == str(transaction_id):
            return data, order
    return data, None


def find_order_by_id(order_id: str):
    data = load_orders()
    for order in data.get("orders", []):
        if str(order.get("order_id")) == str(order_id):
            return data, order
    return data, None


def trigger_fragment_for_order(order: dict):
    bot = get_bot()
    if not bot or not _bot_module or not hasattr(_bot_module, "issue_stars_after_payment"):
        return
    try:
        _bot_module.issue_stars_after_payment(order)
    except Exception as exc:
        print(f"[fragment] trigger failed: {exc}")


@app.on_event("startup")
def startup():
    init_db()
    cleanup_test_review()
    bot = get_bot()
    if bot:
        try:
            from support_features import register_support_handlers
            register_support_handlers(bot, _bot_module)
            print("[telegram] support/info/checks handlers registered")
        except Exception as exc:
            print(f"[telegram] support handlers unavailable: {exc}")
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


@app.on_event("shutdown")
def shutdown():
    pass


@app.get("/api/health")
def health():
    bot = get_bot()
    return {
        "ok": True,
        "service": "f3hcqcx-reviews",
        "database": True,
        "telegram_webhook": bool(bot and WEBHOOK_URL),
        "platega": bool(PLATEGA_MERCHANT_ID and PLATEGA_SECRET),
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
        if update and update.message:
            incoming_text = (update.message.text or "").strip()
            if incoming_text:
                command = incoming_text.split()[0].lower().split("@")[0]
                if command == "/start":
                    if _bot_module and hasattr(_bot_module, "start_handler"):
                        _bot_module.start_handler(update.message)
                        return {"ok": True, "handled": "start"}

        if update and update.channel_post:
            try:
                from channel_sync import sync_channel_post
                sync_channel_post(update.channel_post)
            except Exception as exc:
                print(f"[telegram] channel sync error: {exc}")
            return {"ok": True}

        bot.process_new_updates([update])
        return {"ok": True}
    except Exception as exc:
        print(f"[telegram] update processing failed: {exc}")
        return {"ok": True}


@app.post("/platega/callback")
async def platega_callback(request: Request):
    if not PLATEGA_MERCHANT_ID or not PLATEGA_SECRET:
        return {"ok": False, "error": "Platega is not configured"}

    merchant = request.headers.get("X-MerchantId", "")
    secret = request.headers.get("X-Secret", "")
    if not hmac.compare_digest(merchant, PLATEGA_MERCHANT_ID) or not hmac.compare_digest(secret, PLATEGA_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Platega credentials")

    payload = await request.json()
    transaction_id = payload.get("id") or payload.get("transactionId")
    status = str(payload.get("status", "")).upper()
    amount = payload.get("amount")
    currency = payload.get("currency")
    print(f"[platega] callback transaction={transaction_id} status={status} amount={amount} {currency}")

    if not transaction_id:
        return {"ok": True, "ignored": "missing transaction id"}

    data, order = find_order_by_platega_transaction(transaction_id)
    if not order:
        return {"ok": True, "ignored": "unknown transaction"}

    if status == "CONFIRMED":
        if order.get("status") in {"processing", "completed"}:
            return {"ok": True, "already_processed": True}
        order["status"] = "paid"
        order["paid_at"] = time.time()
        order["platega_status"] = status
        save_orders(data)
        trigger_fragment_for_order(order)
    elif status == "CANCELED":
        order["status"] = "cancelled"
        order["platega_status"] = status
        save_orders(data)
    elif status == "CHARGEBACKED":
        order["status"] = "chargebacked"
        order["platega_status"] = status
        save_orders(data)

    return {"ok": True}


@app.get("/api/order/{order_id}")
def get_order(order_id: str):
    _, order = find_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


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
    user_name = payload.user_name.strip() or user.get("first_name") or user.get("username") or "Клиент"
    product = payload.product.strip()
    message_id = int(time.time() * 1000)
    row = upsert_channel_review(
        chat_id=0,
        message_id=message_id,
        text=text,
        rating=payload.rating,
        date=time_to_datetime(time.time()),
        username=username,
        user_name=user_name,
        product=product,
    )
    return {"ok": True, "review": row}


def time_to_datetime(timestamp: float):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
