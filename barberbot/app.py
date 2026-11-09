"""Сборка и запуск Telegram-бота."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent, Message

from barberbot.config import Settings
from barberbot.handlers import build_main_router

logger = logging.getLogger(__name__)

ERROR_TEXT = "Произошла ошибка. Пожалуйста, попробуйте позже."


async def on_startup(bot: Bot) -> None:
    logger.info("Запуск long polling (bot id=%s)", bot.id)


async def on_shutdown(bot: Bot) -> None:
    logger.info("BarberBot остановлен")


async def on_error(event: ErrorEvent) -> bool:
    """Глобальный обработчик ошибок: детали в лог, пользователю — общий текст."""
    logger.error(
        "Необработанная ошибка при обработке обновления", exc_info=event.exception
    )
    update = event.update
    try:
        if isinstance(update.message, Message):
            await update.message.answer(ERROR_TEXT)
        elif update.callback_query is not None:
            await update.callback_query.answer(ERROR_TEXT, show_alert=True)
    except TelegramAPIError:
        logger.warning("Не удалось отправить пользователю сообщение об ошибке")
    return True


def build_dispatcher() -> Dispatcher:
    """Создать dispatcher с роутерами, событиями запуска и обработчиком ошибок."""
    dispatcher = Dispatcher()
    dispatcher.include_router(build_main_router())
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    dispatcher.errors.register(on_error)
    return dispatcher


async def run_bot(settings: Settings) -> None:
    """Запустить long polling до остановки (Ctrl+C) и закрыть сессию."""
    bot = Bot(token=settings.bot_token.get_secret_value())
    dispatcher = build_dispatcher()
    logger.info("Подключение к Telegram API и запуск polling")
    try:
        await dispatcher.start_polling(bot, close_bot_session=False)
    finally:
        await bot.session.close()
        logger.info("Соединение с Telegram закрыто")
