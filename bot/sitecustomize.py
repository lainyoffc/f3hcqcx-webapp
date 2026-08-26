"""Safe banner hook for the Buy Stars button."""

import base64
import os
import sys
from pathlib import Path

try:
    import telebot
except Exception:
    telebot = None


if telebot is not None:
    _original_register = telebot.TeleBot.register_callback_query_handler

    def _patched_register(self, callback, func, pass_bot=False, **kwargs):
        result = _original_register(self, callback, func, pass_bot=pass_bot, **kwargs)
        if getattr(callback, "__name__", "") != "buy_stars_handler":
            return result

        try:
            module = sys.modules.get(callback.__module__)
            if module is None:
                return result

            path = Path(os.getenv("BUY_STARS_BANNER_PATH", "/tmp/f3hcqcx_buy_stars_banner.jpg"))
            if not path.exists():
                encoded = os.getenv("BUY_STARS_BANNER_B64", "")
                if encoded:
                    try:
                        path.write_bytes(base64.b64decode(encoded))
                    except Exception as exc:
                        print(f"[banner] decode failed: {exc}")

            def banner_handler(call):
                if call.data != "buy_stars":
                    return
                chat_id = call.message.chat.id
                old_message_id = call.message.message_id
                text = (
                    "⭐ *Покупка звёзд*\n\n"
                    f"💰 *Цена за 1 ⭐:* {module.PRICE_PER_STAR_RUB:.2f} {module.CURRENCY}\n\n"
                    f"— Минимум: {module.MIN_STARS:,} звезд\n"
                    f"— Максимум: {module.MAX_STARS:,} звезд\n\n"
                    "🔎 Выберите количество звёзд для покупки:"
                )
                keyboard = module.get_stars_keyboard()

                try:
                    sent = None
                    if path.exists():
                        with path.open("rb") as photo:
                            sent = self.send_photo(
                                chat_id,
                                photo,
                                caption=text,
                                reply_markup=keyboard,
                                parse_mode="Markdown",
                            )
                    if sent is None:
                        sent = self.send_message(
                            chat_id,
                            text,
                            reply_markup=keyboard,
                            parse_mode="Markdown",
                        )
                    try:
                        self.delete_message(chat_id, old_message_id)
                    except Exception:
                        pass
                    self.answer_callback_query(call.id)
                except Exception as exc:
                    print(f"[banner] send failed: {exc}")
                    try:
                        callback(call)
                    except Exception as fallback_exc:
                        print(f"[banner] fallback failed: {fallback_exc}")

            _original_register(self, banner_handler, lambda call: call.data == "buy_stars")
            self.callback_query_handlers.insert(0, self.callback_query_handlers.pop())
        except Exception as exc:
            print(f"[banner] hook installation failed: {exc}")

        return result

    telebot.TeleBot.register_callback_query_handler = _patched_register