import base64
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import telebot
from telebot import types
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "F3hcqcx")
REVIEWS_WEBAPP_URL = os.getenv("REVIEWS_WEBAPP_URL", "https://lainych.github.io/f3hcqcx-webapp/reviews.html")

PRICE_PER_STAR_RUB = 1.53
CURRENCY = "₽"
MIN_STARS = 50
MAX_STARS = 100000

FRAGMENT_API_URL = os.getenv("FRAGMENT_API_URL", "https://api.fragment-api.io")
FRAGMENT_API_KEY = os.getenv("FRAGMENT_API_KEY", "")
FRAGMENT_PAYMENT_METHOD = os.getenv("FRAGMENT_PAYMENT_METHOD", "usdt_ton")

ORDERS_FILE = os.path.join(os.path.dirname(__file__), "orders.json")
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
BANNER_B64_PATH = ASSETS_DIR / "main-menu.jpg.b64"
BANNER_RUNTIME_PATH = Path("/tmp/f3hcqcx-main-menu.jpg")

# The five generated section images uploaded to bot/assets.
SECTION_ASSETS = {
    "BUY STARS": ASSETS_DIR / "878d42de-cfa8-456a-9e4b-daacd88b6ffb-fotor-20260826161413.png",
    "PROFILE": ASSETS_DIR / "878d42de-cfa8-456a-9e4b-daacd88b6ffb-fotor-20260826161311.png",
    "SUPPORT": ASSETS_DIR / "878d42de-cfa8-456a-9e4b-daacd88b6ffb(3).png",
    "INFORMATION": ASSETS_DIR / "878d42de-cfa8-456a-9e4b-daacd88b6ffb(2).png",
    "RECEIPTS": ASSETS_DIR / "878d42de-cfa8-456a-9e4b-daacd88b6ffb(1).png",
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Добавь BOT_TOKEN в переменные окружения Render")

bot = telebot.TeleBot(BOT_TOKEN)

reviews_cache = []
orders_data = {"orders": [], "users": {}}
pending_custom_amount = {}
purchase_menu_messages = {}


def ensure_banner():
    if BANNER_RUNTIME_PATH.is_file():
        return True
    try:
        encoded = BANNER_B64_PATH.read_text(encoding="utf-8").strip()
        BANNER_RUNTIME_PATH.write_bytes(base64.b64decode(encoded))
        return True
    except Exception as exc:
        print(f"[banner] load failed: {exc}")
        return False


def asset_path(title):
    path = SECTION_ASSETS.get(title)
    return path if path and path.is_file() else None


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
ensure_banner()


def safe_delete(chat_id, message_id):
    if not message_id:
        return
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def format_price(amount: int) -> str:
    return f"{amount * PRICE_PER_STAR_RUB:,.2f}".replace(",", " ").replace(".", ",")


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
    rows = [(50, 100), (150, 250), (350, 500), (750, 1000), (1500, 2500), (5000, 10000), (25000, None)]
    for left, right in rows:
        buttons = [types.InlineKeyboardButton(text=f"{left} ⭐", callback_data=f"buy_{left}")]
        if right:
            buttons.append(types.InlineKeyboardButton(text=f"{right} ⭐", callback_data=f"buy_{right}"))
        else:
            buttons.append(types.InlineKeyboardButton(text="⚙️ Указать своё...", callback_data="buy_custom"))
        keyboard.row(*buttons)
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    return keyboard


def purchase_text():
    return (
        "⭐ *Покупка звёзд*\n\n"
        f"💰 Цена за 1 ⭐: *{PRICE_PER_STAR_RUB:.2f} ₽*\n\n"
        f"— Минимум: {MIN_STARS:,} звезд\n"
        f"— Максимум: {MAX_STARS:,} звезд\n\n"
        "🔎 Выберите количество для покупки:"
    )


def main_text(username):
    return (
        f"👋 Привет, {username}!\n\n"
        "🌟 *F3hcqcx Stars* — магазин Telegram звёзд\n\n"
        "🎁 *Бонус для новых клиентов:* -10% на первый заказ!\n\n"
        "Выберите действие в меню ниже:"
    )


def send_main_menu(chat_id, username=None):
    if not username:
        try:
            chat = bot.get_chat(chat_id)
            username = f"@{chat.username}" if getattr(chat, "username", None) else (getattr(chat, "first_name", None) or "Клиент")
        except Exception:
            username = "Клиент"
    if ensure_banner():
        with BANNER_RUNTIME_PATH.open("rb") as photo:
            return bot.send_photo(chat_id, photo, caption=main_text(username), reply_markup=get_main_keyboard(), parse_mode="Markdown")
    return bot.send_message(chat_id, main_text(username), reply_markup=get_main_keyboard(), parse_mode="Markdown")


def send_photo_section(chat_id, old_message_id, title, text, keyboard):
    path = asset_path(title)
    if path:
        try:
            with path.open("rb") as photo:
                message = bot.send_photo(
                    chat_id,
                    photo,
                    caption=f"F3hcqcx\n{title}\n\n{text}",
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
            safe_delete(chat_id, old_message_id)
            return message
        except Exception as exc:
            print(f"[section photo:{title}] send failed: {exc}")
    safe_delete(chat_id, old_message_id)
    return bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")


def send_purchase_menu(chat_id):
    old = purchase_menu_messages.pop(chat_id, None)
    safe_delete(chat_id, old)
    path = asset_path("BUY STARS")
    if path:
        with path.open("rb") as photo:
            message = bot.send_photo(
                chat_id,
                photo,
                caption=f"F3hcqcx\nBUY STARS\n\n{purchase_text()}",
                reply_markup=get_stars_keyboard(),
                parse_mode="Markdown",
            )
    else:
        message = bot.send_message(chat_id, purchase_text(), reply_markup=get_stars_keyboard(), parse_mode="Markdown")
    purchase_menu_messages[chat_id] = message.message_id
    return message


def send_section(chat_id, old_message_id, text, keyboard):
    if text.startswith("💬 *Отзывы"):
        safe_delete(chat_id, old_message_id)
        return bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")
    if text.startswith("👤 *Профиль"):
        return send_photo_section(chat_id, old_message_id, "PROFILE", text, keyboard)
    if text.startswith("❓ *Поддержка"):
        return send_photo_section(chat_id, old_message_id, "SUPPORT", text, keyboard)
    if text.startswith("ℹ️ *F3hcqcx Stars"):
        return send_photo_section(chat_id, old_message_id, "INFORMATION", text, keyboard)
    if text.startswith("🧾 *Чеки"):
        return send_photo_section(chat_id, old_message_id, "RECEIPTS", text, keyboard)
    safe_delete(chat_id, old_message_id)
    return bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")


def clear_purchase_menu(chat_id):
    old = purchase_menu_messages.pop(chat_id, None)
    safe_delete(chat_id, old)


def create_order_for_user(user, amount):
    if amount < MIN_STARS or amount > MAX_STARS:
        raise ValueError(f"Количество должно быть от {MIN_STARS:,} до {MAX_STARS:,} звезд")
    if not user.username:
        raise ValueError("Сначала установите @username в Telegram")
    order_id = f"{user.id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    order = {
        "order_id": order_id,
        "user_id": user.id,
        "username": f"@{user.username}",
        "recipient": user.username,
        "amount": int(amount),
        "total_price_rub": round(amount * PRICE_PER_STAR_RUB, 2),
        "payment_currency": "RUB",
        "status": "awaiting_payment_provider",
        "created_at": datetime.now().isoformat(),
    }
    orders_data.setdefault("orders", []).append(order)
    orders_data.setdefault("users", {}).setdefault(str(user.id), {}).setdefault("orders", []).append(order_id)
    save_orders()
    return order


def find_order(order_id):
    return next((o for o in orders_data.get("orders", []) if str(o.get("order_id")) == str(order_id)), None)


def issue_stars_after_payment(order):
    if not FRAGMENT_API_KEY:
        order["fragment_error"] = "FRAGMENT_API_KEY is not configured"
        save_orders()
        return
    order["fragment_status"] = "queued"
    save_orders()


def reviews_text():
    path = os.path.join(os.path.dirname(__file__), "reviews_data.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        reviews = data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        reviews = []
    avg = sum(r.get("rating", 0) for r in reviews) / len(reviews) if reviews else 0
    return f"💬 *Отзывы наших клиентов*\n\n📊 Всего отзывов: *{len(reviews)}*\n⭐ Средняя оценка: *{avg:.1f}/5.0*\n\nПолные отзывы открываются в WebApp."


def checks_text(user_id):
    orders = [o for o in orders_data.get("orders", []) if int(o.get("user_id", -1)) == int(user_id)]
    if not orders:
        return "🧾 *Чеки*\n\nПока заказов нет."
    lines = ["🧾 *Чеки*", ""]
    for order in orders[-10:][::-1]:
        lines.append(f"#{order['order_id']} — {order.get('amount', 0)} ⭐ — {order.get('status', 'unknown')}")
    return "\n".join(lines)


@bot.message_handler(commands=["start"])
def start_handler(message):
    clear_purchase_menu(message.chat.id)
    send_main_menu(message.chat.id, f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name)


@bot.callback_query_handler(func=lambda call: call.data == "buy_stars")
def buy_stars_handler(call):
    try:
        send_purchase_menu(call.message.chat.id)
        safe_delete(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
    except Exception as exc:
        print(f"[buy_stars] {exc}")
        bot.answer_callback_query(call.id, "Не удалось открыть меню", show_alert=False)


@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main_handler(call):
    clear_purchase_menu(call.message.chat.id)
    safe_delete(call.message.chat.id, call.message.message_id)
    send_main_menu(call.message.chat.id, f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "profile")
def profile_handler(call):
    clear_purchase_menu(call.message.chat.id)
    username = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    count = len([o for o in orders_data.get("orders", []) if o.get("user_id") == call.from_user.id])
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    send_section(call.message.chat.id, call.message.message_id, f"👤 *Профиль*\n\n🆔 ID: `{call.from_user.id}`\n👤 Имя: {username}\n📊 Покупок: {count}\n\n🎁 Статус: Клиент", keyboard)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "reviews")
def reviews_handler(call):
    clear_purchase_menu(call.message.chat.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💬 Открыть отзывы", web_app=types.WebAppInfo(url=REVIEWS_WEBAPP_URL)))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    send_section(call.message.chat.id, call.message.message_id, reviews_text(), keyboard)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "support")
def support_handler(call):
    clear_purchase_menu(call.message.chat.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💬 Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    send_section(call.message.chat.id, call.message.message_id, "❓ *Поддержка*\n\nПо вопросам заказа, оплаты и выдачи Stars напишите в поддержку.", keyboard)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "info")
def info_handler(call):
    clear_purchase_menu(call.message.chat.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"))
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    text = f"ℹ️ *F3hcqcx Stars*\n\n⭐ Магазин Telegram Stars\n💰 Цена: {PRICE_PER_STAR_RUB:.2f} ₽ за ⭐\n⚡ Заказы оформляются через бота\n\nПоддержка: @{SUPPORT_USERNAME.lstrip('@')}"
    send_section(call.message.chat.id, call.message.message_id, text, keyboard)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "checks")
def checks_handler(call):
    clear_purchase_menu(call.message.chat.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
    send_section(call.message.chat.id, call.message.message_id, checks_text(call.from_user.id), keyboard)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_") and call.data[4:].isdigit())
def buy_fixed_handler(call):
    amount = int(call.data[4:])
    if amount < MIN_STARS or amount > MAX_STARS:
        bot.answer_callback_query(call.id, "Некорректное количество", show_alert=True)
        return
    bot.answer_callback_query(call.id, "Оплата пока не подключена", show_alert=True)
    bot.send_message(call.message.chat.id, f"⭐ {amount:,} звёзд\n💰 К оплате: {format_price(amount)} ₽\n\nОплата временно отключена — подключаем рублёвый платёжный сервис.")


@bot.callback_query_handler(func=lambda call: call.data == "buy_custom")
def buy_custom_handler(call):
    pending_custom_amount[call.from_user.id] = call.message.message_id
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"Введите количество звёзд от {MIN_STARS} до {MAX_STARS} одним числом.")


@bot.message_handler(func=lambda message: message.from_user.id in pending_custom_amount)
def custom_amount_handler(message):
    pending_custom_amount.pop(message.from_user.id, None)
    try:
        amount = int(message.text.strip())
        if amount < MIN_STARS or amount > MAX_STARS:
            raise ValueError(f"Количество должно быть от {MIN_STARS:,} до {MAX_STARS:,} звезд")
        bot.send_message(message.chat.id, f"⭐ {amount:,} звёзд\n💰 К оплате: {format_price(amount)} ₽\n\nОплата временно отключена — подключаем рублёвый платёжный сервис.")
    except Exception as exc:
        bot.send_message(message.chat.id, f"❌ {exc}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("status_"))
def status_handler(call):
    order = find_order(call.data[7:])
    if not order:
        bot.answer_callback_query(call.id, "Заказ не найден", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"🧾 Заказ #{order['order_id']}\n⭐ {order['amount']} Stars\n📋 Статус: {order.get('status', 'unknown')}")


try:
    from channel_sync import register_channel_handlers
    register_channel_handlers(bot)
except Exception as exc:
    print(f"[reviews] channel sync is unavailable: {exc}")
