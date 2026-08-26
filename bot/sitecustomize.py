"""Runtime hook for the Telegram bot.

Injects the F3hcqcx Stars banner into the Buy Stars callback. Render stores the
banner bytes in BUY_STARS_BANNER_B64 so the binary image does not need to be
committed to GitHub.
"""

import base64
import os
import sys
from pathlib import Path

try:
    import telebot
except Exception:
    telebot = None


if telebot is not None:
    _original_register_callback = telebot.TeleBot.register_callback_query_handler

    def _patched_register_callback_query_handler(self, callback, func, pass_bot=False, **kwargs):
        result = _original_register_callback(self, callback, func, pass_bot=pass_bot, **kwargs)

        if getattr(callback, "__name__", "") == "buy_stars_handler":
            try:
                module = sys.modules.get(callback.__module__)
                if module is None:
                    return result

                banner_path = Path(os.getenv("BUY_STARS_BANNER_PATH", "/tmp/f3hcqcx_buy_stars_banner.jpg"))
                if not banner_path.exists():
                    encoded = os.getenv("BUY_STARS_BANNER_B64", "")
                    if encoded:
                        try:
                            banner_path.write_bytes(base64.b64decode(encoded))
                        except Exception as exc:
                            print(f"[banner] cannot decode banner: {exc}")

                def banner_buy_stars_handler(call):
                    if call.data != "buy_stars":
                        return
                    try:
                        text = (
                            "⭐ *Покупка звёзд*\n\n"
                            f"💰 *Цена за 1 ⭐:* {module.PRICE_PER_STAR_RUB:.2f} {module.CURRENCY}\n\n"
                            f"— Минимум: {module.MIN_STARS:,} звезд\n"
                            f"— Максимум: {module.MAX_STARS:,} звезд\n\n"
                            "🔎 Выберите количество звёзд для покупки:"
                        )
                        keyboard = module.get_stars_keyboard()
                        try:
                            self.delete_message(call.message.chat.id, call.message.message_id)
                        except Exception:
                            pass

                        if banner_path.exists():
                            with banner_path.open("rb") as photo:
                                self.send_photo(
                                    call.message.chat.id,
                                    photo,
                                    caption=text,
                                    reply_markup=keyboard,
                                    parse_mode="Markdown",
                                )
                        else:
                            callback(call)
                        self.answer_callback_query(call.id)
                    except Exception as exc:
                        print(f"[banner] buy stars banner failed: {exc}")
                        try:
                            callback(call)
                        except Exception:
                            pass

                _original_register_callback(
                    self,
                    banner_buy_stars_handler,
                    lambda call: call.data == "buy_stars",
                )
                self.callback_query_handlers.insert(0, self.callback_query_handlers.pop())
            except Exception as exc:
                print(f"[banner] hook installation failed: {exc}")

        return result

    telebot.TeleBot.register_callback_query_handler = _patched_register_callback_query_handler
