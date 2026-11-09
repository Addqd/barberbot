"""Ошибки базы данных, rollback и отсутствие утечек внутренних деталей."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from barberbot.booking import errors
from barberbot.booking.service import (
    MESSAGE_ALREADY_CANCELLED,
    MESSAGE_BARBER_UNAVAILABLE,
    MESSAGE_DATABASE,
    MESSAGE_DOES_NOT_FIT,
    MESSAGE_INVALID_TIME,
    MESSAGE_NOT_CANCELLABLE,
    MESSAGE_NOT_FOUND,
    MESSAGE_NOT_OWNER,
    MESSAGE_OFF_GRID,
    MESSAGE_OUTSIDE_HOURS,
    MESSAGE_PAST,
    MESSAGE_SERVICE_UNAVAILABLE,
    MESSAGE_SLOT_TAKEN,
    MESSAGE_TOO_LATE,
    BookingService,
)
from barberbot.booking.slots import MOSCOW
from barberbot.db.models import Booking
from barberbot.db.repositories import BookingRepository
from barberbot.db_settings import database_url, get_settings

SLOT = datetime(2030, 1, 7, 9, 0, tzinfo=MOSCOW)
FORBIDDEN_FRAGMENTS = (
    "select ",
    "insert ",
    "update ",
    "delete ",
    "psycopg",
    "sqlalchemy",
    "postgres",
    "traceback",
)


@pytest.mark.asyncio
async def test_database_error_becomes_domain_error_without_internal_details() -> None:
    settings = get_settings()
    # Существующий сервер, но несуществующая база: реальная ошибка PostgreSQL.
    missing_url = database_url(settings, target="test").set(
        database="barberbot_missing_for_error_tests"
    )
    engine = create_async_engine(missing_url, connect_args={"connect_timeout": 5})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = BookingService(sessions)
    try:
        with pytest.raises(errors.DatabaseUnavailable) as error_info:
            await service.available_slots(
                service_id=1, barber_id=1, on_date=SLOT.date()
            )
    finally:
        await engine.dispose()

    message = str(error_info.value)
    assert message == MESSAGE_DATABASE
    lowered = message.lower()
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in lowered
    assert settings.postgres_password.get_secret_value() not in message
    assert error_info.value.__cause__ is None


def test_domain_messages_do_not_contain_database_details() -> None:
    messages = [
        MESSAGE_ALREADY_CANCELLED,
        MESSAGE_BARBER_UNAVAILABLE,
        MESSAGE_DATABASE,
        MESSAGE_DOES_NOT_FIT,
        MESSAGE_INVALID_TIME,
        MESSAGE_NOT_CANCELLABLE,
        MESSAGE_NOT_FOUND,
        MESSAGE_NOT_OWNER,
        MESSAGE_OFF_GRID,
        MESSAGE_OUTSIDE_HOURS,
        MESSAGE_PAST,
        MESSAGE_SERVICE_UNAVAILABLE,
        MESSAGE_SLOT_TAKEN,
        MESSAGE_TOO_LATE,
    ]
    for message in messages:
        lowered = message.lower()
        for fragment in FORBIDDEN_FRAGMENTS:
            assert fragment not in lowered, f"Утечка внутренних деталей: {message!r}"


@pytest.mark.asyncio
async def test_failed_transaction_rolls_back_every_statement(
    database: Any, factory: Any
) -> None:
    user = await factory.user()
    other_user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    existing = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=SLOT,
    )

    with pytest.raises(IntegrityError) as error_info:
        async with database.sessions() as session, session.begin():
            repository = BookingRepository(session)
            # Сначала успешная вставка в другом времени...
            await repository.create(
                user_id=other_user.id,
                barber_id=barber.id,
                service_id=service.id,
                starts_at=SLOT + timedelta(hours=6),
                ends_at=SLOT + timedelta(hours=7),
                price_rub=500,
                duration_minutes=60,
            )
            # ...затем конфликтующая, которая обязана откатить всю транзакцию.
            await repository.create(
                user_id=other_user.id,
                barber_id=barber.id,
                service_id=service.id,
                starts_at=SLOT,
                ends_at=SLOT + timedelta(minutes=60),
                price_rub=500,
                duration_minutes=60,
            )

    assert getattr(error_info.value.orig, "sqlstate", None) == "23P01"

    async with database.sessions() as session:
        stored = await session.scalars(
            select(Booking).where(Booking.barber_id == barber.id)
        )
    assert [row.id for row in stored] == [existing.id]


@pytest.mark.asyncio
async def test_conflicting_booking_leaves_no_partial_rows(
    database: Any, factory: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    first_service = BookingService(database.sessions)
    second_service = BookingService(database.sessions)

    first = await first_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=SLOT,
    )

    with pytest.raises(errors.SlotUnavailable):
        await second_service.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=SLOT,
        )

    async with database.sessions() as session:
        stored = await session.scalars(
            select(Booking).where(Booking.barber_id == barber.id)
        )
    assert [row.id for row in stored] == [first.id]
