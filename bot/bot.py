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


def create_xtr_invoice(order: dict):
    payload = json.dumps({"order_id": order["order_id"], "user_id": order["user_id"]}, ensure_ascii=False, separators=(",", ":"))
    description = f"Покупка {order['amount']} Telegram Stars для {order['username']}. Внутренняя цена: {PRICE_PER_STAR_RUB:.2f} ₽ за ⭐."
    bot.send_invoice(
        chat_id=order["user_id"],
        title=f"Telegram Stars — {order['amount']} ⭐",
        description=description,
        invoice_payload=payload,
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label=f"{order['amount']} Telegram Stars", amount=order["amount"])],
        start_parameter=f"stars_{order['order_id']}",
    )


def create_order_for_user(user, amount: int):
    if amount < MIN_STARS or amount > MAX_STARS:
        raise ValueError(f"Количество должно быть от {MIN_STARS:,} до {MAX_STARS:,} звезд")
    if not user.username:
        raise ValueError("Для автоматической выдачи Stars у Telegram-аккаунта должен быть установлен @username.")
    user_id = user.id
    username = f"@{user.username}"
    order_id = f"{user_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    order = {
        "order_id": order_id,
        "user_id": user_id,
        "username": username,
        "recipient": user.username,
        "amount": int(amount),
        "price_per_star_rub": PRICE_PER_STAR_RUB,
        "total_price_rub": round(amount * PRICE_PER_STAR_RUB, 2),
        "payment_currency": "XTR",
        "payment_amount_xtr": int(amount),
        "status": "pending_payment",
        "created_at": datetime.now().isoformat(),
    }
    orders_data["orders"].append(order)
    orders_data["users"].setdefault(str(user_id), {}).setdefault("orders", []).append(order_id)
    save_orders()
    try:
        create_xtr_invoice(order)
    except Exception:
        orders_data["orders"] = [item for item in orders_data["orders"] if item.get("order_id") != order_id]
        user_orders = orders_data["users"].get(str(user_id), {}).get("orders", [])
        if order_id in user_orders:
            user_orders.remove(order_id)
        save_orders()
        raise


def find_order(order_id: str):
    return next((o for o in orders_data.get("orders", []) if str(o.get("order_id")) == str(order_id)), None)


def issue_stars_after_payment(order: dict):
    if order.get("status") in {"processing", "completed"} and order.get("fragment_transaction_id"):
        return
    if not FRAGMENT_API_KEY:
        print("[fragment] FRAGMENT_API_KEY is not configured")
        order["fragment_error"] = "FRAGMENT_API_KEY is not configured"
        save_orders()
        return
    recipient = order.get("recipient") or str(order.get("username", "")).lstrip("@")
    quantity = int(order.get("amount", 0))
    if not recipient or quantity < MIN_STARS:
        print("[fragment] invalid recipient or quantity")
        order["fragment_error"] = "Invalid recipient or quantity"
        save_orders()
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
    order["paid_at"] = time.time()
    save_orders()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        order["fragment_transaction_id"] = data.get("transaction_id")
        order["fragment_status"] = data.get("status", "pending")
        if data.get("status") == "completed":
            order["status"] = "completed"
        save_orders()
        bot.send_message(order["user_id"], f"✅ Оплата подтверждена.\n\n⭐ Выдаём {quantity} Stars на {order['username']}.\n📋 Статус: {order['status']}")
        print(f"[fragment] purchase created for {order['order_id']}: {data}")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        order["status"] = "paid"
        order["fragment_error"] = f"HTTP {exc.code}: {details[:500]}"
        save_orders()
        print(f"[fragment] HTTP {exc.code}: {details[:500]}")
        bot.send_message(order["user_id"], "✅ Оплата получена, но автоматическая выдача Stars пока не завершилась.\nЗаказ сохранён, администратор сможет проверить его статус.")
    except Exception as exc:
        order["status"] = "paid"
        order["fragment_error"] = str(exc)
        save_orders()
        print(f"[fragment] error: {exc}")
        bot.send_message(order["user_id"], "✅ Оплата получена, но выдача Stars временно не завершилась.\nЗаказ сохранён для повторной проверки.")


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
        f"💰 *Внутренняя цена:* {PRICE_PER_STAR_RUB:.2f} {CURRENCY} за ⭐\n"
        "💳 *Способ оплаты:* Telegram Stars (XTR)\n\n"
        f"— Минимум: {MIN_STARS:,} звезд\n"
        f"— Максимум: {MAX_STARS:,} звезд\n\n"
        "🔎 Выберите количество для оплаты:"
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
        bot.send_message(message.chat.id, f"🧾 Счёт создан: {amount} ⭐.\nПосле оплаты Telegram Stars бот автоматически обработает заказ.\nОриентир по внутренней цене: {format_price(amount)} ₽.")
    except Exception as exc:
        bot.send_message(message.chat.id, f"❌ {exc}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_handler(call):
    value = call.data.replace("buy_", "")
    if value == "custom":
        pending_custom_amount.add(call.message.chat.id)
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"⚙️ Введите количество звезд от {MIN_STARS:,} до {MAX_STARS:,}.\n\n💰 Внутренняя цена: {PRICE_PER_STAR_RUB:.2f} {CURRENCY} за 1 ⭐\n💳 Оплата будет в Telegram Stars (XTR).\n💵 Например: 750 → {format_price(750)} {CURRENCY}")
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
        bot.answer_callback_query(call.id, "Не удалось создать счёт", show_alert=True)
        bot.send_message(call.message.chat.id, f"❌ {exc}")


@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout_handler(query):
    try:
        payload = json.loads(query.invoice_payload)
        order_id = str(payload.get("order_id", ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        bot.answer_pre_checkout_query(query.id, ok=False, error_message="Некорректный заказ.")
        return
    order = find_order(order_id)
    if not order:
        bot.answer_pre_checkout_query(query.id, ok=False, error_message="Заказ не найден или уже закрыт.")
        return
    expected = int(order.get("payment_amount_xtr", order.get("amount", 0)))
    if query.currency != "XTR" or int(query.total_amount) != expected:
        bot.answer_pre_checkout_query(query.id, ok=False, error_message="Сумма заказа не совпадает.")
        return
    if order.get("status") != "pending_payment":
        bot.answer_pre_checkout_query(query.id, ok=False, error_message="Этот заказ уже обработан.")
        return
    bot.answer_pre_checkout_query(query.id, ok=True)


@bot.message_handler(content_types=["successful_payment"])
def successful_payment_handler(message):
    payment = message.successful_payment
    try:
        payload = json.loads(payment.invoice_payload)
        order_id = str(payload.get("order_id", ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        bot.send_message(message.chat.id, "❌ Не удалось определить заказ.")
        return
    order = find_order(order_id)
    if not order:
        bot.send_message(message.chat.id, "✅ Платёж получен, но заказ не найден. Обратитесь в поддержку.")
        return
    if order.get("status") in {"processing", "completed"}:
        return
    order["status"] = "paid"
    order["telegram_payment_charge_id"] = getattr(payment, "telegram_payment_charge_id", "")
    order["telegram_provider_payment_charge_id"] = getattr(payment, "provider_payment_charge_id", "")
    order["paid_amount_xtr"] = int(getattr(payment, "total_amount", order["amount"]))
    order["paid_currency"] = payment.currency
    save_orders()
    bot.send_message(message.chat.id, f"✅ Оплата {order['paid_amount_xtr']} XTR подтверждена.\n⏳ Передаём заказ на выдачу {order['amount']} ⭐.")
    issue_stars_after_payment(order)


@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_handler(call):
    bot.edit_message_text("Выберите действие:", call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard())
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("status_"))
def order_status_handler(call):
    order_id = call.data.replace("status_", "")
    order = find_order(order_id)
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
        f"{status_emoji.get(order.get('status'), '❓')} *Статус:* {status_text.get(order.get('status'), 'Неизвестно')}\n"
        f"⭐ *Количество:* {order.get('amount', 0)} звезд\n"
        f"💰 *1 ⭐:* {PRICE_PER_STAR_RUB:.2f} {CURRENCY}\n"
        f"💵 *Внутренняя сумма:* {format_price(int(order.get('amount', 0)))} {CURRENCY}\n"
        f"💳 *Оплата:* {order.get('paid_amount_xtr', order.get('payment_amount_xtr', 0))} XTR\n"
        f"📅 *Создан:* {order.get('created_at', '')}\n"
    )
    if order.get("status") == "completed":
        text += "\n✅ *Stars успешно выданы!*\n"
    elif order.get("status") == "paid":
        text += "\n⏳ *Платёж получен, выдача ещё не завершена.*\n"
    elif order.get("status") == "pending_payment":
        text += "\n💳 *Нажмите кнопку оплаты в исходном счёте.*\n"
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="🔄 Обновить", callback_data=f"status_{order_id}"))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="buy_stars"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(call.id)


if __name__ == "__main__":
    try:
        print("Бот запущен!")
        bot.polling(none_stop=True, timeout=60, long_polling_timeout=30, allowed_updates=["message", "callback_query", "pre_checkout_query", "channel_post", "edited_channel_post"])
    except KeyboardInterrupt:
        print("Бот остановлен.")
