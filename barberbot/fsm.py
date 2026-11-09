"""Состояния FSM-сценария записи и безопасная работа с его данными.

Используется штатное хранилище aiogram (:class:`MemoryStorage`). Состояние
может потеряться при перезапуске процесса, поэтому обработчики не полагаются
на его наличие: при отсутствии или некорректности данных сценарий начинается
заново.

В данных FSM хранятся только примитивы: ``int``, строка даты ``ГГГГ-ММ-ДД`` и
строка ISO datetime с часовым поясом. Значения всегда перепроверяются, потому
что FSM-данные могли остаться от прежней версии сценария.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from aiogram.fsm.state import State, StatesGroup

#: Ключи данных сценария.
SERVICE_ID = "service_id"
BARBER_ID = "barber_id"
DAY = "day"
START_AT = "start_at"
DATES_PAGE = "dates_page"


class BookingFlow(StatesGroup):
    """Последовательность записи: услуга → мастер → дата → время → подтверждение."""

    service = State()
    barber = State()
    date = State()
    time = State()
    confirm = State()


def read_int(data: Mapping[str, Any], key: str) -> int | None:
    """Целое значение из данных FSM; ``bool`` и строки не принимаются."""
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def read_page(data: Mapping[str, Any]) -> int:
    """Номер страницы дат; отрицательные значения приводятся к нулю."""
    page = read_int(data, DATES_PAGE)
    return 0 if page is None or page < 0 else page


def read_day(data: Mapping[str, Any]) -> date | None:
    """Дата из строки ISO; некорректная строка даёт ``None``."""
    value = data.get(DAY)
    if not isinstance(value, str) or len(value) > 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def read_start(data: Mapping[str, Any]) -> datetime | None:
    """Время начала из строки ISO; принимается только timezone-aware значение."""
    value = data.get(START_AT)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def write_day(day: date) -> str:
    return day.isoformat()


def write_start(start: datetime) -> str:
    return start.isoformat()


__all__ = [
    "BARBER_ID",
    "DATES_PAGE",
    "DAY",
    "SERVICE_ID",
    "START_AT",
    "BookingFlow",
    "read_day",
    "read_int",
    "read_page",
    "read_start",
    "write_day",
    "write_start",
]
