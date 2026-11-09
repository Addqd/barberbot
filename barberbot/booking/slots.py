"""Чистые правила доступности времени записи.

Модуль не обращается к базе данных: рабочие часы, отсутствия мастера и уже
занятые интервалы передаются снаружи. Это позволяет проверять правила
простыми unit-тестами.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")

#: Шаг начала записи.
SLOT_STEP = timedelta(minutes=30)

#: Отмена разрешена не позднее чем за 2 часа до начала.
CANCELLATION_DEADLINE = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class Interval:
    """Полуинтервал ``[start, end)``: соседние записи не пересекаются."""

    start: datetime
    end: datetime

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end


class SlotIssue(StrEnum):
    """Причина, по которой время начала записи недопустимо."""

    PAST = "past"
    OUTSIDE_WORKING_HOURS = "outside_working_hours"
    OFF_GRID = "off_grid"
    DOES_NOT_FIT = "does_not_fit"


def day_window(
    day: date,
    work_start: time,
    work_end: time,
    *,
    tz: ZoneInfo = MOSCOW,
) -> Interval:
    """Рабочий интервал конкретного дня в часовом поясе барбершопа."""
    return Interval(
        start=datetime.combine(day, work_start, tzinfo=tz),
        end=datetime.combine(day, work_end, tzinfo=tz),
    )


def _step_minutes(step: timedelta) -> int:
    minutes = int(step.total_seconds() // 60)
    if minutes <= 0 or step != timedelta(minutes=minutes):
        raise ValueError("Шаг слотов должен быть целым числом минут")
    return minutes


def first_candidate(window_start: datetime, *, step: timedelta = SLOT_STEP) -> datetime:
    """Первое время начала на сетке шага, не раньше открытия."""
    step_minutes = _step_minutes(step)
    aligned = window_start.replace(second=0, microsecond=0)
    minute_of_day = aligned.hour * 60 + aligned.minute
    aligned += timedelta(
        minutes=(-(-minute_of_day // step_minutes)) * step_minutes - minute_of_day
    )
    if aligned < window_start:
        aligned += step
    return aligned


def start_issue(
    *,
    starts_at: datetime,
    window: Interval,
    duration: timedelta,
    now: datetime,
    step: timedelta = SLOT_STEP,
    tz: ZoneInfo = MOSCOW,
) -> SlotIssue | None:
    """Проверить структурную допустимость начала, не учитывая занятость."""
    local = starts_at.astimezone(tz)
    if starts_at <= now:
        return SlotIssue.PAST
    if local < window.start or local >= window.end:
        return SlotIssue.OUTSIDE_WORKING_HOURS
    if local.second or local.microsecond or local.minute % _step_minutes(step):
        return SlotIssue.OFF_GRID
    if local + duration > window.end:
        return SlotIssue.DOES_NOT_FIT
    return None


def generate_slots(
    *,
    window: Interval,
    duration: timedelta,
    now: datetime,
    busy: Iterable[Interval] = (),
    step: timedelta = SLOT_STEP,
) -> list[datetime]:
    """Свободные времена начала с шагом ``step`` в пределах рабочего интервала.

    Учитываются: полностью помещающаяся услуга, будущее время и занятые
    интервалы (полуинтервалы ``[start, end)``).
    """
    busy_intervals = tuple(busy)
    candidate = first_candidate(window.start, step=step)
    slots: list[datetime] = []
    while candidate + duration <= window.end:
        if candidate > now and not any(
            interval.overlaps(candidate, candidate + duration)
            for interval in busy_intervals
        ):
            slots.append(candidate)
        candidate += step
    return slots


__all__ = [
    "CANCELLATION_DEADLINE",
    "MOSCOW",
    "SLOT_STEP",
    "Interval",
    "SlotIssue",
    "day_window",
    "first_candidate",
    "generate_slots",
    "start_issue",
]
