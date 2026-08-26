from telebot import types


def register_support_handlers(bot, bot_module):
    @bot.callback_query_handler(func=lambda call: call.data == "support")
    def support_handler(call):
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/F3hcqcx"))
        keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
        text = (
            "❓ *Поддержка F3hcqcx Stars*\n\n"
            "По вопросам оплаты, заказа, выдачи Stars или отзывов обращайтесь к администратору.\n\n"
            "👤 Поддержка: @F3hcqcx\n"
            "🕐 Ответим как можно скорее."
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=keyboard, parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "info")
    def info_handler(call):
        text = (
            "ℹ️ *О F3hcqcx Stars*\n\n"
            "🌟 Магазин Telegram Stars.\n\n"
            "💰 Цена рассчитывается автоматически.\n"
            "⚡ Заказы обрабатываются через Telegram-бота.\n"
            "🧾 После оплаты заказ можно проверить в разделе «Чеки».\n"
            "💬 По вопросам обращайтесь в поддержку: @F3hcqcx\n\n"
            "⚠️ Перед оплатой внимательно проверяйте количество Stars и свой @username."
        )
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=keyboard, parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "checks")
    def checks_handler(call):
        user_id = str(call.from_user.id)
        orders = [o for o in bot_module.orders_data.get("orders", []) if str(o.get("user_id")) == user_id]
        orders.sort(key=lambda o: o.get("created_at", ""), reverse=True)
        keyboard = types.InlineKeyboardMarkup()

        if not orders:
            text = "🧾 *Чеки*\n\nУ вас пока нет заказов."
        else:
            lines = ["🧾 *Ваши заказы и чеки*", ""]
            status_map = {
                "pending_payment": "💳 Ожидает оплаты",
                "paid": "✅ Оплачен",
                "processing": "⚙️ Выдача Stars",
                "completed": "✅ Выполнен",
                "cancelled": "❌ Отменён",
            }
            for order in orders[:10]:
                order_id = order.get("order_id", "—")
                amount = order.get("amount", 0)
                status = status_map.get(order.get("status"), order.get("status", "Неизвестно"))
                currency = order.get("paid_currency") or order.get("payment_currency", "XTR")
                paid_amount = order.get("paid_amount_xtr") or order.get("payment_amount_xtr", amount)
                lines.append(f"📌 *#{order_id}* — {amount} ⭐")
                lines.append(f"💳 {status}")
                lines.append(f"💰 Оплата: {paid_amount} {currency}")
                lines.append("")
                keyboard.add(types.InlineKeyboardButton(text=f"📋 #{order_id}", callback_data=f"status_{order_id}"))
            text = "\n".join(lines)

        keyboard.add(types.InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main"))
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=keyboard, parse_mode="Markdown")
        bot.answer_callback_query(call.id)
