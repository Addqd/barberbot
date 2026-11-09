"""Интеграционные тесты движка бронирования на реальной PostgreSQL."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest

from barberbot.booking.errors import (
    BarberUnavailable,
    BookingAlreadyCancelled,
    BookingNotCancellable,
    BookingNotFound,
    CancellationTooLate,
    InvalidBookingTime,
    NotBookingOwner,
    ServiceUnavailable,
    SlotUnavailable,
)
from barberbot.booking.service import (
    MESSAGE_DOES_NOT_FIT,
    MESSAGE_INVALID_TIME,
    MESSAGE_NOT_CANCELLABLE,
    MESSAGE_NOT_FOUND,
    MESSAGE_NOT_OWNER,
    MESSAGE_OFF_GRID,
    MESSAGE_OUTSIDE_HOURS,
    MESSAGE_PAST,
    MESSAGE_TOO_LATE,
    BookingService,
)
from barberbot.booking.slots import MOSCOW
from barberbot.db.models import Booking, BookingStatus, Service
from barberbot.db.repositories import UserRepository

MONDAY = date(2030, 1, 7)


def monday(hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, 7, hour, minute, tzinfo=MOSCOW)


def expected_slots(first_hour: int, last_start: datetime) -> list[datetime]:
    slots: list[datetime] = []
    current = monday(first_hour)
    while current <= last_start:
        slots.append(current)
        current += timedelta(minutes=30)
    return slots


@pytest.mark.asyncio
async def test_available_slots_follow_database_schedule(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service(duration=60)

    slots = await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    assert slots == expected_slots(9, monday(16))
    assert all(slot.tzinfo is not None for slot in slots)
    assert all(
        (right - left) == timedelta(minutes=30) for left, right in pairwise(slots)
    )


@pytest.mark.asyncio
async def test_available_dates_exclude_weekend(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    dates = await booking_service.available_dates(
        service_id=service.id, barber_id=barber.id, start_date=MONDAY, days=7
    )

    assert dates == [
        date(2030, 1, 7),
        date(2030, 1, 8),
        date(2030, 1, 9),
        date(2030, 1, 10),
        date(2030, 1, 11),
    ]
    assert date(2030, 1, 12) not in dates  # суббота
    assert date(2030, 1, 13) not in dates  # воскресенье


@pytest.mark.asyncio
async def test_past_date_has_no_slots(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    slots = await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=date(2029, 12, 31)
    )

    assert slots == []


@pytest.mark.asyncio
async def test_available_dates_are_empty_for_past_range(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    dates = await booking_service.available_dates(
        service_id=service.id,
        barber_id=barber.id,
        start_date=date(2029, 12, 31),
        days=3,
    )

    assert dates == []


@pytest.mark.asyncio
async def test_create_booking_rejects_past_date(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    with pytest.raises(InvalidBookingTime) as error_info:
        await booking_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=datetime(2029, 12, 31, 9, 0, tzinfo=MOSCOW),
        )

    assert str(error_info.value) == MESSAGE_PAST


@pytest.mark.asyncio
async def test_day_without_schedule_has_no_slots(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber(weekdays=[])
    service = await factory.service()

    slots = await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    assert slots == []


@pytest.mark.asyncio
async def test_available_slots_respect_time_off(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service(duration=60)
    await factory.time_off(
        barber_id=barber.id,
        starts_at=monday(12),
        ends_at=monday(14),
        reason="Отпуск",
    )

    slots = await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    assert monday(11, 0) in slots
    assert monday(11, 30) not in slots
    assert monday(12, 0) not in slots
    assert monday(13, 0) not in slots
    assert monday(13, 30) not in slots
    assert monday(14, 0) in slots


@pytest.mark.asyncio
async def test_available_slots_respect_existing_booking_and_adjacent_starts(
    booking_service: BookingService, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service(duration=60)
    await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(10),
        duration=60,
    )

    slots = await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    assert monday(9, 0) in slots  # заканчивается ровно к началу занятого времени
    assert monday(9, 30) not in slots
    assert monday(10, 0) not in slots
    assert monday(10, 30) not in slots
    assert monday(11, 0) in slots


@pytest.mark.asyncio
async def test_cancelled_booking_does_not_block_slot(
    booking_service: BookingService, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(10),
        status=BookingStatus.CANCELLED,
    )

    slots = await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    assert monday(10, 0) in slots


@pytest.mark.asyncio
async def test_completed_booking_still_blocks_slot(
    booking_service: BookingService, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(10),
        status=BookingStatus.COMPLETED,
    )

    slots = await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    assert monday(10, 0) not in slots


@pytest.mark.asyncio
async def test_past_times_are_not_offered(sessions: Any, factory: Any) -> None:
    barber = await factory.barber()
    service = await factory.service()
    service_with_later_clock = BookingService(sessions, clock=lambda: monday(12, 0))

    slots = await service_with_later_clock.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    assert slots[0] == monday(12, 30)
    assert monday(12, 0) not in slots
    assert all(slot > monday(12, 0) for slot in slots)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("duration", "last_start"),
    [(30, monday(16, 30)), (45, monday(16)), (60, monday(16))],
)
async def test_available_slots_respect_service_duration(
    booking_service: BookingService,
    factory: Any,
    duration: int,
    last_start: datetime,
) -> None:
    barber = await factory.barber()
    service = await factory.service(duration=duration)

    slots = await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    assert slots[-1] == last_start
    assert all(slot + timedelta(minutes=duration) <= monday(17) for slot in slots)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inactive_kind", "error_type"),
    [("service", ServiceUnavailable), ("barber", BarberUnavailable)],
)
async def test_inactive_or_missing_catalog_rows_are_rejected(
    booking_service: BookingService,
    factory: Any,
    inactive_kind: str,
    error_type: type[Exception],
) -> None:
    service = await factory.service(is_active=inactive_kind != "service")
    barber = await factory.barber(is_active=inactive_kind != "barber")

    with pytest.raises(error_type):
        await booking_service.available_slots(
            service_id=service.id, barber_id=barber.id, on_date=MONDAY
        )

    with pytest.raises(error_type):
        await booking_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=monday(9),
        )


@pytest.mark.asyncio
async def test_create_booking_saves_snapshot_and_user(
    sessions: Any, booking_service: BookingService, factory: Any
) -> None:
    telegram_id = factory.telegram_id()
    barber = await factory.barber()
    service = await factory.service(price=500, duration=60)

    booking = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(9),
        display_name="Клиент",
    )

    assert booking.status is BookingStatus.CONFIRMED
    assert booking.starts_at == monday(9)
    assert booking.ends_at == monday(10)
    assert booking.price_rub_at_booking == 500
    assert booking.duration_minutes_at_booking == 60
    assert booking.barber.name == barber.name
    assert booking.service.name == service.name

    async with sessions() as session:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
    assert user is not None
    assert user.display_name == "Клиент"

    # Изменение услуги после записи не меняет снимок условий.
    async with sessions() as session, session.begin():
        stored_service = await session.get(Service, service.id)
        assert stored_service is not None
        stored_service.price_rub = 800
        stored_service.duration_minutes = 30

    async with sessions() as session:
        reloaded = await session.get(Booking, booking.id)

    assert reloaded is not None
    assert reloaded.price_rub_at_booking == 500
    assert reloaded.duration_minutes_at_booking == 60


@pytest.mark.asyncio
async def test_second_booking_for_same_slot_is_rejected(
    booking_service: BookingService, factory: Any
) -> None:
    first_telegram_id = factory.telegram_id()
    second_telegram_id = factory.telegram_id()
    barber = await factory.barber()
    service = await factory.service()

    first = await booking_service.create_booking(
        telegram_id=first_telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(9),
    )
    with pytest.raises(SlotUnavailable):
        await booking_service.create_booking(
            telegram_id=second_telegram_id,
            barber_id=barber.id,
            service_id=service.id,
            starts_at=monday(9),
        )

    assert [
        row.id for row in await booking_service.list_user_bookings(first_telegram_id)
    ] == [first.id]
    assert await booking_service.list_user_bookings(second_telegram_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("starts_at", "message"),
    [
        (monday(7), MESSAGE_PAST),
        (monday(8, 30), MESSAGE_OUTSIDE_HOURS),
        (monday(9, 10), MESSAGE_OFF_GRID),
        (monday(16, 30), MESSAGE_DOES_NOT_FIT),
        (monday(17), MESSAGE_OUTSIDE_HOURS),
    ],
)
async def test_create_booking_rejects_invalid_start(
    booking_service: BookingService,
    factory: Any,
    starts_at: datetime,
    message: str,
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    with pytest.raises(InvalidBookingTime) as error_info:
        await booking_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=starts_at,
        )

    assert str(error_info.value) == message


@pytest.mark.asyncio
async def test_create_booking_rejects_weekend(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    with pytest.raises(InvalidBookingTime) as error_info:
        await booking_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=datetime(2030, 1, 12, 9, 0, tzinfo=MOSCOW),
        )

    assert str(error_info.value) == MESSAGE_OUTSIDE_HOURS


@pytest.mark.asyncio
async def test_create_booking_rejects_naive_datetime(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    with pytest.raises(InvalidBookingTime) as error_info:
        await booking_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=datetime(2030, 1, 7, 9, 0),
        )

    assert str(error_info.value) == MESSAGE_INVALID_TIME


@pytest.mark.asyncio
async def test_create_booking_rejects_time_off(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    await factory.time_off(
        barber_id=barber.id,
        starts_at=monday(9),
        ends_at=monday(12),
        reason="Отпуск",
    )

    with pytest.raises(SlotUnavailable):
        await booking_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=monday(10),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", ["service", "barber"])
async def test_create_booking_rejects_missing_rows(
    booking_service: BookingService, factory: Any, unknown: str
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    with pytest.raises(
        ServiceUnavailable if unknown == "service" else BarberUnavailable
    ):
        await booking_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=10**17 if unknown == "barber" else barber.id,
            service_id=10**17 if unknown == "service" else service.id,
            starts_at=monday(9),
        )


@pytest.mark.asyncio
async def test_cancel_booking_frees_slot(
    booking_service: BookingService, factory: Any
) -> None:
    telegram_id = factory.telegram_id()
    barber = await factory.barber()
    service = await factory.service()

    booking = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(12),
    )
    assert monday(12) not in await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )

    cancelled = await booking_service.cancel_booking(
        telegram_id=telegram_id, booking_id=booking.id
    )

    assert cancelled.status is BookingStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert monday(12) in await booking_service.available_slots(
        service_id=service.id, barber_id=barber.id, on_date=MONDAY
    )


@pytest.mark.asyncio
async def test_cancel_foreign_booking_is_forbidden(
    booking_service: BookingService, factory: Any
) -> None:
    owner_id = factory.telegram_id()
    stranger = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=owner_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(12),
    )

    with pytest.raises(NotBookingOwner) as error_info:
        await booking_service.cancel_booking(
            telegram_id=stranger.telegram_id, booking_id=booking.id
        )

    assert str(error_info.value) == MESSAGE_NOT_OWNER
    own_bookings = await booking_service.list_user_bookings(owner_id)
    assert [row.status for row in own_bookings] == [BookingStatus.CONFIRMED]


@pytest.mark.asyncio
async def test_cancel_unknown_booking_or_user(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    stranger = await factory.user()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(12),
    )

    with pytest.raises(BookingNotFound) as booking_error:
        await booking_service.cancel_booking(
            telegram_id=factory.telegram_id(), booking_id=booking.id
        )
    assert str(booking_error.value) == MESSAGE_NOT_FOUND

    with pytest.raises(BookingNotFound):
        await booking_service.cancel_booking(
            telegram_id=stranger.telegram_id, booking_id=10**17
        )


@pytest.mark.asyncio
async def test_cancel_exactly_two_hours_before_is_allowed(
    sessions: Any, factory: Any
) -> None:
    telegram_id = factory.telegram_id()
    barber = await factory.barber()
    service = await factory.service()
    at_deadline = BookingService(sessions, clock=lambda: monday(10))
    booking = await at_deadline.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(12),
    )

    cancelled = await at_deadline.cancel_booking(
        telegram_id=telegram_id, booking_id=booking.id
    )

    assert cancelled.status is BookingStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_inside_two_hour_window_is_rejected(
    sessions: Any, factory: Any
) -> None:
    telegram_id = factory.telegram_id()
    barber = await factory.barber()
    service = await factory.service()
    booking_service = BookingService(sessions, clock=lambda: monday(8))
    booking = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(12),
    )

    too_late_service = BookingService(
        sessions, clock=lambda: monday(10) + timedelta(microseconds=1)
    )
    with pytest.raises(CancellationTooLate) as error_info:
        await too_late_service.cancel_booking(
            telegram_id=telegram_id, booking_id=booking.id
        )

    assert str(error_info.value) == MESSAGE_TOO_LATE


@pytest.mark.asyncio
async def test_cancel_twice_is_predictable(
    booking_service: BookingService, factory: Any
) -> None:
    telegram_id = factory.telegram_id()
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(12),
    )
    await booking_service.cancel_booking(telegram_id=telegram_id, booking_id=booking.id)

    with pytest.raises(BookingAlreadyCancelled):
        await booking_service.cancel_booking(
            telegram_id=telegram_id, booking_id=booking.id
        )


@pytest.mark.asyncio
async def test_completed_booking_cannot_be_cancelled(
    booking_service: BookingService, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    booking = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(12),
        status=BookingStatus.COMPLETED,
    )

    with pytest.raises(BookingNotCancellable) as error_info:
        await booking_service.cancel_booking(
            telegram_id=user.telegram_id, booking_id=booking.id
        )

    assert str(error_info.value) == MESSAGE_NOT_CANCELLABLE


@pytest.mark.asyncio
async def test_list_user_bookings_returns_details_and_filters(
    booking_service: BookingService, factory: Any
) -> None:
    telegram_id = factory.telegram_id()
    barber = await factory.barber()
    service = await factory.service(price=650, duration=60)

    morning = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(9),
    )
    noon = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(12),
    )
    await booking_service.cancel_booking(telegram_id=telegram_id, booking_id=noon.id)

    all_bookings = await booking_service.list_user_bookings(telegram_id)
    active_only = await booking_service.list_user_bookings(
        telegram_id, include_cancelled=False
    )

    assert [row.id for row in all_bookings] == [morning.id, noon.id]
    assert [row.id for row in active_only] == [morning.id]
    assert all_bookings[0].barber.name == barber.name
    assert all_bookings[0].service.name == service.name
    assert all_bookings[1].status is BookingStatus.CANCELLED
    assert all_bookings[0].cancelled_at is None


@pytest.mark.asyncio
async def test_list_user_bookings_unknown_user_is_empty(
    booking_service: BookingService, factory: Any
) -> None:
    assert await booking_service.list_user_bookings(factory.telegram_id()) == []


@pytest.mark.asyncio
async def test_booking_can_start_immediately_after_adjacent_booking(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service(duration=30)

    first = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(9),
    )
    second = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=monday(9, 30),
    )

    assert first.ends_at == second.starts_at


@pytest.mark.asyncio
async def test_horizon_days_must_be_positive(
    booking_service: BookingService, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    with pytest.raises(ValueError):
        await booking_service.available_dates(
            service_id=service.id, barber_id=barber.id, days=0
        )
