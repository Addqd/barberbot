"""Гонка между бронированием клиента и административными изменениями.

Тесты детерминированные: вместо случайных задержек используется одноразовый
перехват вызова репозитория, поэтому порядок операций задан явно.

* «Администратор первым» — административное изменение полностью
  коммитится в момент, когда клиентская транзакция ещё только собирается
  взять блокировку строки мастера.
* «Клиент первым» — клиентская транзакция вставляет запись и удерживает
  блокировки, административная операция запускается параллельно и обязана
  дождаться коммита клиента.

Работаем только с тестовой базой ``barberbot_test`` (фикстуры ``sessions`` и
``factory`` проверяют фактическое имя базы).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Any

import pytest
from sqlalchemy import select

from barberbot.admin.errors import AdminConflict
from barberbot.admin.service import AdminService
from barberbot.booking.errors import (
    BarberUnavailable,
    InvalidBookingTime,
    ServiceUnavailable,
    SlotUnavailable,
)
from barberbot.booking.service import BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.db.models import BarberWorkingHours, Booking
from barberbot.db.repositories import BookingRepository, CatalogRepository

ADMIN_ID = 910000001


def at(hour: int, minute: int = 0, day: int = 7) -> datetime:
    """Время по Москве; 07.01.2030 — понедельник (фиксированное «сейчас»)."""
    return datetime(2030, 1, day, hour, minute, tzinfo=MOSCOW)


@pytest.fixture
def admin(sessions: Any) -> AdminService:
    return AdminService(sessions, admin_ids=frozenset({ADMIN_ID}), clock=lambda: at(8))


@pytest.fixture
def client(sessions: Any) -> BookingService:
    return BookingService(sessions, clock=lambda: at(8))


async def bookings_of_barber(sessions: Any, barber_id: int) -> list[Booking]:
    async with sessions() as session:
        return list(
            await session.scalars(select(Booking).where(Booking.barber_id == barber_id))
        )


async def booking_ids_of_barber(sessions: Any, barber_id: int) -> list[int]:
    return [row.id for row in await bookings_of_barber(sessions, barber_id)]


async def weekday_hours(
    admin: AdminService, barber_id: int, weekday: int
) -> BarberWorkingHours | None:
    view = await admin.get_barber(actor_telegram_id=ADMIN_ID, barber_id=barber_id)
    return view.hours.get(weekday)


def hook_before_lock(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    action: Any,
    *,
    target: type = CatalogRepository,
) -> dict[str, Any]:
    """Выполнить ``action`` ровно один раз перед блокировкой клиента."""
    original = getattr(target, method_name)
    state: dict[str, Any] = {"armed": False, "task": None}

    async def wrapper(instance: Any, *args: Any, **kwargs: Any) -> Any:
        if state["armed"] and asyncio.current_task() is state["task"]:
            state["armed"] = False
            await action()
        return await original(instance, *args, **kwargs)

    monkeypatch.setattr(target, method_name, wrapper)
    return state


def arm_for_current_task(state: dict[str, Any]) -> None:
    state["task"] = asyncio.current_task()
    state["armed"] = True


# --------------------------------------------------------------------------- #
# Администратор первым: клиент обязан увидеть уже изменённые условия
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_hours_change_before_client_lock_rejects_booking(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    state = hook_before_lock(
        monkeypatch,
        "get_barber_for_update",
        lambda: admin.set_working_hours(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            weekday=0,
            start_time=time(10, 0),
            end_time=time(17, 0),
        ),
    )
    arm_for_current_task(state)

    with pytest.raises(InvalidBookingTime) as error:
        await client.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=at(9),
        )

    assert "вне рабочего графика" in str(error.value)
    assert await bookings_of_barber(sessions, barber.id) == []
    hours = await weekday_hours(admin, barber.id, 0)
    assert hours is not None
    assert hours.start_time == time(10, 0)


@pytest.mark.asyncio
async def test_admin_time_off_before_client_lock_rejects_booking(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    state = hook_before_lock(
        monkeypatch,
        "get_barber_for_update",
        lambda: admin.add_time_off(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            starts_at=at(0, 0, day=7),
            ends_at=at(0, 0, day=8),
        ),
    )
    arm_for_current_task(state)

    with pytest.raises(SlotUnavailable):
        await client.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=at(9),
        )

    assert await bookings_of_barber(sessions, barber.id) == []


@pytest.mark.asyncio
async def test_disabled_barber_before_client_lock_rejects_booking(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    state = hook_before_lock(
        monkeypatch,
        "get_barber_for_update",
        lambda: admin.toggle_barber(actor_telegram_id=ADMIN_ID, barber_id=barber.id),
    )
    arm_for_current_task(state)

    with pytest.raises(BarberUnavailable):
        await client.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=at(9),
        )

    assert await bookings_of_barber(sessions, barber.id) == []


@pytest.mark.asyncio
async def test_disabled_service_before_client_lock_rejects_booking(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    state = hook_before_lock(
        monkeypatch,
        "get_service_for_update",
        lambda: admin.toggle_service(actor_telegram_id=ADMIN_ID, service_id=service.id),
    )
    arm_for_current_task(state)

    with pytest.raises(ServiceUnavailable):
        await client.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=at(9),
        )

    assert await bookings_of_barber(sessions, barber.id) == []


@pytest.mark.asyncio
async def test_duration_change_before_client_lock_rejects_booking(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Удлинённая услуга перестаёт помещаться в рабочие часы."""
    barber = await factory.barber()
    service = await factory.service(duration=30)
    state = hook_before_lock(
        monkeypatch,
        "get_service_for_update",
        lambda: admin.update_service(
            actor_telegram_id=ADMIN_ID,
            service_id=service.id,
            duration_minutes=60,
        ),
    )
    arm_for_current_task(state)

    with pytest.raises(InvalidBookingTime) as error:
        await client.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=at(16, 30),
        )

    assert "не помещается" in str(error.value)
    assert await bookings_of_barber(sessions, barber.id) == []


@pytest.mark.asyncio
async def test_duration_change_before_client_lock_is_used_for_new_booking(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Запись создаётся по актуальным параметрам услуги, а не по предварительным."""
    barber = await factory.barber()
    service = await factory.service(duration=30, price=500)
    state = hook_before_lock(
        monkeypatch,
        "get_service_for_update",
        lambda: admin.update_service(
            actor_telegram_id=ADMIN_ID,
            service_id=service.id,
            duration_minutes=60,
            price_rub=900,
        ),
    )
    arm_for_current_task(state)

    booking = await client.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    assert booking.duration_minutes_at_booking == 60
    assert booking.price_rub_at_booking == 900
    assert booking.ends_at == at(10)
    assert await booking_ids_of_barber(sessions, barber.id) == [booking.id]


# --------------------------------------------------------------------------- #
# Клиент первым: административное изменение обязано увидеть новую запись
# --------------------------------------------------------------------------- #


def hold_inside_booking_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Приостановить клиентскую транзакцию сразу после вставки записи."""
    original = BookingRepository.create
    state: dict[str, Any] = {
        "armed": True,
        "task": None,
        "inserted": asyncio.Event(),
        "release": asyncio.Event(),
    }

    async def create_and_pause(instance: Any, **kwargs: Any) -> Any:
        booking = await original(instance, **kwargs)
        if state["armed"] and asyncio.current_task() is state["task"]:
            state["armed"] = False
            state["inserted"].set()
            await state["release"].wait()
        return booking

    monkeypatch.setattr(BookingRepository, "create", create_and_pause)
    return state


def notice_admin_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Отметить момент, когда административная транзакция подошла к блокировке."""
    original = CatalogRepository.get_barber_for_update
    state: dict[str, Any] = {"task": None, "arrived": asyncio.Event()}

    async def notice(instance: Any, barber_id: int) -> Any:
        if asyncio.current_task() is state["task"]:
            state["arrived"].set()
        return await original(instance, barber_id)

    monkeypatch.setattr(CatalogRepository, "get_barber_for_update", notice)
    return state


@pytest.mark.asyncio
async def test_booking_created_first_makes_hours_change_conflict(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    pause = hold_inside_booking_transaction(monkeypatch)
    arrival = notice_admin_lock(monkeypatch)

    booking_task = asyncio.create_task(
        client.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=at(9),
        )
    )
    pause["task"] = booking_task
    await asyncio.wait_for(pause["inserted"].wait(), timeout=10)

    hours_task = asyncio.create_task(
        admin.set_working_hours(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            weekday=0,
            start_time=time(10, 0),
            end_time=time(17, 0),
        )
    )
    arrival["task"] = hours_task
    await asyncio.wait_for(arrival["arrived"].wait(), timeout=10)
    assert not hours_task.done(), "Смена часов не должна пройти до коммита записи"

    pause["release"].set()
    created = await asyncio.wait_for(booking_task, timeout=10)
    assert created.starts_at == at(9)

    with pytest.raises(AdminConflict):
        await asyncio.wait_for(hours_task, timeout=10)

    assert await booking_ids_of_barber(sessions, barber.id) == [created.id]
    hours = await weekday_hours(admin, barber.id, 0)
    assert hours is not None
    assert hours.start_time == time(9, 0)


@pytest.mark.asyncio
async def test_booking_created_first_makes_time_off_add_conflict(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    pause = hold_inside_booking_transaction(monkeypatch)
    arrival = notice_admin_lock(monkeypatch)

    booking_task = asyncio.create_task(
        client.create_booking(
            telegram_id=factory.telegram_id(),
            barber_id=barber.id,
            service_id=service.id,
            starts_at=at(9),
        )
    )
    pause["task"] = booking_task
    await asyncio.wait_for(pause["inserted"].wait(), timeout=10)

    time_off_task = asyncio.create_task(
        admin.add_time_off(
            actor_telegram_id=ADMIN_ID,
            barber_id=barber.id,
            starts_at=at(0, 0, day=7),
            ends_at=at(0, 0, day=8),
        )
    )
    arrival["task"] = time_off_task
    await asyncio.wait_for(arrival["arrived"].wait(), timeout=10)
    assert not time_off_task.done(), "Период отсутствия не должен пройти до коммита"

    pause["release"].set()
    created = await asyncio.wait_for(booking_task, timeout=10)

    with pytest.raises(AdminConflict):
        await asyncio.wait_for(time_off_task, timeout=10)

    assert await booking_ids_of_barber(sessions, barber.id) == [created.id]
    page = await admin.list_time_off(actor_telegram_id=ADMIN_ID, barber_id=barber.id)
    assert page.rows == []


# --------------------------------------------------------------------------- #
# Реальная параллельность: инварианты вместо предсказания победителя
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_parallel_hours_change_and_booking_never_break_availability(
    sessions: Any,
    factory: Any,
    admin: AdminService,
    client: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()

    results = await asyncio.wait_for(
        asyncio.gather(
            client.create_booking(
                telegram_id=factory.telegram_id(),
                barber_id=barber.id,
                service_id=service.id,
                starts_at=at(9),
            ),
            admin.set_working_hours(
                actor_telegram_id=ADMIN_ID,
                barber_id=barber.id,
                weekday=0,
                start_time=time(10, 0),
                end_time=time(17, 0),
            ),
            return_exceptions=True,
        ),
        timeout=20,
    )
    booking_result, hours_result = results

    assert isinstance(booking_result, (Booking, InvalidBookingTime, SlotUnavailable)), (
        booking_result
    )
    assert isinstance(hours_result, (BarberWorkingHours, AdminConflict)), hours_result

    hours = await weekday_hours(admin, barber.id, 0)
    assert hours is not None
    rows = await bookings_of_barber(sessions, barber.id)
    assert len(rows) == (1 if isinstance(booking_result, Booking) else 0)
    for row in rows:
        local = row.starts_at.astimezone(MOSCOW)
        assert local.hour >= hours.start_time.hour
        assert row.ends_at.astimezone(MOSCOW) <= at(
            hours.end_time.hour, hours.end_time.minute
        )


@pytest.mark.asyncio
async def test_mixed_parallel_operations_complete_without_deadlock(
    sessions: Any,
    factory: Any,
    admin: AdminService,
) -> None:
    """Одинаковый порядок блокировок: мастер → услуга, без циклических ожиданий."""
    first_barber = await factory.barber()
    second_barber = await factory.barber()
    service = await factory.service()
    first_client = BookingService(sessions, clock=lambda: at(8))
    second_client = BookingService(sessions, clock=lambda: at(8))

    results = await asyncio.wait_for(
        asyncio.gather(
            first_client.create_booking(
                telegram_id=factory.telegram_id(),
                barber_id=first_barber.id,
                service_id=service.id,
                starts_at=at(9),
            ),
            second_client.create_booking(
                telegram_id=factory.telegram_id(),
                barber_id=second_barber.id,
                service_id=service.id,
                starts_at=at(9),
            ),
            admin.update_service(
                actor_telegram_id=ADMIN_ID, service_id=service.id, price_rub=900
            ),
            admin.set_working_hours(
                actor_telegram_id=ADMIN_ID,
                barber_id=first_barber.id,
                weekday=1,
                start_time=time(10, 0),
                end_time=time(15, 0),
            ),
            return_exceptions=True,
        ),
        timeout=20,
    )

    assert not [item for item in results if isinstance(item, BaseException)], results
    assert await booking_ids_of_barber(sessions, first_barber.id) == [results[0].id]
    assert await booking_ids_of_barber(sessions, second_barber.id) == [results[1].id]
