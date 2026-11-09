"""Интеграционные тесты административного сервиса на реальной PostgreSQL.

Используется только тестовая база ``barberbot_test``: фикстуры ``sessions`` и
``factory`` проверяют фактическое имя базы, создают уникальные строки
``__test_...`` и удаляют только их. Seed-данные не изменяются.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, time
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from barberbot.admin import texts as admin_texts
from barberbot.admin.errors import (
    AdminAccessDenied,
    AdminBookingState,
    AdminConflict,
    AdminDatabaseUnavailable,
    AdminNotFound,
    AdminValidationError,
)
from barberbot.admin.service import (
    AdminService,
    check_duration_minutes,
    check_weekday,
    paginate,
    parse_day,
    parse_duration,
    parse_period,
    parse_price,
    parse_working_hours,
)
from barberbot.booking.errors import CancellationTooLate
from barberbot.booking.service import BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.db.models import Booking, BookingStatus, Service

ADMIN_ID = 800000001
OTHER_ID = 800000002


def at(hour: int, minute: int = 0, day: int = 7) -> datetime:
    """Время по Москве в понедельник 07.01.2030 (фиксированное «сейчас»)."""
    return datetime(2030, 1, day, hour, minute, tzinfo=MOSCOW)


@pytest.fixture
def admin(sessions: async_sessionmaker[AsyncSession]) -> AdminService:
    return AdminService(sessions, admin_ids=frozenset({ADMIN_ID}), clock=lambda: at(8))


@pytest.fixture
def intruder(sessions: async_sessionmaker[AsyncSession]) -> AdminService:
    return AdminService(sessions, admin_ids=frozenset({ADMIN_ID}), clock=lambda: at(8))


async def service_exists(
    sessions: async_sessionmaker[AsyncSession], service_id: int
) -> Service | None:
    async with sessions() as session:
        return await session.get(Service, service_id)


# --------------------------------------------------------------------------- #
# Авторизация
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_non_admin_is_denied_on_every_operation(
    intruder: AdminService, factory: Any
) -> None:
    service = await factory.service()
    barber = await factory.barber()

    calls = [
        intruder.list_services(actor_telegram_id=OTHER_ID),
        intruder.get_service(actor_telegram_id=OTHER_ID, service_id=service.id),
        intruder.create_service(
            actor_telegram_id=OTHER_ID,
            name=factory.unique("forbidden"),
            price_rub=100,
            duration_minutes=30,
        ),
        intruder.toggle_service(actor_telegram_id=OTHER_ID, service_id=service.id),
        intruder.list_barbers(actor_telegram_id=OTHER_ID),
        intruder.toggle_barber(actor_telegram_id=OTHER_ID, barber_id=barber.id),
        intruder.list_bookings(actor_telegram_id=OTHER_ID),
        intruder.cancel_booking(actor_telegram_id=OTHER_ID, booking_id=1),
    ]

    for call in calls:
        with pytest.raises(AdminAccessDenied):
            await call


@pytest.mark.asyncio
async def test_denied_toggle_does_not_change_service(
    intruder: AdminService, factory: Any, sessions: Any
) -> None:
    service = await factory.service()

    with pytest.raises(AdminAccessDenied):
        await intruder.toggle_service(actor_telegram_id=OTHER_ID, service_id=service.id)

    stored = await service_exists(sessions, service.id)
    assert stored is not None
    assert stored.is_active is True


def test_every_public_admin_operation_checks_permissions() -> None:
    """Новый публичный метод без проверки прав должен ломать этот тест."""
    public_methods = [
        (name, member)
        for name, member in inspect.getmembers(
            AdminService, predicate=inspect.iscoroutinefunction
        )
        if not name.startswith("_")
    ]

    assert public_methods, "у AdminService нет публичных асинхронных операций"
    missing = [
        name
        for name, member in public_methods
        if "_authorize(" not in inspect.getsource(member)
    ]
    assert missing == []


# --------------------------------------------------------------------------- #
# Услуги
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_service_is_created_and_listed(
    admin: AdminService, factory: Any, booking_service: BookingService
) -> None:
    name = factory.unique("service")

    created = await admin.create_service(
        actor_telegram_id=ADMIN_ID,
        name=f"  {name}  ",
        price_rub=1200,
        duration_minutes=45,
    )

    assert created.name == name
    assert created.is_active is True
    factory.track_service(created.id)

    result = await admin.list_services(actor_telegram_id=ADMIN_ID)
    found = False
    for page in range(result.page.pages):
        page_result = await admin.list_services(actor_telegram_id=ADMIN_ID, page=page)
        found = found or any(row.id == created.id for row in page_result.rows)
    assert found is True

    active = await booking_service.list_active_services()
    assert created.id in {row.id for row in active}


@pytest.mark.asyncio
async def test_duplicate_service_name_is_rejected(
    admin: AdminService, factory: Any
) -> None:
    name = factory.unique("service")
    first = await admin.create_service(
        actor_telegram_id=ADMIN_ID,
        name=name,
        price_rub=500,
        duration_minutes=30,
    )
    factory.track_service(first.id)

    with pytest.raises(AdminValidationError) as error:
        await admin.create_service(
            actor_telegram_id=ADMIN_ID,
            name=name,
            price_rub=700,
            duration_minutes=30,
        )

    assert str(error.value) == admin_texts.SERVICE_NAME_TAKEN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("price", "duration"),
    [(-1, 30), (100, 0), (100, 61), (100, -5)],
    ids=["negative-price", "zero-duration", "long-duration", "negative-duration"],
)
async def test_invalid_service_values_are_rejected(
    admin: AdminService, factory: Any, price: int, duration: int
) -> None:
    with pytest.raises(AdminValidationError):
        await admin.create_service(
            actor_telegram_id=ADMIN_ID,
            name=factory.unique("service"),
            price_rub=price,
            duration_minutes=duration,
        )


@pytest.mark.asyncio
async def test_service_is_updated_field_by_field(
    admin: AdminService, factory: Any
) -> None:
    service = await factory.service(price=500, duration=60)
    new_name = factory.unique("service")

    renamed = await admin.update_service(
        actor_telegram_id=ADMIN_ID, service_id=service.id, name=new_name
    )
    assert renamed.name == new_name

    repriced = await admin.update_service(
        actor_telegram_id=ADMIN_ID, service_id=service.id, price_rub=1500
    )
    assert repriced.price_rub == 1500

    resized = await admin.update_service(
        actor_telegram_id=ADMIN_ID, service_id=service.id, duration_minutes=30
    )
    assert resized.duration_minutes == 30
    assert resized.name == new_name
    assert resized.price_rub == 1500


@pytest.mark.asyncio
async def test_update_to_existing_name_is_rejected(
    admin: AdminService, factory: Any
) -> None:
    first = await factory.service()
    second = await factory.service()

    with pytest.raises(AdminValidationError) as error:
        await admin.update_service(
            actor_telegram_id=ADMIN_ID, service_id=second.id, name=first.name
        )

    assert str(error.value) == admin_texts.SERVICE_NAME_TAKEN


@pytest.mark.asyncio
async def test_missing_service_is_reported(admin: AdminService) -> None:
    with pytest.raises(AdminNotFound):
        await admin.get_service(actor_telegram_id=ADMIN_ID, service_id=10**12)


@pytest.mark.asyncio
async def test_service_is_disabled_but_history_is_kept(
    admin: AdminService,
    factory: Any,
    booking_service: BookingService,
    sessions: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    telegram_id = factory.telegram_id()
    booking = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    disabled = await admin.toggle_service(
        actor_telegram_id=ADMIN_ID, service_id=service.id
    )
    assert disabled.is_active is False

    active = await booking_service.list_active_services()
    assert service.id not in {row.id for row in active}

    async with sessions() as session:
        stored = await session.get(Booking, booking.id)
    assert stored is not None
    assert stored.status == BookingStatus.CONFIRMED

    enabled = await admin.toggle_service(
        actor_telegram_id=ADMIN_ID, service_id=service.id
    )
    assert enabled.is_active is True


@pytest.mark.asyncio
async def test_service_change_does_not_touch_booking_snapshots(
    admin: AdminService,
    factory: Any,
    booking_service: BookingService,
    sessions: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service(price=500, duration=60)
    telegram_id = factory.telegram_id()
    booking = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    await admin.update_service(
        actor_telegram_id=ADMIN_ID,
        service_id=service.id,
        price_rub=2000,
        duration_minutes=30,
    )

    async with sessions() as session:
        stored = await session.get(Booking, booking.id)
    assert stored is not None
    assert stored.price_rub_at_booking == 500
    assert stored.duration_minutes_at_booking == 60


# --------------------------------------------------------------------------- #
# Барберы и расписание
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_new_barber_is_inactive_and_can_be_enabled(
    admin: AdminService, factory: Any, booking_service: BookingService
) -> None:
    name = factory.unique("barber")

    created = await admin.create_barber(actor_telegram_id=ADMIN_ID, name=name)
    factory.track_barber(created.id)

    assert created.is_active is False
    active = await booking_service.list_active_barbers()
    assert created.id not in {row.id for row in active}

    enabled = await admin.toggle_barber(
        actor_telegram_id=ADMIN_ID, barber_id=created.id
    )
    assert enabled.is_active is True
    active = await booking_service.list_active_barbers()
    assert created.id in {row.id for row in active}


@pytest.mark.asyncio
async def test_duplicate_barber_name_is_rejected(
    admin: AdminService, factory: Any
) -> None:
    name = factory.unique("barber")
    duplicate = await admin.create_barber(actor_telegram_id=ADMIN_ID, name=name)
    factory.track_barber(duplicate.id)

    with pytest.raises(AdminValidationError) as error:
        await admin.create_barber(actor_telegram_id=ADMIN_ID, name=name)

    assert str(error.value) == admin_texts.BARBER_NAME_TAKEN


@pytest.mark.asyncio
async def test_working_hours_are_updated(admin: AdminService, factory: Any) -> None:
    barber = await factory.barber()

    await admin.set_working_hours(
        actor_telegram_id=ADMIN_ID,
        barber_id=barber.id,
        weekday=0,
        start_time=time(10, 0),
        end_time=time(16, 0),
    )

    view = await admin.get_barber(actor_telegram_id=ADMIN_ID, barber_id=barber.id)
    monday = view.hours[0]
    assert monday.start_time == time(10, 0)
    assert monday.end_time == time(16, 0)


@pytest.mark.asyncio
async def test_invalid_working_hours_are_rejected(
    admin: AdminService, factory: Any
) -> None:
    barber = await factory.barber()

    with pytest.raises(AdminValidationError):
        await admin.set_working_hours(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            weekday=0,
            start_time=time(18, 0),
            end_time=time(10, 0),
        )


@pytest.mark.asyncio
async def test_schedule_change_conflicting_with_booking_is_rejected(
    admin: AdminService,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    with pytest.raises(AdminConflict) as error:
        await admin.set_working_hours(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            weekday=0,
            start_time=time(10, 0),
            end_time=time(17, 0),
        )

    message = str(error.value)
    assert "Изменение отклонено" in message
    assert f"запись №{booking.id}" in message

    view = await admin.get_barber(actor_telegram_id=ADMIN_ID, barber_id=barber.id)
    assert view.hours[0].start_time == time(9, 0)


@pytest.mark.asyncio
async def test_schedule_change_succeeds_after_cancelling_conflict(
    admin: AdminService,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    await admin.cancel_booking(actor_telegram_id=ADMIN_ID, booking_id=booking.id)
    hours = await admin.set_working_hours(
        actor_telegram_id=ADMIN_ID,
        barber_id=barber.id,
        weekday=0,
        start_time=time(10, 0),
        end_time=time(17, 0),
    )

    assert hours.start_time == time(10, 0)


@pytest.mark.asyncio
async def test_working_hours_for_booking_free_day_can_shrink(
    admin: AdminService,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    # Вторник свободен: сокращение вторника не конфликтует с записями.
    hours = await admin.set_working_hours(
        actor_telegram_id=ADMIN_ID,
        barber_id=barber.id,
        weekday=1,
        start_time=time(12, 0),
        end_time=time(14, 0),
    )

    assert hours.weekday == 1
    assert hours.start_time == time(12, 0)


@pytest.mark.asyncio
async def test_clearing_working_hours_with_future_booking_is_rejected(
    admin: AdminService,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    with pytest.raises(AdminConflict):
        await admin.clear_working_hours(
            actor_telegram_id=ADMIN_ID, barber_id=barber.id, weekday=0
        )

    await admin.cancel_booking(actor_telegram_id=ADMIN_ID, booking_id=booking.id)
    await admin.clear_working_hours(
        actor_telegram_id=ADMIN_ID, barber_id=barber.id, weekday=0
    )

    view = await admin.get_barber(actor_telegram_id=ADMIN_ID, barber_id=barber.id)
    assert 0 not in view.hours


# --------------------------------------------------------------------------- #
# Периоды отсутствия
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_time_off_is_added_and_removed(admin: AdminService, factory: Any) -> None:
    barber = await factory.barber()

    row = await admin.add_time_off(
        actor_telegram_id=ADMIN_ID,
        barber_id=barber.id,
        starts_at=at(0, 0, day=8),
        ends_at=at(0, 0, day=9),
    )
    page = await admin.list_time_off(actor_telegram_id=ADMIN_ID, barber_id=barber.id)
    assert row.id in {item.id for item in page.rows}

    await admin.remove_time_off(
        actor_telegram_id=ADMIN_ID, barber_id=barber.id, time_off_id=row.id
    )
    page = await admin.list_time_off(actor_telegram_id=ADMIN_ID, barber_id=barber.id)
    assert row.id not in {item.id for item in page.rows}


@pytest.mark.asyncio
async def test_time_off_removal_is_not_repeatable(
    admin: AdminService, factory: Any
) -> None:
    barber = await factory.barber()
    row = await admin.add_time_off(
        actor_telegram_id=ADMIN_ID,
        barber_id=barber.id,
        starts_at=at(0, 0, day=8),
        ends_at=at(0, 0, day=9),
    )

    await admin.remove_time_off(
        actor_telegram_id=ADMIN_ID, barber_id=barber.id, time_off_id=row.id
    )

    with pytest.raises(AdminNotFound):
        await admin.remove_time_off(
            actor_telegram_id=ADMIN_ID, barber_id=barber.id, time_off_id=row.id
        )


@pytest.mark.asyncio
async def test_time_off_conflicting_with_booking_is_rejected(
    admin: AdminService, factory: Any, booking_service: BookingService
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    with pytest.raises(AdminConflict) as error:
        await admin.add_time_off(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            starts_at=at(0, 0),
            ends_at=at(0, 0, day=8),
        )

    assert f"запись №{booking.id}" in str(error.value)


@pytest.mark.asyncio
async def test_overlapping_time_off_is_rejected(
    admin: AdminService, factory: Any
) -> None:
    barber = await factory.barber()
    await admin.add_time_off(
        actor_telegram_id=ADMIN_ID,
        barber_id=barber.id,
        starts_at=at(0, 0, day=8),
        ends_at=at(0, 0, day=10),
    )

    with pytest.raises(AdminValidationError) as error:
        await admin.add_time_off(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            starts_at=at(0, 0, day=9),
            ends_at=at(0, 0, day=11),
        )

    assert str(error.value) == admin_texts.PERIOD_OVERLAP


@pytest.mark.asyncio
async def test_time_off_in_the_past_is_rejected(
    admin: AdminService, factory: Any
) -> None:
    barber = await factory.barber()

    with pytest.raises(AdminValidationError) as error:
        await admin.add_time_off(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            starts_at=at(0, 0, day=1),
            ends_at=at(0, 0, day=2),
        )

    assert str(error.value) == admin_texts.PERIOD_IN_PAST


# --------------------------------------------------------------------------- #
# Записи клиентов
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_cancel_bypasses_client_deadline(
    admin: AdminService, factory: Any, booking_service: BookingService
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    telegram_id = factory.telegram_id()
    # До начала записи меньше 2 часов: клиентская отмена запрещена.
    booking = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    with pytest.raises(CancellationTooLate):
        await booking_service.cancel_booking(
            telegram_id=telegram_id, booking_id=booking.id
        )

    cancelled = await admin.cancel_booking(
        actor_telegram_id=ADMIN_ID, booking_id=booking.id
    )

    assert cancelled.status == BookingStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert cancelled.user.telegram_id == telegram_id
    assert cancelled.service.id == service.id
    assert cancelled.barber.id == barber.id


@pytest.mark.asyncio
async def test_repeated_admin_cancel_is_rejected(
    admin: AdminService, factory: Any, booking_service: BookingService
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    await admin.cancel_booking(actor_telegram_id=ADMIN_ID, booking_id=booking.id)

    with pytest.raises(AdminBookingState) as error:
        await admin.cancel_booking(actor_telegram_id=ADMIN_ID, booking_id=booking.id)

    assert str(error.value) == admin_texts.BOOKING_ALREADY_CANCELLED


@pytest.mark.asyncio
async def test_completed_booking_cannot_be_cancelled(
    admin: AdminService, factory: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    booking = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
        status=BookingStatus.COMPLETED,
    )

    with pytest.raises(AdminBookingState) as error:
        await admin.cancel_booking(actor_telegram_id=ADMIN_ID, booking_id=booking.id)

    assert str(error.value) == admin_texts.BOOKING_COMPLETED


@pytest.mark.asyncio
async def test_concurrent_admin_cancel_has_exactly_one_winner(
    sessions: async_sessionmaker[AsyncSession], factory: Any, booking_service: Any
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )
    first = AdminService(sessions, admin_ids=frozenset({ADMIN_ID}), clock=lambda: at(8))
    second = AdminService(
        sessions, admin_ids=frozenset({ADMIN_ID}), clock=lambda: at(8)
    )

    results = await asyncio.gather(
        first.cancel_booking(actor_telegram_id=ADMIN_ID, booking_id=booking.id),
        second.cancel_booking(actor_telegram_id=ADMIN_ID, booking_id=booking.id),
        return_exceptions=True,
    )

    successes = [item for item in results if isinstance(item, Booking)]
    failures = [item for item in results if isinstance(item, AdminBookingState)]
    assert len(successes) == 1
    assert len(failures) == 1


@pytest.mark.asyncio
async def test_admin_bookings_are_filtered_by_date_and_barber(
    admin: AdminService,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    other_barber = await factory.barber()
    service = await factory.service()
    monday = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )
    await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=other_barber.id,
        service_id=service.id,
        starts_at=at(11),
    )

    filtered = await admin.list_bookings(
        actor_telegram_id=ADMIN_ID,
        on_date=monday.starts_at.date(),
        barber_id=barber.id,
    )

    assert [row.id for row in filtered.rows] == [monday.id]
    assert filtered.rows[0].service.name == service.name
    assert filtered.rows[0].user is not None
    assert filtered.rows[0].barber.id == barber.id

    empty = await admin.list_bookings(
        actor_telegram_id=ADMIN_ID, on_date=at(0, 0, day=20).date()
    )
    assert empty.rows == []


@pytest.mark.asyncio
async def test_admin_booking_card_contains_details(
    admin: AdminService, factory: Any, booking_service: BookingService
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    telegram_id = factory.telegram_id()
    booking = await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
        display_name="Клиент",
    )

    card = await admin.get_booking(actor_telegram_id=ADMIN_ID, booking_id=booking.id)

    assert card.id == booking.id
    assert card.user.telegram_id == telegram_id
    assert card.user.display_name == "Клиент"
    assert card.price_rub_at_booking == service.price_rub
    assert card.duration_minutes_at_booking == service.duration_minutes


# --------------------------------------------------------------------------- #
# Ошибки базы данных и разбор ввода
# --------------------------------------------------------------------------- #


class BrokenSessions:
    """Фабрика сессий, которая имитирует недоступную PostgreSQL."""

    def __call__(self) -> None:
        raise OperationalError(
            "SELECT secret_column FROM secret_table", {}, Exception("boom")
        )


@pytest.mark.asyncio
async def test_database_error_is_translated_without_internals() -> None:
    service = AdminService(
        BrokenSessions(),  # type: ignore[arg-type]
        admin_ids=frozenset({ADMIN_ID}),
    )

    with pytest.raises(AdminDatabaseUnavailable) as error:
        await service.list_services(actor_telegram_id=ADMIN_ID)

    message = str(error.value)
    assert message == admin_texts.DATABASE_ERROR
    assert "secret_column" not in message
    assert "SELECT" not in message


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("500", 500), (" 0 ", 0), ("1500 ₽", 1500)],
    ids=["plain", "zero", "with-currency"],
)
def test_price_parser_accepts_valid_values(raw: str, expected: int) -> None:
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["-1", "1.5", "abc", "", "9999999999"])
def test_price_parser_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(AdminValidationError):
        parse_price(raw)


def test_duration_and_weekday_limits() -> None:
    assert parse_duration("60") == 60
    assert check_duration_minutes(1) == 1
    assert check_weekday(6) == 6
    for raw in ("0", "61", "abc", ""):
        with pytest.raises(AdminValidationError):
            parse_duration(raw)
    for weekday in (-1, 7):
        with pytest.raises(AdminValidationError):
            check_weekday(weekday)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("09:00-18:00", (time(9, 0), time(18, 0))),
        ("9:00 - 18:00", (time(9, 0), time(18, 0))),
        ("10:30–15:00", (time(10, 30), time(15, 0))),
        ("выходной", None),
        ("  Выходной день ", None),
    ],
    ids=["plain", "spaces", "dash", "day-off", "day-off-spaces"],
)
def test_working_hours_parser(raw: str, expected: tuple[time, time] | None) -> None:
    assert parse_working_hours(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["18:00-09:00", "09:00", "09:00-09:00", "25:00-26:00", "09:60-10:00", "abc"],
)
def test_working_hours_parser_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(AdminValidationError):
        parse_working_hours(raw)


def test_period_parser_builds_moscow_intervals() -> None:
    single_start, single_end = parse_period("08.01.2030")
    assert single_start == at(0, 0, day=8)
    assert single_end == at(0, 0, day=9)

    range_start, range_end = parse_period("08.01.2030-10.01.2030")
    assert range_start == at(0, 0, day=8)
    assert range_end == at(0, 0, day=11)


@pytest.mark.parametrize(
    "raw",
    ["10.01.2030-08.01.2030", "abc", "08.01.2030-", "08.01.2030-09.01.2030-10.01.2030"],
)
def test_period_parser_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(AdminValidationError):
        parse_period(raw)


def test_day_parser_rejects_wrong_format() -> None:
    with pytest.raises(AdminValidationError):
        parse_day("2030-01-08")


def test_pagination_bounds() -> None:
    assert paginate(0, 0) == paginate(0, 0)
    assert paginate(0, 5).number == 0
    assert paginate(0, 5).pages == 1
    assert paginate(12, 0).offset == 0
    assert paginate(12, 1).offset == 5
    assert paginate(12, 10).number == 2
    assert paginate(12, 10).offset == 10
