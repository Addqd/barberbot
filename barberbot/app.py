"""Сборка и запуск Telegram-бота."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import ErrorEvent, Message

from barberbot.booking.completion import CompletionScheduler
from barberbot.booking.service import BookingService
from barberbot.config import Settings
from barberbot.db.engine import Database, create_database
from barberbot.handlers import build_main_router
from barberbot.middleware import PrivateChatOnlyMiddleware

logger = logging.getLogger(__name__)

ERROR_TEXT = "Произошла ошибка. Пожалуйста, попробуйте позже."


async def on_startup(bot: Bot, completion_scheduler: CompletionScheduler) -> None:
    # Обновление статусов при запуске: записи, завершившиеся пока бот был
    # остановлен, получают ``completed`` до начала обработки обновлений.
    await completion_scheduler.start()
    logger.info("Запуск long polling (bot id=%s)", bot.id)


async def on_shutdown(bot: Bot, completion_scheduler: CompletionScheduler) -> None:
    completion_scheduler.shutdown()
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


def build_dispatcher(booking_service: BookingService) -> Dispatcher:
    """Создать dispatcher с роутерами, DI сервиса и обработчиком ошибок.

    ``booking_service`` попадает в ``workflow_data`` aiogram и передаётся
    обработчикам по имени аргумента. ``SimpleEventIsolation`` сериализует
    обновления одного чата: повторное нажатие «Подтвердить» не выполняется
    параллельно с первым. ``CompletionScheduler`` тоже живёт в
    ``workflow_data``: его запускает ``on_startup``, останавливает
    ``on_shutdown``, который aiogram вызывает и при ошибке polling.

    ``PrivateChatOnlyMiddleware`` регистрируется первым уровнем обработки
    updates: клиентские функции доступны только в личных чатах, проверка
    выполняется до фильтров, обработчиков и обращения к сервису.
    """
    dispatcher = Dispatcher(
        booking_service=booking_service,
        completion_scheduler=CompletionScheduler(booking_service),
        events_isolation=SimpleEventIsolation(),
    )
    dispatcher.update.outer_middleware(PrivateChatOnlyMiddleware())
    dispatcher.include_router(build_main_router())
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    dispatcher.errors.register(on_error)
    return dispatcher


async def run_bot(settings: Settings) -> None:
    """Запустить long polling до остановки (Ctrl+C).

    Один ``AsyncEngine`` создаётся на процесс. Пул соединений закрывается в
    ``finally`` — и при штатной остановке, и при ошибке запуска polling.
    Миграции при запуске не применяются.
    """
    bot = Bot(token=settings.bot_token.get_secret_value())
    database: Database | None = None
    try:
        database = create_database()
        dispatcher = build_dispatcher(BookingService(database.sessions))
        logger.info("Подключение к Telegram API и запуск polling")
        await dispatcher.start_polling(bot, close_bot_session=False)
    finally:
        try:
            await bot.session.close()
            logger.info("Соединение с Telegram закрыто")
        finally:
            if database is not None:
                await database.dispose()
                logger.info("Пул соединений с базой данных закрыт")
