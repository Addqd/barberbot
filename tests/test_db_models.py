"""Соответствие ORM-моделей фактической схеме PostgreSQL и защита записей.

Тесты работают с реальной тестовой базой ``*_test`` (фикстура ``database``)
и не изменяют схему.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from barberbot.booking.slots import MOSCOW
from barberbot.db.models import (
    Barber,
    BarberTimeOff,
    BarberWorkingHours,
    Base,
    Booking,
    BookingStatus,
    Reminder,
    ReminderStatus,
    Service,
    User,
)

PG_DIALECT = postgresql.dialect()
IGNORED_TABLES = {"alembic_version"}
MONDAY_MORNING = datetime(2030, 1, 7, 9, 0, tzinfo=MOSCOW)


def _sql_type(type_: Any) -> str:
    return str(type_.dialect_impl(PG_DIALECT).compile(dialect=PG_DIALECT))


def _live_facts(connection: Any) -> dict[str, dict[str, Any]]:
    inspector = inspect(connection)
    facts: dict[str, dict[str, Any]] = {}
    for name in inspector.get_table_names(schema="public"):
        if name in IGNORED_TABLES:
            continue
        facts[name] = {
            "columns": {
                column["name"]: {
                    "nullable": column["nullable"],
                    "type": _sql_type(column["type"]),
                }
                for column in inspector.get_columns(name, schema="public")
            },
            "primary_key": tuple(
                inspector.get_pk_constraint(name, schema="public")[
                    "constrained_columns"
                ]
            ),
            "unique": {
                tuple(sorted(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(
                    name, schema="public"
                )
            },
            "checks": {
                constraint["name"]
                for constraint in inspector.get_check_constraints(name, schema="public")
            },
            "foreign_keys": {
                (
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                    tuple(foreign_key["referred_columns"]),
                    foreign_key["options"].get("ondelete"),
                )
                for foreign_key in inspector.get_foreign_keys(name, schema="public")
            },
            "indexes": {
                index["name"]
                for index in inspector.get_indexes(name, schema="public")
                if not index.get("duplicates_constraint")
            },
        }
    return facts


def _metadata_facts() -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for table in Base.metadata.sorted_tables:
        facts[table.name] = {
            "columns": {
                column.name: {
                    "nullable": column.nullable,
                    "type": _sql_type(column.type),
                }
                for column in table.columns
            },
            "primary_key": tuple(column.name for column in table.primary_key.columns),
            "unique": {
                tuple(sorted(constraint.columns.keys()))
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            },
            "checks": {
                constraint.name
                for constraint in table.constraints
                if isinstance(constraint, CheckConstraint)
            },
            "foreign_keys": {
                (
                    (column.name,),
                    foreign_key.target_fullname.split(".")[0],
                    (foreign_key.target_fullname.split(".")[1],),
                    foreign_key.ondelete,
                )
                for column in table.columns
                for foreign_key in column.foreign_keys
            },
            "indexes": {index.name for index in table.indexes},
        }
    return facts


@pytest.mark.asyncio
async def test_orm_metadata_matches_live_schema(database: Any) -> None:
    async with database.engine.connect() as connection:
        live = await connection.run_sync(_live_facts)
    metadata = _metadata_facts()

    assert (
        set(live)
        == set(metadata)
        == {
            "users",
            "barbers",
            "services",
            "barber_working_hours",
            "barber_time_off",
            "bookings",
            "reminders",
        }
    )
    for table_name, expected in metadata.items():
        assert live[table_name] == expected, (
            f"Таблица {table_name} расходится со схемой"
        )


@pytest.mark.asyncio
async def test_exclusion_constraint_exists_in_database_and_metadata(
    database: Any,
) -> None:
    async with database.engine.connect() as connection:
        definition = await connection.scalar(
            text(
                """
                SELECT pg_get_constraintdef(constraint_row.oid)
                FROM pg_constraint AS constraint_row
                JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
                WHERE relation.relname = 'bookings'
                  AND constraint_row.conname = 'ex_bookings_barber_no_overlap'
                """
            )
        )

    assert definition is not None, "Exclusion constraint отсутствует в PostgreSQL"
    assert "EXCLUDE USING gist" in definition
    assert "tstzrange(starts_at, ends_at" in definition
    assert "status" in definition
    assert "ex_bookings_barber_no_overlap" in {
        constraint.name for constraint in Booking.__table__.constraints
    }


@pytest.mark.asyncio
async def test_booking_status_roundtrip_uses_declared_database_values(
    database: Any, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    booking = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=MONDAY_MORNING,
        status=BookingStatus.CANCELLED,
    )

    async with database.sessions() as session:
        raw_status = await session.scalar(
            text("SELECT status FROM bookings WHERE id = :id"),
            {"id": booking.id},
        )
        loaded = await session.get(Booking, booking.id)

    assert raw_status == "cancelled"
    assert loaded is not None
    assert loaded.status is BookingStatus.CANCELLED


@pytest.mark.asyncio
async def test_status_check_constraint_rejects_unknown_value(
    database: Any, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()

    with pytest.raises(IntegrityError) as error_info:
        async with database.sessions() as session, session.begin():
            await session.execute(
                text(
                    """
                        INSERT INTO bookings
                            (user_id, barber_id, service_id, starts_at, ends_at,
                             price_rub_at_booking, duration_minutes_at_booking, status)
                        VALUES
                            (:user_id, :barber_id, :service_id, :starts_at, :ends_at,
                             500, 60, 'unknown')
                        """
                ),
                {
                    "user_id": user.id,
                    "barber_id": barber.id,
                    "service_id": service.id,
                    "starts_at": MONDAY_MORNING,
                    "ends_at": MONDAY_MORNING + timedelta(minutes=60),
                },
            )

    assert getattr(error_info.value.orig, "sqlstate", None) == "23514"


@pytest.mark.asyncio
async def test_relationships_are_mapped_between_all_tables(
    database: Any, factory: Any
) -> None:
    user = await factory.user(display_name="Тест")
    barber = await factory.barber()
    service = await factory.service(price=650)
    await factory.time_off(
        barber_id=barber.id,
        starts_at=datetime(2030, 1, 8, 9, 0, tzinfo=MOSCOW),
        ends_at=datetime(2030, 1, 8, 12, 0, tzinfo=MOSCOW),
        reason="Отпуск",
    )
    booking = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=MONDAY_MORNING,
    )

    async with database.sessions() as session:
        loaded = await session.scalar(
            select(Booking)
            .where(Booking.id == booking.id)
            .options(
                selectinload(Booking.user),
                selectinload(Booking.barber).selectinload(Barber.working_hours),
                selectinload(Booking.barber).selectinload(Barber.time_off),
                selectinload(Booking.service).selectinload(Service.bookings),
            )
        )
        loaded_user = await session.scalar(
            select(User).where(User.id == user.id).options(selectinload(User.bookings))
        )
        reminder = await session.scalar(
            select(Reminder).where(Reminder.booking_id == booking.id)
        )

    assert loaded is not None
    assert loaded.user.telegram_id == user.telegram_id
    assert loaded.barber.name == barber.name
    assert sorted(row.weekday for row in loaded.barber.working_hours) == [0, 1, 2, 3, 4]
    assert [row.reason for row in loaded.barber.time_off] == ["Отпуск"]
    assert loaded.service.price_rub == 650
    assert [row.id for row in loaded.service.bookings] == [booking.id]
    assert loaded_user is not None
    assert [row.id for row in loaded_user.bookings] == [booking.id]
    assert reminder is None
    assert loaded.ends_at - loaded.starts_at == timedelta(minutes=60)


def test_all_seven_tables_are_declared() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "barbers",
        "services",
        "barber_working_hours",
        "barber_time_off",
        "bookings",
        "reminders",
    }


def test_status_enums_values_match_schema_checks() -> None:
    assert {status.value for status in BookingStatus} == {
        "confirmed",
        "cancelled",
        "completed",
    }
    assert {status.value for status in ReminderStatus} == {
        "pending",
        "sent",
        "failed",
        "cancelled",
    }


def test_model_status_columns_map_to_varchar_16() -> None:
    for model in (Booking, Reminder):
        table_column = model.__table__.columns["status"]
        assert _sql_type(table_column.type) == "VARCHAR(16)"


def test_table_names_are_declared_explicitly() -> None:
    assert BarberWorkingHours.__tablename__ == "barber_working_hours"
    assert BarberTimeOff.__tablename__ == "barber_time_off"
