"""Регрессионные тесты автоматического перевода записей в ``completed``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any

import pytest
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from barberbot import app
from barberbot.app import build_dispatcher
from barberbot.booking.completion import CompletionScheduler
from barberbot.booking.errors import DatabaseUnavailable
from barberbot.booking.service import MESSAGE_DATABASE, BookingService
from barberbot.db.models import Booking, BookingStatus
from barberbot.db_settings import database_url, get_settings

from .conftest import FIXED_NOW
from .fakes import FakeBookingService


async def statuses_of(
    database: Any, booking_ids: Sequence[int]
) -> dict[int, BookingStatus]:
    """Фактические статусы записей, прочитанные из PostgreSQL заново."""
    async with database.sessions() as session:
        rows = await session.execute(
            select(Booking.id, Booking.status).where(Booking.id.in_(booking_ids))
        )
        return {booking_id: status for booking_id, status in rows.all()}


@pytest.mark.asyncio
async def test_finished_booking_becomes_completed(
    booking_service: BookingService, factory: Any, database: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    finished = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(hours=2),
    )

    completed = await booking_service.complete_finished_bookings()

    assert completed == 1
    assert (await statuses_of(database, [finished.id]))[
        finished.id
    ] == BookingStatus.COMPLETED


@pytest.mark.asyncio
async def test_booking_ending_exactly_now_is_completed(
    booking_service: BookingService, factory: Any, database: Any
) -> None:
    """Граница включительная: ``ends_at == now`` уже считается завершением."""
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    boundary = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(minutes=60),
        duration=60,
    )

    assert await booking_service.complete_finished_bookings() == 1
    assert (await statuses_of(database, [boundary.id]))[
        boundary.id
    ] == BookingStatus.COMPLETED


@pytest.mark.asyncio
async def test_running_and_future_bookings_are_untouched(
    booking_service: BookingService, factory: Any, database: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    running = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(minutes=30),
        duration=60,
    )
    future = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW + timedelta(hours=1),
        duration=60,
    )

    assert await booking_service.complete_finished_bookings() == 0
    assert await statuses_of(database, [running.id, future.id]) == {
        running.id: BookingStatus.CONFIRMED,
        future.id: BookingStatus.CONFIRMED,
    }


@pytest.mark.asyncio
async def test_cancelled_and_completed_bookings_are_untouched(
    booking_service: BookingService, factory: Any, database: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    cancelled = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(days=1),
        status=BookingStatus.CANCELLED,
    )
    already_completed = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(days=2),
        status=BookingStatus.COMPLETED,
    )

    assert await booking_service.complete_finished_bookings() == 0
    assert await statuses_of(database, [cancelled.id, already_completed.id]) == {
        cancelled.id: BookingStatus.CANCELLED,
        already_completed.id: BookingStatus.COMPLETED,
    }


@pytest.mark.asyncio
async def test_restart_completes_finished_bookings_idempotently(
    booking_service: BookingService, factory: Any, database: Any
) -> None:
    """Первый проход после запуска догоняет всё, повторный ничего не меняет."""
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    first = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(days=1),
    )

    assert await booking_service.complete_finished_bookings() == 1
    # Повторный запуск («перезапуск процесса») не находит работы.
    assert await booking_service.complete_finished_bookings() == 0

    second = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(days=2),
    )
    assert await booking_service.complete_finished_bookings() == 1
    assert await statuses_of(database, [first.id, second.id]) == {
        first.id: BookingStatus.COMPLETED,
        second.id: BookingStatus.COMPLETED,
    }


@pytest.mark.asyncio
async def test_concurrent_completion_runs_update_each_booking_once(
    booking_service: BookingService, factory: Any, database: Any
) -> None:
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    finished = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(hours=3),
    )

    results = await asyncio.gather(
        booking_service.complete_finished_bookings(),
        booking_service.complete_finished_bookings(),
    )

    assert sorted(results) == [0, 1]
    assert (await statuses_of(database, [finished.id]))[
        finished.id
    ] == BookingStatus.COMPLETED


@pytest.mark.asyncio
async def test_completion_database_error_is_a_domain_error() -> None:
    """Реальная ошибка PostgreSQL не раскрывает внутренние детали."""
    settings = get_settings()
    missing_url = database_url(settings, target="test").set(
        database="barberbot_missing_for_completion_tests"
    )
    engine = create_async_engine(missing_url, connect_args={"connect_timeout": 5})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = BookingService(sessions)
    try:
        with pytest.raises(DatabaseUnavailable) as error_info:
            await service.complete_finished_bookings()
    finally:
        await engine.dispose()

    assert str(error_info.value) == MESSAGE_DATABASE
    assert error_info.value.__cause__ is None


class RecordingCompletionService:
    """Сервис-заглушка для тестов планировщика: без базы данных."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def complete_finished_bookings(self) -> int:
        self.calls += 1
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        return 0


async def wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("Планировщик не выполнил задачу по интервалу")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_start_updates_statuses_before_first_interval() -> None:
    service = RecordingCompletionService()
    scheduler = CompletionScheduler(service, interval=timedelta(hours=1))  # type: ignore[arg-type]
    try:
        await scheduler.start()

        assert service.calls == 1
        assert scheduler.running is True
    finally:
        scheduler.shutdown()


@pytest.mark.asyncio
async def test_scheduler_repeats_completion_without_user_actions() -> None:
    service = RecordingCompletionService()
    scheduler = CompletionScheduler(
        service,
        interval=timedelta(milliseconds=50),  # type: ignore[arg-type]
    )
    try:
        await scheduler.start()
        await wait_until(lambda: service.calls >= 3)
    finally:
        scheduler.shutdown()
        await asyncio.sleep(0.1)

    assert scheduler.running is False
    stopped_calls = service.calls
    await asyncio.sleep(0.15)
    assert service.calls == stopped_calls


@pytest.mark.asyncio
async def test_database_error_does_not_stop_scheduled_attempts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = RecordingCompletionService(error=DatabaseUnavailable(MESSAGE_DATABASE))
    scheduler = CompletionScheduler(
        service,
        interval=timedelta(milliseconds=50),  # type: ignore[arg-type]
    )
    try:
        with caplog.at_level(logging.WARNING, logger="barberbot.booking.completion"):
            await scheduler.start()
            # Первый проход упал, но планировщик запустился и повторил попытку.
            await wait_until(lambda: service.calls >= 2)
    finally:
        scheduler.shutdown()

    assert "Не удалось обновить статусы записей" in caplog.text
    assert MESSAGE_DATABASE in caplog.text


class RecordingScheduler:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.stopped = True


def test_shutdown_without_start_is_safe() -> None:
    scheduler = CompletionScheduler(RecordingCompletionService())  # type: ignore[arg-type]

    scheduler.shutdown()

    assert scheduler.running is False


@pytest.mark.asyncio
async def test_startup_and_shutdown_manage_completion_scheduler(bot: Bot) -> None:
    scheduler = RecordingScheduler()

    await app.on_startup(bot, scheduler)  # type: ignore[arg-type]
    await app.on_shutdown(bot, scheduler)  # type: ignore[arg-type]

    assert scheduler.started is True
    assert scheduler.stopped is True


def test_dispatcher_exposes_idle_completion_scheduler() -> None:
    dispatcher = build_dispatcher(FakeBookingService())  # type: ignore[arg-type]

    scheduler = dispatcher["completion_scheduler"]

    assert isinstance(scheduler, CompletionScheduler)
    assert scheduler.running is False


@pytest.mark.asyncio
async def test_dispatcher_lifecycle_runs_real_scheduler(
    booking_service: BookingService,
    factory: Any,
    database: Any,
    bot: Bot,
) -> None:
    """Те же startup/shutdown-хуки, что вызывает start_polling, без сети."""
    user = await factory.user()
    barber = await factory.barber()
    service = await factory.service()
    finished = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=FIXED_NOW - timedelta(hours=2),
    )
    dispatcher = build_dispatcher(booking_service)
    scheduler = dispatcher["completion_scheduler"]
    workflow_data = {**dispatcher.workflow_data, "dispatcher": dispatcher}
    try:
        await dispatcher.emit_startup(bot=bot, **workflow_data)

        assert isinstance(scheduler, CompletionScheduler)
        assert scheduler.running is True
        assert (await statuses_of(database, [finished.id]))[
            finished.id
        ] == BookingStatus.COMPLETED
    finally:
        await dispatcher.emit_shutdown(bot=bot, **workflow_data)

    await wait_until(lambda: not scheduler.running)
