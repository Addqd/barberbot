"""Настройка логирования приложения."""

from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Включить логирование в stderr.

    Обработчик aiogram ``aiogram.event`` пишет по строке на каждое обновление,
    поэтому его уровень поднят до WARNING.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt="%H:%M:%S")
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
