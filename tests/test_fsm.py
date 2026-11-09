"""Unit-тесты безопасного разбора данных FSM (недоверенное состояние)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from barberbot import fsm

MOSCOW = ZoneInfo("Europe/Moscow")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),
        (0, 0),
        (-3, -3),
        (True, None),
        ("5", None),
        (5.0, None),
        (None, None),
    ],
    ids=["int", "zero", "negative", "bool", "str", "float", "none"],
)
def test_read_int_accepts_only_real_integers(
    value: object, expected: int | None
) -> None:
    assert fsm.read_int({"key": value}, "key") == expected


def test_read_int_missing_key() -> None:
    assert fsm.read_int({}, "key") is None


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, 0),
        ({fsm.DATES_PAGE: 3}, 3),
        ({fsm.DATES_PAGE: -1}, 0),
        ({fsm.DATES_PAGE: "2"}, 0),
    ],
    ids=["missing", "valid", "negative", "wrong-type"],
)
def test_read_page(data: dict[str, object], expected: int) -> None:
    assert fsm.read_page(data) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2030-01-07", date(2030, 1, 7)),
        ("2030-13-45", None),
        ("", None),
        ("2030-01-07T00:00:00", None),
        (1_234_567, None),
        (None, None),
    ],
    ids=["valid", "invalid-date", "empty", "datetime", "int", "none"],
)
def test_read_day(value: object, expected: date | None) -> None:
    assert fsm.read_day({fsm.DAY: value}) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2030-01-07T10:00:00+03:00", datetime(2030, 1, 7, 10, 0, tzinfo=MOSCOW)),
        ("2030-01-07T10:00:00", None),
        ("not-a-datetime", None),
        (1_234_567, None),
        (None, None),
    ],
    ids=["aware", "naive", "invalid", "int", "none"],
)
def test_read_start(value: object, expected: datetime | None) -> None:
    assert fsm.read_start({fsm.START_AT: value}) == expected


def test_day_and_start_round_trip() -> None:
    day = date(2030, 2, 3)
    start = datetime(2030, 2, 3, 14, 30, tzinfo=MOSCOW)

    assert fsm.read_day({fsm.DAY: fsm.write_day(day)}) == day
    assert fsm.read_start({fsm.START_AT: fsm.write_start(start)}) == start
