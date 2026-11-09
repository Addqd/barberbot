"""Интеграционные тесты слоя доступа к данным на реальной PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from typing import Any

import pytest

from barberbot.booking.slots import MOSCOW
from barberbot.db.models import Booking, BookingStatus, Service
from barberbot.db.repositories import (
    BookingRepository,
    CatalogRepository,
    ScheduleRepository,
    UserRepository,
)

MONDAY = datetime(2030, 1, 7, 9, 0, tzinfo=MOSCOW)


@pytest.mark.asyncio
async def test_catalog_lists_only_active_rows_from_database(
    sessions: Any, factory: Any
) -> None:
    active_service = await factory.service(price=500, duration=60)
    inactive_service = await factory.service(is_active=False)
    active_barber = await factory.barber()
    inactive_barber = await factory.barber(is_active=False)

    async with sessions() as session:
        catalog = CatalogRepository(session)
        services = await catalog.list_active_services()
        barbers = await catalog.list_active_barbers()
        loaded_service = await catalog.get_service(active_service.id)
        loaded_barber = await catalog.get_barber(active_barber.id)
        missing_service = await catalog.get_service(10**17)
        missing_barber = await catalog.get_barber(10**17)

    service_ids = {row.id for row in services}
    barber_ids = {row.id for row in barbers}

    assert active_service.id in service_ids
    assert inactive_service.id not in service_ids
    assert active_barber.id in barber_ids
    assert inactive_barber.id not in barber_ids
    assert loaded_service is not None and loaded_service.price_rub == 500
    assert loaded_barber is not None and loaded_barber.name == active_barber.name
    assert missing_service is None
    assert missing_barber is None


@pytest.mark.asyncio
async def test_schedule_reads_working_hours_and_time_off(
    sessions: Any, factory: Any
) -> None:
    barber = await factory.barber(weekdays=[0, 2], start=time(10), end=time(16))
    await factory.time_off(
        barber_id=barber.id,
        starts_at=datetime(2030, 1, 7, 12, 0, tzinfo=MOSCOW),
        ends_at=datetime(2030, 1, 7, 13, 0, tzinfo=MOSCOW),
        reason="Обед",
    )
    await factory.time_off(
        barber_id=barber.id,
        starts_at=datetime(2030, 1, 9, 9, 0, tzinfo=MOSCOW),
        ends_at=datetime(2030, 1, 9, 10, 0, tzinfo=MOSCOW),
        reason="Вне окна",
    )

    async with sessions() as session:
        schedule = ScheduleRepository(session)
        working_hours = await schedule.list_working_hours(barber.id)
        monday = await schedule.get_working_hours(barber.id, 0)
        tuesday = await schedule.get_working_hours(barber.id, 1)
        time_off = await schedule.list_time_off(
            barber.id,
            window_start=datetime(2030, 1, 7, 0, 0, tzinfo=MOSCOW),
            window_end=datetime(2030, 1, 8, 0, 0, tzinfo=MOSCOW),
        )

    assert [row.weekday for row in working_hours] == [0, 2]
    assert monday is not None
    assert monday.start_time.hour == 10
    assert monday.end_time.hour == 16
    assert tuesday is None
    assert [row.reason for row in time_off] == ["Обед"]


@pytest.mark.asyncio
async def test_user_get_or_create_is_idempotent(sessions: Any, factory: Any) -> None:
    telegram_id = factory.telegram_id()

    async with sessions() as session, session.begin():
        first = await UserRepository(session).get_or_create(telegram_id, "Имя")

    async with sessions() as session, session.begin():
        second = await UserRepository(session).get_or_create(telegram_id, "Другое")

    assert first.id == second.id
    assert second.display_name == "Имя"

    async with sessions() as session:
        found = await UserRepository(session).get_by_telegram_id(telegram_id)
        missing = await UserRepository(session).get_by_telegram_id(10**17)

    assert found is not None and found.id == first.id
    assert missing is None


@pytest.mark.asyncio
async def test_user_get_or_create_is_race_safe(sessions: Any, factory: Any) -> None:
    telegram_id = factory.telegram_id()

    async def create() -> int:
        async with sessions() as session, session.begin():
            user = await UserRepository(session).get_or_create(telegram_id)
            return user.id

    first_id, second_id = await asyncio.gather(create(), create())

    assert first_id == second_id


@pytest.mark.asyncio
async def test_booking_repository_returns_only_active_bookings(
    sessions: Any, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    confirmed = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=MONDAY,
    )
    cancelled = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=MONDAY + timedelta(minutes=30),
        status=BookingStatus.CANCELLED,
    )
    completed = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=MONDAY + timedelta(hours=3),
        status=BookingStatus.COMPLETED,
    )

    async with sessions() as session:
        repository = BookingRepository(session)
        active = await repository.list_active_between(
            barber.id,
            window_start=datetime(2030, 1, 7, 0, 0, tzinfo=MOSCOW),
            window_end=datetime(2030, 1, 8, 0, 0, tzinfo=MOSCOW),
        )
        loaded = await repository.get_with_details(confirmed.id)
        listed = await repository.list_for_user(user.id)
        without_cancelled = await repository.list_for_user(
            user.id, include_cancelled=False
        )

    assert active is not None
    active_ids = {row.id for row in active}
    assert active_ids == {confirmed.id, completed.id}
    assert cancelled.id not in active_ids
    assert loaded is not None
    assert loaded.barber.name == barber.name
    assert loaded.service.name == service.name
    assert [row.id for row in listed] == [confirmed.id, cancelled.id, completed.id]
    assert [row.id for row in without_cancelled] == [confirmed.id, completed.id]


@pytest.mark.asyncio
async def test_booking_repository_can_load_and_cancel(
    sessions: Any, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    booking = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=MONDAY,
    )
    cancelled_at = MONDAY - timedelta(hours=3)

    async with sessions() as session, session.begin():
        repository = BookingRepository(session)
        loaded = await repository.get(booking.id)
        assert loaded is not None
        await repository.mark_cancelled(loaded, cancelled_at=cancelled_at)

    async with sessions() as session:
        stored = await session.get(Booking, booking.id)

    assert stored is not None
    assert stored.status is BookingStatus.CANCELLED
    assert stored.cancelled_at is not None
    assert stored.cancelled_at == cancelled_at


@pytest.mark.asyncio
async def test_booking_repository_create_returns_primary_key(
    sessions: Any, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service(price=650, duration=45)

    async with sessions() as session, session.begin():
        created = await BookingRepository(session).create(
            user_id=user.id,
            barber_id=barber.id,
            service_id=service.id,
            starts_at=MONDAY,
            ends_at=MONDAY + timedelta(minutes=45),
            price_rub=650,
            duration_minutes=45,
        )

    assert created.id is not None

    async with sessions() as session:
        stored = await session.get(Service, service.id)

    assert stored is not None and stored.price_rub == 650
