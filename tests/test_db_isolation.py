"""Изоляция тестов: только тестовая база и удаление только своих строк."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import func, select, text

from barberbot.booking.slots import MOSCOW
from barberbot.db.models import Barber, Booking, Service, User
from barberbot.db_settings import database_names, get_settings
from tests.conftest import DataFactory


async def _counts(sessions: Any) -> dict[str, int]:
    async with sessions() as session:
        return {
            "users": await session.scalar(select(func.count()).select_from(User)) or 0,
            "barbers": await session.scalar(select(func.count()).select_from(Barber))
            or 0,
            "services": await session.scalar(select(func.count()).select_from(Service))
            or 0,
            "bookings": await session.scalar(select(func.count()).select_from(Booking))
            or 0,
        }


@pytest.mark.asyncio
async def test_integration_tests_use_only_the_test_database(database: Any) -> None:
    expected = database_names(get_settings())[1]

    async with database.engine.connect() as connection:
        current = await connection.scalar(text("SELECT current_database()"))

    assert database.engine.url.database == expected
    assert current == expected
    assert current.endswith("_test")


def test_test_database_has_a_distinct_name() -> None:
    main_name, test_name = database_names(get_settings())

    assert test_name == main_name + "_test"
    assert test_name != main_name


@pytest.mark.asyncio
async def test_no_test_rows_leaked_from_previous_tests(sessions: Any) -> None:
    async with sessions() as session:
        leaked_services = await session.scalar(
            select(func.count())
            .select_from(Service)
            .where(Service.name.like("\\_\\_test\\_%", escape="\\"))
        )
        leaked_barbers = await session.scalar(
            select(func.count())
            .select_from(Barber)
            .where(Barber.name.like("\\_\\_test\\_%", escape="\\"))
        )
        leaked_users = await session.scalar(
            select(func.count()).select_from(User).where(User.telegram_id < 0)
        )

    assert (leaked_services, leaked_barbers, leaked_users) == (0, 0, 0)


@pytest.mark.asyncio
async def test_factory_cleanup_deletes_only_its_own_rows(sessions: Any) -> None:
    before = await _counts(sessions)
    local = DataFactory(sessions)

    user = await local.user()
    barber = await local.barber()
    service = await local.service()
    await local.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=datetime(2030, 1, 7, 9, 0, tzinfo=MOSCOW),
    )

    after_create = await _counts(sessions)
    assert after_create["users"] == before["users"] + 1
    assert after_create["barbers"] == before["barbers"] + 1
    assert after_create["services"] == before["services"] + 1
    assert after_create["bookings"] == before["bookings"] + 1

    await local.cleanup()

    after_cleanup = await _counts(sessions)
    assert after_cleanup == before
