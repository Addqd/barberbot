"""Общие обработчики: главное меню, справка, возврат в меню."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from barberbot.callbacks import FlowCancelCB, NavMainCB
from barberbot.handlers.render import render
from barberbot.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


def _is_admin(event: Message | CallbackQuery, admin_ids: frozenset[int]) -> bool:
    """Показывать ли кнопку панели: только по ``from_user.id`` от Telegram."""
    user = event.from_user
    return user is not None and user.id in admin_ids


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


async def handle_start(
    message: Message,
    state: FSMContext,
    admin_ids: frozenset[int] = frozenset(),
) -> None:
    """Приветствие и главное меню; незавершённый сценарий сбрасывается."""
    user_id = message.from_user.id if message.from_user else "?"
    logger.info("Команда /start от пользователя id=%s", user_id)
    await state.clear()
    await message.answer(
        START_TEXT, reply_markup=main_menu_keyboard(admin=_is_admin(message, admin_ids))
    )


async def handle_help(message: Message) -> None:
    """Краткая справка по боту."""
    await message.answer(HELP_TEXT)


async def show_main_menu(
    callback: CallbackQuery,
    state: FSMContext,
    admin_ids: frozenset[int] = frozenset(),
) -> None:
    """Вернуть пользователя в главное меню, очистив данные сценария."""
    await callback.answer()
    await state.clear()
    await render(
        callback,
        START_TEXT,
        main_menu_keyboard(admin=_is_admin(callback, admin_ids)),
    )


def build_router() -> Router:
    """Создать роутер с командами и возвратом в главное меню."""
    router = Router(name="common")
    router.message.register(handle_start, Command("start"))
    router.message.register(handle_help, Command("help"))
    router.callback_query.register(show_main_menu, NavMainCB.filter())
    router.callback_query.register(show_main_menu, FlowCancelCB.filter())
    return router


__all__ = ["HELP_TEXT", "START_TEXT", "build_router", "handle_help", "handle_start"]
