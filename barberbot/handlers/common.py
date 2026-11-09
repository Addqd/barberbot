"""Общие обработчики: главное меню и справка."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from barberbot.keyboards import MENU_CALLBACKS, main_menu_keyboard

logger = logging.getLogger(__name__)

START_TEXT = (
    "💈 Добро пожаловать в BarberBot!\n"
    "\n"
    "Здесь вы сможете выбрать услугу, мастера и удобное время для записи."
)

HELP_TEXT = (
    "💈 BarberBot — запись в барбершоп.\n"
    "\n"
    "Бот поможет выбрать услугу, мастера и удобное время для записи.\n"
    "\n"
    "Команды:\n"
    "/start — главное меню\n"
    "/help — эта справка"
)

IN_DEVELOPMENT_TEXT = "Этот раздел пока в разработке."


async def handle_start(message: Message) -> None:
    """Приветствие и главное меню."""
    user_id = message.from_user.id if message.from_user else "?"
    logger.info("Команда /start от пользователя id=%s", user_id)
    await message.answer(START_TEXT, reply_markup=main_menu_keyboard())


async def handle_help(message: Message) -> None:
    """Краткая справка по боту."""
    await message.answer(HELP_TEXT)


async def handle_menu_callback(callback: CallbackQuery) -> None:
    """Ответ на кнопки главного меню.

    Callback всегда подтверждается, иначе у пользователя остаётся
    индикатор загрузки на кнопке.
    """
    logger.info("Нажата кнопка меню %r", callback.data)
    await callback.answer(IN_DEVELOPMENT_TEXT)
    if isinstance(callback.message, Message):
        await callback.message.answer(IN_DEVELOPMENT_TEXT)


def build_router() -> Router:
    """Создать роутер с обработчиками команд и кнопок."""
    router = Router(name="common")
    router.message.register(handle_start, Command("start"))
    router.message.register(handle_help, Command("help"))
    router.callback_query.register(handle_menu_callback, F.data.in_(MENU_CALLBACKS))
    return router
