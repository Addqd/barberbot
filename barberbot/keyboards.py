"""Клавиатуры и callback-данные главного меню."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_BOOK = "menu:book"
CALLBACK_SERVICES = "menu:services"
CALLBACK_MY_BOOKINGS = "menu:my_bookings"

MENU_CALLBACKS = frozenset({CALLBACK_BOOK, CALLBACK_SERVICES, CALLBACK_MY_BOOKINGS})


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню: три раздела, доступные из ``/start``."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✂️ Записаться", callback_data=CALLBACK_BOOK)],
            [
                InlineKeyboardButton(
                    text="💈 Услуги и цены", callback_data=CALLBACK_SERVICES
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Мои записи", callback_data=CALLBACK_MY_BOOKINGS
                )
            ],
        ]
    )
