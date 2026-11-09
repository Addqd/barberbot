"""Конкурентное бронирование на реальной PostgreSQL.

Проверяется именно поведение базы данных: два независимых соединения на один
слот, а также защита exclusion constraint без предварительных Python-проверок.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from barberbot.booking.errors import SlotUnavailable
from barberbot.booking.service import EXCLUSION_VIOLATION, BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.db.models import Booking
from barberbot.db.repositories import BookingRepository

SLOT = datetime(2030, 1, 7, 9, 0, tzinfo=MOSCOW)


async def count_bookings(sessions: Any, barber_id: int) -> int:
    async with sessions() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(Booking)
            .where(Booking.barber_id == barber_id)
        )
    assert total is not None
    return total


@pytest.mark.asyncio
async def test_two_concurrent_requests_for_one_slot_have_exactly_one_winner(
    sessions: Any, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    first_telegram_id = factory.telegram_id()
    second_telegram_id = factory.telegram_id()
    first_service = BookingService(sessions)
    second_service = BookingService(sessions)

    async def book(client: BookingService, telegram_id: int) -> object:
        return await client.create_booking(
            telegram_id=telegram_id,
            barber_id=barber.id,
            service_id=service.id,
            starts_at=SLOT,
        )

    results = await asyncio.gather(
        book(first_service, first_telegram_id),
        book(second_service, second_telegram_id),
        return_exceptions=True,
    )

    created = [result for result in results if isinstance(result, Booking)]
    rejected = [result for result in results if isinstance(result, SlotUnavailable)]
    assert len(created) == 1, f"Ожидался ровно один успех, получено: {results!r}"
    assert len(rejected) == 1, f"Ожидался ровно один конфликт, получено: {results!r}"
    assert await count_bookings(sessions, barber.id) == 1


@pytest.mark.asyncio
async def test_database_conflict_is_mapped_to_domain_error(
    sessions: Any, factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Конфликт, возникший уже после Python-проверки, должен стать SlotUnavailable.

    Слот занимает другой клиент между проверкой доступности и вставкой,
    поэтому срабатывает именно exclusion constraint PostgreSQL (23P01).
    """
    barber = await factory.barber()
    service = await factory.service()
    racing_service = BookingService(sessions)
    rival_service = BookingService(sessions)
    original_ensure_user = racing_service._ensure_user

    async def ensure_user_then_lose_race(
        telegram_id: int, display_name: str | None
    ) -> Any:
        user = await original_ensure_user(telegram_id, display_name)
        await rival_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=SLOT,
        )
        return user

    monkeypatch.setattr(
        racing_service, "_ensure_user", ensure_user_then_lose_race, raising=True
    )

    with pytest.raises(SlotUnavailable):
        await racing_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=SLOT,
        )

    assert await count_bookings(sessions, barber.id) == 1


@pytest.mark.asyncio
async def test_retry_after_conflict_is_predictable(sessions: Any, factory: Any) -> None:
    barber = await factory.barber()
    service = await factory.service()
    first_service = BookingService(sessions)
    second_service = BookingService(sessions)

    await first_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=SLOT,
    )

    with pytest.raises(SlotUnavailable):
        await second_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=SLOT,
        )

    retried = await second_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=SLOT + timedelta(hours=1),
    )

    assert retried.starts_at == SLOT + timedelta(hours=1)
    assert await count_bookings(sessions, barber.id) == 2


@pytest.mark.asyncio
async def test_database_constraint_rejects_overlap_from_separate_sessions(
    sessions: Any, factory: Any
) -> None:
    """Проверка без Python-логики: constraint обязан отклонить пересечение."""
    barber = await factory.barber()
    service = await factory.service()
    first_user = await factory.user()
    second_user = await factory.user()

    async def insert(user_id: int) -> str:
        async with sessions() as session:
            try:
                async with session.begin():
                    await BookingRepository(session).create(
                        user_id=user_id,
                        barber_id=barber.id,
                        service_id=service.id,
                        starts_at=SLOT,
                        ends_at=SLOT + timedelta(minutes=60),
                        price_rub=500,
                        duration_minutes=60,
                    )
            except IntegrityError as error:
                return str(getattr(error.orig, "sqlstate", None))
            return "ok"

    outcomes = await asyncio.gather(insert(first_user.id), insert(second_user.id))

    assert sorted(outcomes) == [EXCLUSION_VIOLATION, "ok"]
    assert await count_bookings(sessions, barber.id) == 1


@pytest.mark.asyncio
async def test_concurrent_bookings_for_different_barbers_do_not_block_each_other(
    sessions: Any, factory: Any
) -> None:
    first_barber = await factory.barber()
    second_barber = await factory.barber()
    service = await factory.service()
    first_service = BookingService(sessions)
    second_service = BookingService(sessions)

    results = await asyncio.gather(
        first_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=first_barber.id,
            service_id=service.id,
            starts_at=SLOT,
        ),
        second_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=second_barber.id,
            service_id=service.id,
            starts_at=SLOT,
        ),
        return_exceptions=True,
    )

    assert all(isinstance(result, Booking) for result in results), results
    assert await count_bookings(sessions, first_barber.id) == 1
    assert await count_bookings(sessions, second_barber.id) == 1
