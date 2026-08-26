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
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "F3hcqcx")
REVIEWS_WEBAPP_URL = os.getenv("REVIEWS_WEBAPP_URL", "https://lainyoffc.github.io/f3hcqcx-webapp/reviews.html")
PURCHASE_BANNER_URL = "https://raw.githubusercontent.com/lainyoffc/f3hcqcx-webapp/main/bot/assets/stars-banner.jpg"
PURCHASE_BANNER_PATH = os.path.join(os.path.dirname(__file__), "assets", "stars-banner.jpg")

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
purchase_menu_messages = {}


def load_orders():
    global orders_data
    if not os.path.exists(ORDERS_FILE):
        return
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


def safe_delete(chat_id, message_id):
    if not message_id:
        return
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def clear_purchase_menu(chat_id, message_id=None):
    old_id = message_id or purchase_menu_messages.pop(chat_id, None)
    if old_id:
        safe_delete(chat_id, old_id)
    purchase_menu_messages.pop(chat_id, None)


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


def purchase_caption():
    return (
        "⭐ *Покупка звёзд*\n\n"
        f"💰 *Внутренняя цена:* {PRICE_PER_STAR_RUB:.2f} {CURRENCY} за ⭐\n"
        "💳 *Способ оплаты:* Telegram Stars (XTR)\n\n"
        f"— Минимум: {MIN_STARS:,} звезд\n"
        f"— Максимум: {MAX_STARS:,} звезд\n\n"
        "🔎 Выберите количество для оплаты:"
    )


def send_purchase_menu(chat_id):
    clear_purchase_menu(chat_id)
    message = None
    try:
        if os.path.isfile(PURCHASE_BANNER_PATH):
            with open(PURCHASE_BANNER_PATH, "rb") as photo:
                message = bot.send_photo(
                    chat_id,
                    photo,
                    caption=purchase_caption(),
                    reply_markup=get_stars_keyboard(),
                    parse_mode="Markdown",
                )
        else:
            message = bot.send_message(
                chat_id,
                purchase_caption(),
                reply_markup=get_stars_keyboard(),
                parse_mode="Markdown",
            )
    except Exception as exc:
        print(f"[purchase_menu] send failed: {exc}")
        message = bot.send_message(
            chat_id,
            purchase_caption(),
            reply_markup=get_stars_keyboard(),
            parse_mode="Markdown",
        )
    purchase_menu_messages[chat_id] = message.message_id
    return message


def send_main_menu(chat_id, username=None):
    if not username:
        try:
            chat = bot.get_chat(chat_id)
            username = f"@{getattr(chat, 'username', None)}" if getattr(chat, 'username', None) else getattr(chat, 'first_name', 'Клиент')
        except Exception:
            username = "Клиент"
    text = (
        f"👋 Привет, {username}!\n\n"
        "🌟 *F3hcqcx Stars* — магазин Telegram звёзд\n\n"
        "🎁 *Бонус для новых клиентов:* -10% на первый заказ!\n\n"
        "Выберите действие в меню ниже:"
    )
    return bot.send_message(chat_id, text, reply_markup=get_main_keyboard(), parse_mode="Markdown")


def create_xtr_invoice(order: dict):
    payload = json.dumps({"order_id": order["order_id"], "user_id": order["user_id"]}, ensure_ascii=False, separators=(",", ":"))
    description = f"Покупка {order['amount']} Telegram Stars для {order['username']}. Внутренняя цена: {PRICE_PER_STAR_RUB:.2f} ₽ за ⭐."
    return bot.send_invoice(
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

    order_id = f"{user.id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    order = {
        "order_id": order_id,
        "user_id": user.id,
        "username": f"@{user.username}",
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
    orders_data["users"].setdefault(str(user.id), {}).setdefault("orders", []).append(order_id)
    save_orders()
    try:
        invoice = create_xtr_invoice(order)
        order["invoice_message_id"] = getattr(invoice, "message_id", None)
        save_orders()
    except Exception:
        orders_data["orders"] = [item for item in orders_data["orders"] if item.get("order_id") != order_id]
        user_orders = orders_data["users"].get(str(user.id), {}).get("orders", [])
        if order_id in user_orders:
            user_orders.remove(order_id)
        save_orders()
        raise
    return order


def find_order(order_id: str):
    return next((o for o in orders_data.get("orders", []) if str(o.get("order_id")) == str(order_id)), None)


def issue_stars_after_payment(order: dict):
    if order.get("status") in {"processing", "completed"} and order.get("fragment_transaction_id"):
        return
    if not FRAGMENT_API_KEY:
        order["fragment_error"] = "FRAGMENT_API_KEY is not configured"
        save_orders()
        print("[fragment] FRAGMENT_API_KEY is not configured")
        return

    recipient = order.get("recipient") or str(order.get("username", "")).lstrip("@")
    quantity = int(order.get("amount", 0))
    if not recipient or quantity < MIN_STARS:
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
    except Exception as exc:
        details = exc.read().decode("utf-8", errors="replace")[:500] if isinstance(exc, urllib.error.HTTPError) else str(exc)
        order["status"] = "paid"
        order["fragment_error"] = details
        save_orders()
        bot.send_message(order["user_id"], "✅ Оплата получена, но автоматическая выдача Stars пока не завершилась.\nЗаказ сохранён для проверки.")


def cleanup_paid_invoice(order, chat_id):
    safe_delete(chat_id, order.get("invoice_message_id"))


def fetch_reviews_from_channel():
    global reviews_cache
    path = os.path.join(os.path.dirname(__file__), "reviews_data.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        reviews_cache = data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        reviews_cache = []
    return bool(reviews_cache)


def review_text():
    fetch_reviews_from_channel()
    avg = sum(r.get("rating", 0) for r in reviews_cache) / len(reviews_cache) if reviews_cache else 0
    return f"⭐ *Отзывы наших клиентов*\n\n📊 *Всего отзывов:* {len(reviews_cache)}\n⭐ *Средняя оценка:* {avg:.1f}/5.0\n\n_Полные отзывы открываются в WebApp._"


@bot.message_handler(commands=["start"])
def start_handler(message):
    send_main_menu(
        message.chat.id,
        f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name,
    )


@bot.callback_query_handler(func=lambda call: call.data == "buy_stars")
def buy_stars_handler(call):
    try:
        chat_id = call.message.chat.id
        old_message_id = call.message.message_id
        # Новый экран отправляется ПЕРВЫМ. Старое сообщение удаляем только после успеха.
        new_message = send_purchase_menu(chat_id)
        if new_message and new_message.message_id != old_message_id:
            safe_delete(chat_id, old_message_id)
        bot.answer_callback_query(call.id)
    except Exception as exc:
        print(f"[buy_stars] handler failed: {exc}")
        try:
            bot.answer_callback_query(call.id, "Не удалось открыть меню покупки", show_alert=False)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "profile")
def profile_handler(call):
    clear_purchase_menu(call.message.chat.id)
    username = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    text = f"👤 *Ваш профиль*\n\n🆔 ID: {call.from_user.id}\n👤 Имя: {username}\n📊 Покупок: {len([o for o in orders_data.get('orders', []) if o.get('user_id') == call.from_user.id])}\n⭐ Потрачено: 0 звёзд\n\n🎁 *Статус:* Клиент"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "reviews")
def reviews_handler(call):
    clear_purchase_menu(call.message.chat.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💬 Открыть отзывы", web_app=types.WebAppInfo(url=REVIEWS_WEBAPP_URL)))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    bot.edit_message_text(review_text(), call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "support")
def support_handler(call):
    clear_purchase_menu(call.message.chat.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💬 Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    text = "❓ *Поддержка*\n\nПо вопросам заказа, оплаты и выдачи Stars напишите в поддержку."
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "info")
def info_handler(call):
    clear_purchase_menu(call.message.chat.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    text = (
        "ℹ️ *О магазине F3hcqcx Stars*\n\n"
        "⭐ Покупка Telegram Stars\n"
        f"💰 Внутренняя цена: {PRICE_PER_STAR_RUB:.2f} ₽ за ⭐\n"
        "⚡ Заказы оформляются через Telegram\n"
        "🔒 Не передавайте никому коды входа и пароли Telegram.\n\n"
        f"Поддержка: @{SUPPORT_USERNAME.lstrip('@')}"
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "checks")
def checks_handler(call):
    clear_purchase_menu(call.message.chat.id)
    orders = [o for o in orders_data.get("orders", []) if int(o.get("user_id", -1)) == int(call.from_user.id)]
    keyboard = types.InlineKeyboardMarkup()
    lines = ["🧾 *Ваши чеки*\n"]
    if not orders:
        lines.append("Пока заказов нет.")
    else:
        for order in orders[-10:][::-1]:
            lines.append(
                f"#{order['order_id']} — {order.get('amount', 0)} ⭐ — {order.get('status', 'unknown')} — {order.get('paid_amount_xtr', order.get('payment_amount_xtr', 0))} XTR"
            )
            keyboard.add(types.InlineKeyboardButton(text=f"📋 #{order['order_id']}", callback_data=f"status_{order['order_id']}"))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    bot.edit_message_text("\n".join(lines), call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(call.id)
