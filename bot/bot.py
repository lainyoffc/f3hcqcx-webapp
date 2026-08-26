import telebot
from telebot import types
from datetime import datetime
from dotenv import load_dotenv
import time
import json
import os
import urllib.request
import urllib.error
import uuid

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REVIEWS_CHANNEL = os.getenv("REVIEWS_CHANNEL", "OtziviF3hcqcx1")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "F3hcqcx")
REVIEWS_WEBAPP_URL = os.getenv("REVIEWS_WEBAPP_URL", "https://lainyoffc.github.io/f3hcqcx-webapp/reviews.html")

PRICE_PER_STAR_RUB = 1.53
CURRENCY = "₽"
MIN_STARS = 50
MAX_STARS = 100000

PLATEGA_URL = os.getenv("PLATEGA_URL", "https://app.platega.io/v2/transaction/process")
PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET", "")
PLATEGA_RETURN_URL = os.getenv("PLATEGA_RETURN_URL", REVIEWS_WEBAPP_URL)
PLATEGA_FAILED_URL = os.getenv("PLATEGA_FAILED_URL", REVIEWS_WEBAPP_URL)

FRAGMENT_API_URL = os.getenv("FRAGMENT_API_URL", "https://api.fragment-api.io")
FRAGMENT_API_KEY = os.getenv("FRAGMENT_API_KEY", "")
FRAGMENT_PAYMENT_METHOD = os.getenv("FRAGMENT_PAYMENT_METHOD", "usdt_ton")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Добавь BOT_TOKEN в переменные окружения Render")

bot = telebot.TeleBot(BOT_TOKEN)

try:
    from channel_sync import register_channel_handlers
    register_channel_handlers(bot)
except Exception as exc:
    print(f"[reviews] channel sync is unavailable: {exc}")

ORDERS_FILE = "orders.json"
reviews_cache = []
orders_data = {"orders": [], "users": {}}
pending_custom_amount = set()


def load_orders():
    global orders_data
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                orders_data = data
        except (OSError, json.JSONDecodeError):
            pass


def save_orders():
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders_data, f, ensure_ascii=False, indent=2)


load_orders()


def format_price(amount: int) -> str:
    total = amount * PRICE_PER_STAR_RUB
    return f"{total:,.2f}".replace(",", " ").replace(".", ",")


def _platega_headers():
    return {
        "X-MerchantId": PLATEGA_MERCHANT_ID,
        "X-Secret": PLATEGA_SECRET,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def create_platega_payment(order: dict):
    if not PLATEGA_MERCHANT_ID or not PLATEGA_SECRET:
        return None, "PLATEGA_MERCHANT_ID / PLATEGA_SECRET не настроены"

    payload = {
        "paymentDetails": {
            "amount": round(float(order["total_price"]), 2),
            "currency": "RUB",
        },
        "description": f"Покупка {order['amount']} Telegram Stars — заказ #{order['order_id']}",
        "return": PLATEGA_RETURN_URL,
        "failedUrl": PLATEGA_FAILED_URL,
        "payload": json.dumps({"order_id": order["order_id"], "user_id": order["user_id"]}, ensure_ascii=False),
        "metadata": {
            "userId": str(order["user_id"]),
            "userName": order.get("username", ""),
        },
    }
    request = urllib.request.Request(
        PLATEGA_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_platega_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        transaction_id = body.get("transactionId") or body.get("id")
        payment_url = body.get("url") or body.get("redirect")
        if not transaction_id or not payment_url:
            return None, f"Platega вернул неполный ответ: {body}"
        return {"transaction_id": transaction_id, "payment_url": payment_url, "raw": body}, None
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        return None, f"Platega HTTP {exc.code}: {details[:500]}"
    except Exception as exc:
        return None, f"Platega error: {exc}"


def create_order_for_user(user, amount: int):
    if amount < MIN_STARS or amount > MAX_STARS:
        raise ValueError(f"Количество должно быть от {MIN_STARS:,} до {MAX_STARS:,} звезд")

    if not user.username:
        raise ValueError("Для автоматической выдачи Stars у Telegram-аккаунта должен быть установлен @username.")

    user_id = user.id
    username = f"@{user.username}"
    order_id = f"{user_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    total_price = amount * PRICE_PER_STAR_RUB

    order = {
        "order_id": order_id,
        "user_id": user_id,
        "username": username,
        "recipient": user.username,
        "amount": amount,
        "price_per_star": PRICE_PER_STAR_RUB,
        "total_price": total_price,
        "currency": "RUB",
        "status": "pending_payment",
        "created_at": datetime.now().isoformat(),
    }

    payment, error = create_platega_payment(order)
    if error:
        raise RuntimeError(error)

    order["platega_transaction_id"] = payment["transaction_id"]
    order["payment_url"] = payment["payment_url"]
    orders_data["orders"].append(order)
    orders_data["users"].setdefault(str(user_id), {}).setdefault("orders", []).append(order_id)
    save_orders()

    text = (
        f"⭐ *Заказ #{order_id}*\n\n"
        f"👤 *Получатель:* {username}\n"
        f"⭐ *Количество:* {amount} звезд\n"
        f"💰 *1 ⭐:* {PRICE_PER_STAR_RUB:.2f} {CURRENCY}\n"
        f"💵 *К оплате:* {format_price(amount)} {CURRENCY}\n\n"
        "После подтверждения оплаты Stars будут выданы автоматически."
    )
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💳 Оплатить через Platega", url=payment["payment_url"]))
    keyboard.add(types.InlineKeyboardButton(text="📋 Статус", callback_data=f"status_{order_id}"))
    bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="Markdown")


def issue_stars_after_payment(order: dict):
    if order.get("status") in {"processing", "completed"} and order.get("fragment_transaction_id"):
        return
    if not FRAGMENT_API_KEY:
        print("[fragment] FRAGMENT_API_KEY is not configured")
        return

    recipient = order.get("recipient") or str(order.get("username", "")).lstrip("@")
    quantity = int(order.get("amount", 0))
    if not recipient or quantity < MIN_STARS:
        print("[fragment] invalid recipient or quantity")
        return

    payload = {
        "product_type": "stars",
        "recipient": recipient,
        "quantity": str(quantity),
        "payment_method": FRAGMENT_PAYMENT_METHOD,
        "idempotency_key": order["order_id"],
    }
    request = urllib.request.Request(
        f"{FRAGMENT_API_URL.rstrip('/')}/api/purchase",
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-API-Key": FRAGMENT_API_KEY, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    order["status"] = "processing"
    save_orders()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        order["fragment_transaction_id"] = data.get("transaction_id")
        order["fragment_status"] = data.get("status", "pending")
        if data.get("status") == "completed":
            order["status"] = "completed"
        save_orders()
        try:
            bot.send_message(order["user_id"], f"✅ Оплата подтверждена. Выдаём {quantity} ⭐ на {order['username']}.")
        except Exception:
            pass
        print(f"[fragment] purchase created for {order['order_id']}: {data}")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        order["status"] = "paid"
        order["fragment_error"] = f"HTTP {exc.code}: {details[:500]}"
        save_orders()
        print(f"[fragment] HTTP {exc.code}: {details[:500]}")
    except Exception as exc:
        order["status"] = "paid"
        order["fragment_error"] = str(exc)
        save_orders()
        print(f"[fragment] error: {exc}")


def get_main_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars"))
    keyboard.add(types.InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    keyboard.add(types.InlineKeyboardButton(text="💬 Отзывы", web_app=types.WebAppInfo(url=REVIEWS_WEBAPP_URL)))
    keyboard.add(types.InlineKeyboardButton(text="❓ Поддержка", callback_data="support"))
    keyboard.add(types.InlineKeyboardButton(text="ℹ️ Информация", callback_data="info"))
    keyboard.add(types.InlineKeyboardButton(text="🧾 Чеки", callback_data="checks"))
    return keyboard


def get_stars_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton(text="50 ⭐", callback_data="buy_50"), types.InlineKeyboardButton(text="100 ⭐", callback_data="buy_100"))
    keyboard.row(types.InlineKeyboardButton(text="150 ⭐", callback_data="buy_150"), types.InlineKeyboardButton(text="250 ⭐", callback_data="buy_250"))
    keyboard.row(types.InlineKeyboardButton(text="350 ⭐", callback_data="buy_350"), types.InlineKeyboardButton(text="500 ⭐", callback_data="buy_500"))
    keyboard.row(types.InlineKeyboardButton(text="750 ⭐", callback_data="buy_750"), types.InlineKeyboardButton(text="1000 ⭐", callback_data="buy_1000"))
    keyboard.row(types.InlineKeyboardButton(text="1500 ⭐", callback_data="buy_1500"), types.InlineKeyboardButton(text="2500 ⭐", callback_data="buy_2500"))
    keyboard.row(types.InlineKeyboardButton(text="5000 ⭐", callback_data="buy_5000"), types.InlineKeyboardButton(text="10000 ⭐", callback_data="buy_10000"))
    keyboard.row(types.InlineKeyboardButton(text="25000 ⭐", callback_data="buy_25000"), types.InlineKeyboardButton(text="⚙️ Указать своё...", callback_data="buy_custom"))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    return keyboard


def get_reviews_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="📱 Открыть отзывы", web_app=types.WebAppInfo(url=REVIEWS_WEBAPP_URL)))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    return keyboard


def fetch_reviews_from_channel():
    global reviews_cache
    reviews_file = os.path.join(os.path.dirname(__file__), "reviews_data.json")
    try:
        with open(reviews_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        reviews_cache = data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        reviews_cache = []
    return bool(reviews_cache)


def format_reviews(filter_type="all"):
    if not reviews_cache:
        return "📝 Отзывов пока нет. Будьте первым, кто оставит отзыв!"
    filtered_reviews = reviews_cache
    if filter_type == "positive":
        filtered_reviews = [r for r in reviews_cache if r.get("rating", 0) >= 4]
    elif filter_type == "negative":
        filtered_reviews = [r for r in reviews_cache if r.get("rating", 0) < 4]
    if not filtered_reviews:
        return "📝 Отзывов с таким фильтром пока нет."
    avg_rating = sum(r.get("rating", 0) for r in reviews_cache) / len(reviews_cache)
    text = f"⭐ *Отзывы клиентов*\n\n📊 Рейтинг: {avg_rating:.1f}/5.0 ({len(reviews_cache)} отзывов)\n\n"
    for review in filtered_reviews:
        text += f"👤 {review.get('user', 'Клиент')}\n"
        text += f"{'⭐' * int(review.get('rating', 5))}\n"
        text += f"{review.get('text', '')}\n"
        text += f"📅 {review.get('date', '')}\n\n────────────────────\n\n"
    text += "_Оставить отзыв могут только покупатели_"
    return text


@bot.message_handler(commands=["start"])
def start_handler(message):
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    text = f"👋 Привет, {username}!\n\n🌟 *F3hcqcx Stars* — магазин Telegram звёзд\n\n🎁 *Бонус для новых клиентов:* -10% на первый заказ!\n\nВыберите действие в меню ниже:"
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == "buy_stars")
def buy_stars_handler(call):
    text = (
        "⭐ *Покупка звёзд*\n\n"
        f"💰 *Цена за 1 ⭐:* {PRICE_PER_STAR_RUB:.2f} {CURRENCY}\n\n"
        f"— Минимум: {MIN_STARS:,} звезд\n"
        f"— Максимум: {MAX_STARS:,} звезд\n\n"
        "🔎 Выберите количество звёзд для покупки:"
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=get_stars_keyboard(), parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "profile")
def profile_handler(call):
    username = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    text = f"👤 *Ваш профиль*\n\n🆔 ID: {call.from_user.id}\n👤 Имя: {username}\n📊 Покупок: 0\n⭐ Потрачено: 0 звёзд\n\n🎁 *Бонусный статус:* Новый клиент\n_История покупок появится здесь_"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "reviews")
def reviews_handler(call):
    fetch_reviews_from_channel()
    avg = sum(r.get("rating", 0) for r in reviews_cache) / len(reviews_cache) if reviews_cache else 0
    text = f"⭐ *Отзывы наших клиентов*\n\n📊 *Всего отзывов:* {len(reviews_cache)}\n⭐ *Средняя оценка:* {avg:.1f}/5.0\n\n_Полные отзывы открываются в WebApp._"
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💬 Открыть отзывы", web_app=types.WebAppInfo(url=REVIEWS_WEBAPP_URL)))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("reviews_"))
def reviews_filter_handler(call):
    filter_type = call.data.replace("reviews_", "")
    if filter_type == "refresh":
        fetch_reviews_from_channel()
        text = format_reviews("all")
    else:
        text = format_reviews(filter_type)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=get_reviews_keyboard(), parse_mode="Markdown")
    except Exception:
        pass
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: message.chat.id in pending_custom_amount)
def custom_amount_message_handler(message):
    pending_custom_amount.discard(message.chat.id)
    raw = (message.text or "").strip().replace(" ", "").replace(",", ".")
    try:
        amount_float = float(raw)
    except ValueError:
        bot.send_message(message.chat.id, f"❌ Введите целое число от {MIN_STARS} до {MAX_STARS}.")
        return
    if not amount_float.is_integer():
        bot.send_message(message.chat.id, "❌ Количество звёзд должно быть целым числом.")
        return
    amount = int(amount_float)
    if amount < MIN_STARS or amount > MAX_STARS:
        bot.send_message(message.chat.id, f"❌ Допустимо от {MIN_STARS:,} до {MAX_STARS:,} звезд.")
        return
    try:
        create_order_for_user(message.from_user, amount)
    except Exception as exc:
        bot.send_message(message.chat.id, f"❌ {exc}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_handler(call):
    value = call.data.replace("buy_", "")
    if value == "custom":
        pending_custom_amount.add(call.message.chat.id)
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"⚙️ Введите количество звезд от {MIN_STARS:,} до {MAX_STARS:,}.\n\n💰 Цена: {PRICE_PER_STAR_RUB:.2f} {CURRENCY} за 1 ⭐\n💵 Например: 750 → {format_price(750)} {CURRENCY}")
        return
    try:
        amount = int(value)
        if amount < MIN_STARS or amount > MAX_STARS:
            raise ValueError
        create_order_for_user(call.from_user, amount)
        bot.answer_callback_query(call.id)
    except ValueError:
        bot.answer_callback_query(call.id, f"Допустимо от {MIN_STARS:,} до {MAX_STARS:,}", show_alert=True)
    except Exception as exc:
        bot.answer_callback_query(call.id, "Не удалось создать оплату", show_alert=True)
        bot.send_message(call.message.chat.id, f"❌ {exc}")


@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_handler(call):
    bot.edit_message_text("Выберите действие:", call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard())
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("status_"))
def order_status_handler(call):
    order_id = call.data.replace("status_", "")
    order = next((o for o in orders_data["orders"] if o.get("order_id") == order_id), None)
    if not order:
        bot.answer_callback_query(call.id, "❌ Заказ не найден", show_alert=True)
        return
    if int(order.get("user_id", -1)) != int(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
        return
    status_emoji = {"pending_payment": "💳", "paid": "✅", "processing": "⚙️", "completed": "✅", "cancelled": "❌"}
    status_text = {"pending_payment": "Ожидает оплаты", "paid": "Оплачен, выдаём Stars", "processing": "Выдаём Stars", "completed": "Выполнен", "cancelled": "Отменён"}
    text = (
        f"📋 *Статус заказа #{order_id}*\n\n"
        f"{status_emoji.get(order['status'], '❓')} *Статус:* {status_text.get(order['status'], 'Неизвестно')}\n"
        f"⭐ *Количество:* {order['amount']} звезд\n"
        f"💰 *1 ⭐:* {PRICE_PER_STAR_RUB:.2f} {CURRENCY}\n"
        f"💵 *Итого:* {format_price(int(order['amount']))} {CURRENCY}\n"
        f"📅 *Создан:* {order['created_at']}\n"
    )
    if order.get("payment_url"):
        text += "\n💳 Нажмите кнопку ниже, чтобы оплатить.\n"
    if order.get("status") == "completed":
        text += "\n✅ *Stars успешно выданы!*\n"
    keyboard = types.InlineKeyboardMarkup()
    if order.get("payment_url") and order.get("status") == "pending_payment":
        keyboard.add(types.InlineKeyboardButton(text="💳 Оплатить", url=order["payment_url"]))
    keyboard.add(types.InlineKeyboardButton(text="🔄 Обновить", callback_data=f"status_{order_id}"))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="buy_stars"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(call.id)


if __name__ == "__main__":
    try:
        print("Бот запущен!")
        bot.polling(none_stop=True, timeout=60, long_polling_timeout=30, allowed_updates=["message", "callback_query", "channel_post", "edited_channel_post"])
    except KeyboardInterrupt:
        print("Бот остановлен.")