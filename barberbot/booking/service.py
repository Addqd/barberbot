"""Движок бронирования, независимый от Telegram.

Сервис объединяет доменные правила (шаг 30 минут, рабочие часы, отсутствия,
занятость, срок отмены) с доступом к данным. Каждая операция получает
собственную ``AsyncSession``; записи выполняются в явной транзакции.

Защита от пересекающихся записей обеспечивается PostgreSQL exclusion
constraint ``ex_bookings_barber_no_overlap``: при SQLSTATE ``23P01`` транзакция
откатывается, а вызывающий код получает доменный ``SlotUnavailable``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from barberbot.booking.errors import (
    BarberUnavailable,
    BookingAlreadyCancelled,
    BookingError,
    BookingNotCancellable,
    BookingNotFound,
    CancellationTooLate,
    DatabaseUnavailable,
    InvalidBookingTime,
    NotBookingOwner,
    ServiceUnavailable,
    SlotUnavailable,
)
from barberbot.booking.slots import (
    CANCELLATION_DEADLINE,
    MOSCOW,
    SLOT_STEP,
    Interval,
    SlotIssue,
    day_window,
    generate_slots,
    start_issue,
)
from barberbot.db.models import Barber, Booking, BookingStatus, Service, User
from barberbot.db.repositories import (
    BookingRepository,
    CatalogRepository,
    ScheduleRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)

#: SQLSTATE нарушения exclusion constraint PostgreSQL.
EXCLUSION_VIOLATION = "23P01"

#: Горизонт выдачи доступных дат по умолчанию.
DEFAULT_HORIZON_DAYS = 30

MESSAGE_SERVICE_UNAVAILABLE = "Услуга недоступна для записи."
MESSAGE_BARBER_UNAVAILABLE = "Мастер недоступен для записи."
MESSAGE_NOT_FOUND = "Запись не найдена."
MESSAGE_PAST = "Нельзя записаться на прошедшее время."
MESSAGE_OUTSIDE_HOURS = "Выбранное время вне рабочего графика мастера."
MESSAGE_OFF_GRID = "Выберите время начала с шагом 30 минут."
MESSAGE_DOES_NOT_FIT = "Услуга не помещается в рабочее время мастера."
MESSAGE_INVALID_TIME = "Некорректное время начала записи."
MESSAGE_SLOT_TAKEN = "Это время уже занято. Выберите другое."
MESSAGE_ALREADY_CANCELLED = "Запись уже отменена."
MESSAGE_NOT_CANCELLABLE = "Эту запись нельзя отменить."
MESSAGE_NOT_OWNER = "Можно отменять только свои записи."
MESSAGE_TOO_LATE = "Отмена возможна не позднее чем за 2 часа до начала."
MESSAGE_DATABASE = "Сервис записи временно недоступен. Попробуйте позже."

_ISSUE_MESSAGES: dict[SlotIssue, str] = {
    SlotIssue.PAST: MESSAGE_PAST,
    SlotIssue.OUTSIDE_WORKING_HOURS: MESSAGE_OUTSIDE_HOURS,
    SlotIssue.OFF_GRID: MESSAGE_OFF_GRID,
    SlotIssue.DOES_NOT_FIT: MESSAGE_DOES_NOT_FIT,
}


@dataclass(frozen=True, slots=True)
class _DayAvailability:
    """Рабочее окно дня, занятые интервалы и свободные времена начала."""

    window: Interval | None
    busy: tuple[Interval, ...]
    slots: tuple[datetime, ...]


def _sqlstate(error: IntegrityError) -> str | None:
    """SQLSTATE исходной ошибки psycopg, если он доступен."""
    return getattr(error.orig, "sqlstate", None)


class BookingService:
    """Операции записи: слоты, создание, список и отмена."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
        timezone: ZoneInfo = MOSCOW,
        horizon_days: int = DEFAULT_HORIZON_DAYS,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tz = timezone
        self._horizon_days = horizon_days

    # ------------------------------------------------------------------ #
    # Публичные операции
    # ------------------------------------------------------------------ #

    async def available_dates(
        self,
        *,
        service_id: int,
        barber_id: int,
        start_date: date | None = None,
        days: int | None = None,
    ) -> list[date]:
        """Даты, на которые есть хотя бы одно свободное время начала."""
        now = self._now()
        first_day = start_date or now.astimezone(self._tz).date()
        total_days = self._horizon_days if days is None else days
        if total_days <= 0:
            raise ValueError("Количество дней должно быть положительным")
        requested = [first_day + timedelta(days=offset) for offset in range(total_days)]

        async with self._operation() as session:
            service = await self._require_service(session, service_id)
            barber = await self._require_barber(session, barber_id)
            availability = await self._availability(
                session, service=service, barber=barber, days=requested, now=now
            )
        return [day for day in requested if availability[day].slots]

    async def available_slots(
        self, *, service_id: int, barber_id: int, on_date: date
    ) -> list[datetime]:
        """Свободные времена начала в конкретный день (часовой пояс Москвы)."""
        now = self._now()
        async with self._operation() as session:
            service = await self._require_service(session, service_id)
            barber = await self._require_barber(session, barber_id)
            availability = await self._availability(
                session, service=service, barber=barber, days=[on_date], now=now
            )
        return list(availability[on_date].slots)

    async def create_booking(
        self,
        *,
        telegram_id: int,
        barber_id: int,
        service_id: int,
        starts_at: datetime,
        display_name: str | None = None,
    ) -> Booking:
        """Создать запись и сохранить снимок цены и длительности услуги."""
        if starts_at.tzinfo is None:
            raise InvalidBookingTime(MESSAGE_INVALID_TIME)
        now = self._now()
        local_day = starts_at.astimezone(self._tz).date()

        # Сначала проверяем услугу, мастера и время: для недопустимого запроса
        # ничего не пишется в базу.
        async with self._operation() as session:
            service = await self._require_service(session, service_id)
            barber = await self._require_barber(session, barber_id)
            availability = await self._availability(
                session, service=service, barber=barber, days=[local_day], now=now
            )
            duration = timedelta(minutes=service.duration_minutes)
            self._validate_start(
                starts_at=starts_at,
                duration=duration,
                day_state=availability[local_day],
                now=now,
            )
            barber_pk = barber.id
            service_pk = service.id
            price_rub = service.price_rub
            duration_minutes = service.duration_minutes

        user = await self._ensure_user(telegram_id, display_name)

        async with self._operation() as session:
            repository = BookingRepository(session)
            try:
                async with session.begin():
                    created = await repository.create(
                        user_id=user.id,
                        barber_id=barber_pk,
                        service_id=service_pk,
                        starts_at=starts_at,
                        ends_at=starts_at + duration,
                        price_rub=price_rub,
                        duration_minutes=duration_minutes,
                    )
            except IntegrityError as error:
                # Гонка двух запросов на один слот: окончательное решение
                # принимает exclusion constraint PostgreSQL.
                if _sqlstate(error) == EXCLUSION_VIOLATION:
                    raise SlotUnavailable(MESSAGE_SLOT_TAKEN) from None
                raise DatabaseUnavailable(MESSAGE_DATABASE) from None

            booking = await repository.get_with_details(created.id)
            if booking is None:  # pragma: no cover - защита от невозможного состояния
                raise DatabaseUnavailable(MESSAGE_DATABASE)
            return booking

    async def list_user_bookings(
        self, telegram_id: int, *, include_cancelled: bool = True
    ) -> list[Booking]:
        """Записи пользователя, сначала ближайшие по времени начала."""
        async with self._operation() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                return []
            bookings = await BookingRepository(session).list_for_user(
                user.id, include_cancelled=include_cancelled
            )
        return list(bookings)

    async def cancel_booking(self, *, telegram_id: int, booking_id: int) -> Booking:
        """Отменить собственную запись не позднее чем за 2 часа до начала."""
        now = self._now()
        async with self._operation() as session:
            repository = BookingRepository(session)
            try:
                async with session.begin():
                    user = await UserRepository(session).get_by_telegram_id(telegram_id)
                    if user is None:
                        raise BookingNotFound(MESSAGE_NOT_FOUND)
                    booking = await repository.get_for_update(booking_id)
                    if booking is None:
                        raise BookingNotFound(MESSAGE_NOT_FOUND)
                    if booking.user_id != user.id:
                        raise NotBookingOwner(MESSAGE_NOT_OWNER)
                    if booking.status == BookingStatus.CANCELLED:
                        raise BookingAlreadyCancelled(MESSAGE_ALREADY_CANCELLED)
                    if booking.status == BookingStatus.COMPLETED:
                        raise BookingNotCancellable(MESSAGE_NOT_CANCELLABLE)
                    if now > booking.starts_at - CANCELLATION_DEADLINE:
                        raise CancellationTooLate(MESSAGE_TOO_LATE)
                    await repository.mark_cancelled(booking, cancelled_at=now)
            except IntegrityError:
                raise DatabaseUnavailable(MESSAGE_DATABASE) from None

            cancelled = await repository.get_with_details(booking_id)
            if cancelled is None:  # pragma: no cover
                raise BookingNotFound(MESSAGE_NOT_FOUND)
            return cancelled

    # ------------------------------------------------------------------ #
    # Внутренние помощники
    # ------------------------------------------------------------------ #

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("Часы сервиса должны возвращать timezone-aware datetime")
        return now

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[AsyncSession]:
        """Сессия на одну операцию с преобразованием ошибок БД в доменные."""
        try:
            async with self._sessions() as session:
                yield session
        except BookingError:
            raise
        except SQLAlchemyError as error:
            # Ни текст SQL, ни параметры, ни DSN не попадают ни в лог, ни в
            # сообщение пользователю.
            logger.warning(
                "Ошибка базы данных при операции бронирования (%s)",
                type(error).__name__,
            )
            raise DatabaseUnavailable(MESSAGE_DATABASE) from None

    async def _ensure_user(self, telegram_id: int, display_name: str | None) -> User:
        async with self._operation() as session:
            try:
                async with session.begin():
                    user = await UserRepository(session).get_or_create(
                        telegram_id, display_name
                    )
            except IntegrityError:
                raise DatabaseUnavailable(MESSAGE_DATABASE) from None
            return user

    async def _require_service(self, session: AsyncSession, service_id: int) -> Service:
        service = await CatalogRepository(session).get_service(service_id)
        if service is None or not service.is_active:
            raise ServiceUnavailable(MESSAGE_SERVICE_UNAVAILABLE)
        return service

    async def _require_barber(self, session: AsyncSession, barber_id: int) -> Barber:
        barber = await CatalogRepository(session).get_barber(barber_id)
        if barber is None or not barber.is_active:
            raise BarberUnavailable(MESSAGE_BARBER_UNAVAILABLE)
        return barber

    async def _availability(
        self,
        session: AsyncSession,
        *,
        service: Service,
        barber: Barber,
        days: Sequence[date],
        now: datetime,
    ) -> dict[date, _DayAvailability]:
        """Свободные слоты и занятость для набора дней (3 запроса на диапазон)."""
        if not days:
            return {}
        tz = self._tz
        duration = timedelta(minutes=service.duration_minutes)
        range_start = datetime.combine(min(days), time(0, 0), tzinfo=tz)
        range_end = datetime.combine(
            max(days) + timedelta(days=1), time(0, 0), tzinfo=tz
        )

        schedule = ScheduleRepository(session)
        hours = {
            row.weekday: row for row in await schedule.list_working_hours(barber.id)
        }
        time_off = await schedule.list_time_off(
            barber.id, window_start=range_start, window_end=range_end
        )
        bookings = await BookingRepository(session).list_active_between(
            barber.id, window_start=range_start, window_end=range_end
        )
        busy = tuple(
            [Interval(row.starts_at, row.ends_at) for row in bookings]
            + [Interval(row.starts_at, row.ends_at) for row in time_off]
        )

        availability: dict[date, _DayAvailability] = {}
        for day in days:
            working_hours = hours.get(day.weekday())
            if working_hours is None:
                availability[day] = _DayAvailability(window=None, busy=busy, slots=())
                continue
            window = day_window(
                day,
                working_hours.start_time,
                working_hours.end_time,
                tz=tz,
            )
            availability[day] = _DayAvailability(
                window=window,
                busy=busy,
                slots=tuple(
                    generate_slots(
                        window=window,
                        duration=duration,
                        now=now,
                        busy=busy,
                        step=SLOT_STEP,
                    )
                ),
            )
        return availability

    def _validate_start(
        self,
        *,
        starts_at: datetime,
        duration: timedelta,
        day_state: _DayAvailability,
        now: datetime,
    ) -> None:
        if day_state.window is None:
            raise InvalidBookingTime(MESSAGE_OUTSIDE_HOURS)
        issue = start_issue(
            starts_at=starts_at,
            window=day_state.window,
            duration=duration,
            now=now,
            step=SLOT_STEP,
            tz=self._tz,
        )
        if issue is not None:
            raise InvalidBookingTime(_ISSUE_MESSAGES[issue])
        if any(
            interval.overlaps(starts_at, starts_at + duration)
            for interval in day_state.busy
        ):
            raise SlotUnavailable(MESSAGE_SLOT_TAKEN)


__all__ = [
    "DEFAULT_HORIZON_DAYS",
    "EXCLUSION_VIOLATION",
    "BookingService",
]
