"""Unit-тесты форматирования даты, времени, цены и правил показа отмены."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from barberbot import ui
from barberbot.booking.slots import MOSCOW
from barberbot.db.models import Booking, BookingStatus

from .fakes import make_barber, make_service


def make_booking(
    *,
    starts_at: datetime,
    status: BookingStatus = BookingStatus.CONFIRMED,
    booking_id: int = 7,
) -> Booking:
    service = make_service(name="Обычная стрижка", price=500, duration=60)
    barber = make_barber(name="Елена")
    return Booking(
        id=booking_id,
        user_id=11,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=60),
        price_rub_at_booking=500,
        duration_minutes_at_booking=60,
        status=status,
        barber=barber,
        service=service,
    )


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (1, "1 минута"),
        (2, "2 минуты"),
        (4, "4 минуты"),
        (5, "5 минут"),
        (11, "11 минут"),
        (14, "14 минут"),
        (21, "21 минута"),
        (22, "22 минуты"),
        (60, "60 минут"),
        (111, "111 минут"),
    ],
)
def test_format_duration(minutes: int, expected: str) -> None:
    assert ui.format_duration(minutes) == expected


def test_moscow_date_and_time_formatting() -> None:
    moment = datetime(2030, 1, 7, 10, 0, tzinfo=UTC)
    local = ui.as_moscow(moment)

    assert ui.format_date(local.date()) == "07.01.2030"
    assert ui.format_time(moment) == "13:00"
    assert ui.format_datetime(moment) == "07.01.2030 13:00"


def test_day_short_and_price() -> None:
    assert ui.format_day_short(datetime(2030, 1, 7).date()) == "пн, 07.01"
    assert ui.format_price(800) == "800 ₽"


def test_booking_lines_use_snapshot_fields() -> None:
    booking = make_booking(
        starts_at=datetime(2030, 1, 7, 14, 0, tzinfo=MOSCOW),
        status=BookingStatus.CANCELLED,
    )

    lines = ui.booking_lines(booking)

    assert "💈 Услуга: Обычная стрижка" in lines
    assert "👤 Мастер: Елена" in lines
    assert "📅 Дата: 07.01.2030" in lines
    assert "🕐 Время: 14:00" in lines
    assert "⏱ Длительность: 60 минут" in lines
    assert "💰 Стоимость: 500 ₽" in lines
    assert "📌 Статус: ❌ Отменена" in lines


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # Сервисное правило: отмена не позднее чем за 2 часа.
        (datetime(2030, 1, 7, 7, 0, tzinfo=MOSCOW), True),
        (datetime(2030, 1, 7, 9, 0, tzinfo=MOSCOW), True),
        (datetime(2030, 1, 7, 9, 30, tzinfo=MOSCOW), False),
        (datetime(2030, 1, 7, 11, 0, tzinfo=MOSCOW), False),
    ],
    ids=["three-hours", "exactly-two-hours", "one-and-half-hours", "after-start"],
)
def test_is_cancellable_respects_two_hour_deadline(
    now: datetime, expected: bool
) -> None:
    booking = make_booking(starts_at=datetime(2030, 1, 7, 11, 0, tzinfo=MOSCOW))

    assert ui.is_cancellable(booking, now=now) is expected


@pytest.mark.parametrize(
    "status",
    [BookingStatus.CANCELLED, BookingStatus.COMPLETED],
    ids=["cancelled", "completed"],
)
def test_only_confirmed_bookings_are_cancellable(status: BookingStatus) -> None:
    booking = make_booking(
        starts_at=datetime(2030, 1, 7, 18, 0, tzinfo=MOSCOW), status=status
    )

    assert (
        ui.is_cancellable(booking, now=datetime(2030, 1, 7, 8, 0, tzinfo=MOSCOW))
        is False
    )


def test_sort_for_display_orders_upcoming_then_past() -> None:
    now = datetime(2030, 1, 7, 12, 0, tzinfo=MOSCOW)
    past_early = make_booking(
        starts_at=datetime(2030, 1, 6, 10, 0, tzinfo=MOSCOW), booking_id=1
    )
    past_late = make_booking(
        starts_at=datetime(2030, 1, 7, 9, 0, tzinfo=MOSCOW), booking_id=2
    )
    upcoming_late = make_booking(
        starts_at=datetime(2030, 1, 8, 15, 0, tzinfo=MOSCOW), booking_id=3
    )
    upcoming_soon = make_booking(
        starts_at=datetime(2030, 1, 7, 14, 0, tzinfo=MOSCOW), booking_id=4
    )

    ordered = ui.sort_for_display(
        [past_early, upcoming_late, past_late, upcoming_soon], now=now
    )

    assert [row.id for row in ordered] == [4, 3, 2, 1]
