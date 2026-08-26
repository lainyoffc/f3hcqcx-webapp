import telebot
from telebot import types
from datetime import datetime
from dotenv import load_dotenv
import time
import json
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REVIEWS_CHANNEL = os.getenv("REVIEWS_CHANNEL", "OtziviF3hcqcx1")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "F3hcqcx")
REVIEWS_WEBAPP_URL = os.getenv("REVIEWS_WEBAPP_URL", "https://lainyoffc.github.io/f3hcqcx-webapp/reviews.html")
STAR_PRICE = 1.53  # Цена одной Telegram Star в USD.

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Добавь BOT_TOKEN в переменные окружения Render")

bot = telebot.TeleBot(BOT_TOKEN)

# Новые посты из канала @OtziviF3hcqcx1 автоматически попадают в PostgreSQL.
try:
    from channel_sync import register_channel_handlers
    register_channel_handlers(bot)
except Exception as exc:
    print(f"[reviews] channel sync is unavailable: {exc}")

ORDERS_FILE = "orders.json"
reviews_cache = []
orders_data = {"orders": [], "users": {}}


def load_orders():
    global orders_data
    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            orders_data = json.load(f)


def save_orders():
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders_data, f, ensure_ascii=False, indent=2)


load_orders()


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
    """Совместимость со старым кодом: список для сообщений бота берётся из JSON."""
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
    username = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    text = f"⭐ *Покупка звёзд*\n\n👤 Получатель: {username}\n💵 *Цена 1 звезды:* ${STAR_PRICE:.2f} USD\n\n— Минимум: 50 звёзд\n— Максимум (за один заказ): 100 000 звёзд\n\n🔎 Выберите количество звёзд для покупки:"
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
    if reviews_cache:
        avg = sum(r.get("rating", 0) for r in reviews_cache) / len(reviews_cache)
    else:
        avg = 0
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_handler(call):
    value = call.data.replace("buy_", "")
    if value == "custom":
        bot.answer_callback_query(call.id, "Введите количество звёзд после нажатия кнопки", show_alert=True)
        return
    try:
        amount = int(value)
    except ValueError:
        bot.answer_callback_query(call.id, "Некорректное количество", show_alert=True)
        return
    if amount < 50 or amount > 100000:
        bot.answer_callback_query(call.id, "Допустимо от 50 до 100 000", show_alert=True)
        return
    user_id = call.from_user.id
    username = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    order_id = f"{user_id}_{int(time.time())}"
    total_price = amount * STAR_PRICE
    order = {"order_id": order_id, "user_id": user_id, "username": username, "amount": amount, "unit_price": STAR_PRICE, "price_usd": round(total_price, 2), "status": "pending", "created_at": datetime.now().isoformat()}
    orders_data["orders"].append(order)
    orders_data["users"].setdefault(str(user_id), {}).setdefault("orders", []).append(order_id)
    save_orders()
    text = f"⭐ *Заказ #{order_id}*\n\n👤 *Покупатель:* {username}\n⭐ *Количество:* {amount} звёзд\n💵 *Цена 1 звезды:* ${STAR_PRICE:.2f} USD\n💰 *Итого:* ${total_price:,.2f} USD\n\n📞 *Для оплаты:* @{SUPPORT_USERNAME}"
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="💳 Перейти к оплате", url=f"https://t.me/{SUPPORT_USERNAME}?start=order_{order_id}"))
    keyboard.add(types.InlineKeyboardButton(text="📋 Статус", callback_data=f"status_{order_id}"))
    bot.send_message(call.message.chat.id, text, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(call.id)


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
    status_emoji = {"pending": "⏳", "paid": "💰", "processing": "⚙️", "completed": "✅", "cancelled": "❌"}
    status_text = {"pending": "Ожидает оплаты", "paid": "Оплачен", "processing": "В обработке", "completed": "Выполнен", "cancelled": "Отменён"}
    text = f"📋 *Статус заказа #{order_id}*\n\n{status_emoji.get(order['status'], '❓')} *Статус:* {status_text.get(order['status'], 'Неизвестно')}\n⭐ *Количество:* {order['amount']} звёзд\n💵 *Цена 1 звезды:* ${float(order.get('unit_price', STAR_PRICE)):.2f} USD\n💰 *Итого:* ${float(order.get('price_usd', order.get('amount', 0) * STAR_PRICE)):,.2f} USD\n📅 *Создан:* {order['created_at']}\n"
    if order["status"] == "completed":
        text += "\n✅ *Звёзды успешно выданы!*\n"
    keyboard = types.InlineKeyboardMarkup()
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
