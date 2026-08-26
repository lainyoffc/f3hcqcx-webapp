"""Bot UI compatibility patches: correct section artwork and compact Telegram images."""

from io import BytesIO
from pathlib import Path

import telebot
from PIL import Image

_original_register = telebot.TeleBot.register_callback_query_handler
_original_send_photo = telebot.TeleBot.send_photo


def _patched_register(self, callback, func, pass_bot=False, **kwargs):
    name = getattr(callback, "__name__", "")
    if name == "buy_fixed_handler":
        def disabled_fixed_handler(call):
            try:
                self.answer_callback_query(
                    call.id,
                    "Оплата временно отключена. Мы подключаем оплату в рублях.",
                    show_alert=True,
                )
            except Exception:
                pass

        disabled_fixed_handler.__name__ = "disabled_buy_fixed_handler"
        return _original_register(
            self,
            disabled_fixed_handler,
            lambda call: bool(getattr(call, "data", "").startswith("buy_") and getattr(call, "data", "")[4:].isdigit()),
            pass_bot=pass_bot,
            **kwargs,
        )

    if name == "buy_custom_handler":
        def disabled_custom_handler(call):
            try:
                self.answer_callback_query(
                    call.id,
                    "Оплата временно отключена. Мы подключаем оплату в рублях.",
                    show_alert=True,
                )
            except Exception:
                pass

        disabled_custom_handler.__name__ = "disabled_buy_custom_handler"
        return _original_register(
            self,
            disabled_custom_handler,
            lambda call: call.data == "buy_custom",
            pass_bot=pass_bot,
            **kwargs,
        )

    return _original_register(self, callback, func, pass_bot=pass_bot, **kwargs)


def _compact_section_photo(path):
    image = Image.open(path).convert("RGB")
    max_width = 340
    if image.width > max_width:
        height = round(image.height * max_width / image.width)
        image = image.resize((max_width, height), Image.Resampling.LANCZOS)
    buf = BytesIO()
    buf.name = Path(path).stem + ".jpg"
    image.save(buf, format="JPEG", quality=88, optimize=True, progressive=True)
    buf.seek(0)
    return buf


def _patched_send_photo(self, chat_id, photo, *args, **kwargs):
    source_name = str(getattr(photo, "name", ""))
    if source_name:
        assets = Path(__file__).resolve().parent / "assets"
        mapping = {
            "878d42de-cfa8-456a-9e4b-daacd88b6ffb-fotor-20260826161413.png": "878d42de-cfa8-456a-9e4b-daacd88b6ffb-fotor-20260826161311.png",
            "878d42de-cfa8-456a-9e4b-daacd88b6ffb-fotor-20260826161311.png": "878d42de-cfa8-456a-9e4b-daacd88b6ffb-fotor-20260826161413.png",
            "878d42de-cfa8-456a-9e4b-daacd88b6ffb(3).png": "878d42de-cfa8-456a-9e4b-daacd88b6ffb(1).png",
            "878d42de-cfa8-456a-9e4b-daacd88b6ffb(2).png": "878d42de-cfa8-456a-9e4b-daacd88b6ffb(2).png",
            "878d42de-cfa8-456a-9e4b-daacd88b6ffb(1).png": "878d42de-cfa8-456a-9e4b-daacd88b6ffb(3).png",
        }
        filename = Path(source_name).name
        target = mapping.get(filename)
        if target:
            target_path = assets / target
            if target_path.is_file():
                photo = _compact_section_photo(target_path)
                caption = kwargs.get("caption")
                if isinstance(caption, str) and caption.startswith("F3hcqcx\n"):
                    parts = caption.split("\n\n", 1)
                    if len(parts) == 2:
                        kwargs["caption"] = parts[1]
    return _original_send_photo(self, chat_id, photo, *args, **kwargs)


telebot.TeleBot.register_callback_query_handler = _patched_register
telebot.TeleBot.send_photo = _patched_send_photo
