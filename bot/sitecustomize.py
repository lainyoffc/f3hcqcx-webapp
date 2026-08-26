"""Temporarily disable purchase invoices until a RUB payment provider is connected."""

import telebot
from telebot import types

_original_register = telebot.TeleBot.register_callback_query_handler


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


telebot.TeleBot.register_callback_query_handler = _patched_register
