"""Точка входа: ``python -m barberbot``."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)

from barberbot.app import run_bot
from barberbot.config import ConfigurationError, load_settings
from barberbot.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    try:
        settings = load_settings()
    except ConfigurationError as error:
        logger.error("Не удалось запустить бота: %s", error)
        return 1

    try:
        # Psycopg async requires SelectorEventLoop on Windows 10.
        asyncio.run(
            run_bot(settings),
            loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None,
        )
    except KeyboardInterrupt:
        logger.info("Получен Ctrl+C, бот останавливается")
    except TelegramNetworkError as error:
        logger.error("Не удалось подключиться к Telegram API: %s", error)
        return 1
    except TelegramUnauthorizedError:
        logger.error("Telegram отклонил BOT_TOKEN, проверьте значение в .env")
        return 1
    except TelegramAPIError as error:
        logger.error("Ошибка Telegram API: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
