"""Административные операции: права, runtime-валидация и транзакции.

Каждый публичный метод сервиса:

* заново проверяет права по Telegram ID, полученному от Telegram
  (никогда — по данным callback или FSM);
* валидирует входные данные на runtime, не полагаясь на подсказки типов;
* выполняет запись в одной транзакции и переводит ошибки БД в доменные
  сообщения без SQL, DSN и прочих внутренних подробностей.

Правила клиентского бронирования не дублируются: административная отмена
меняет только статус существующей записи, а правки расписания и периодов
отсутствия отклоняются, если делают будущие подтверждённые записи
недействительными.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from barberbot.admin import texts
from barberbot.admin.errors import (
    AdminAccessDenied,
    AdminBookingState,
    AdminConflict,
    AdminDatabaseUnavailable,
    AdminError,
    AdminNotFound,
    AdminValidationError,
)
from barberbot.booking.slots import MOSCOW
from barberbot.db.models import (
    Barber,
    BarberTimeOff,
    BarberWorkingHours,
    Booking,
    BookingStatus,
    Service,
)
from barberbot.db.repositories import (
    BookingRepository,
    CatalogRepository,
    ScheduleRepository,
)

logger = logging.getLogger(__name__)

#: Количество строк на странице списков админ-панели.
PAGE_SIZE = 5

MAX_SERVICE_NAME = 160
MAX_BARBER_NAME = 120
MAX_PRICE_RUB = 2**31 - 1
MIN_DURATION_MINUTES = 1
MAX_DURATION_MINUTES = 60

_WEEKDAYS = range(7)
_NO_WORK_PHRASES = frozenset({"выходной", "выходной день"})
_HOURS_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})[-–—](\d{1,2}):(\d{2})$")
_PERIOD_SEPARATOR = re.compile(r"\s*[-–—]\s*")
_DATE_FORMAT = "%d.%m.%Y"


# --------------------------------------------------------------------------- #
# Постраничная выдача
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Page:
    """Номер страницы (с нуля), всего страниц, смещение и общее число строк."""

    number: int
    pages: int
    offset: int
    total: int


def paginate(total: int, page: int, *, page_size: int = PAGE_SIZE) -> Page:
    """Ограничить запрошенную страницу реальным диапазоном."""
    pages = max(1, ceil(total / page_size))
    current = min(max(page, 0), pages - 1)
    return Page(number=current, pages=pages, offset=current * page_size, total=total)


@dataclass(frozen=True, slots=True)
class ServicesPage:
    rows: list[Service]
    total: int
    active: int
    page: Page


@dataclass(frozen=True, slots=True)
class BarbersPage:
    rows: list[Barber]
    working_days: dict[int, int]
    total: int
    active: int
    page: Page


@dataclass(frozen=True, slots=True)
class TimeOffPage:
    barber: Barber
    rows: list[BarberTimeOff]
    total: int
    page: Page


@dataclass(frozen=True, slots=True)
class BarberView:
    barber: Barber
    hours: dict[int, BarberWorkingHours]
    time_off: list[BarberTimeOff]


@dataclass(frozen=True, slots=True)
class BookingsPage:
    rows: list[Booking]
    page: Page


# --------------------------------------------------------------------------- #
# Разбор и проверка пользовательского ввода
# --------------------------------------------------------------------------- #


def parse_service_name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > MAX_SERVICE_NAME:
        raise AdminValidationError(texts.INVALID_NAME.format(limit=MAX_SERVICE_NAME))
    return name


def parse_barber_name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > MAX_BARBER_NAME:
        raise AdminValidationError(texts.INVALID_NAME.format(limit=MAX_BARBER_NAME))
    return name


def check_price_rub(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdminValidationError(texts.INVALID_PRICE)
    if value < 0 or value > MAX_PRICE_RUB:
        raise AdminValidationError(texts.INVALID_PRICE)
    return value


def check_duration_minutes(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdminValidationError(texts.INVALID_DURATION)
    if not MIN_DURATION_MINUTES <= value <= MAX_DURATION_MINUTES:
        raise AdminValidationError(texts.INVALID_DURATION)
    return value


def check_weekday(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in _WEEKDAYS:
        raise AdminValidationError(texts.NOT_FOUND)
    return value


def parse_price(value: str) -> int:
    text = value.strip().replace(" ", "").replace("₽", "")
    if not text.isascii() or not text.isdigit():
        raise AdminValidationError(texts.INVALID_PRICE)
    return check_price_rub(int(text))


def parse_duration(value: str) -> int:
    text = value.strip()
    if not text.isascii() or not text.isdigit():
        raise AdminValidationError(texts.INVALID_DURATION)
    return check_duration_minutes(int(text))


def parse_day(value: str) -> date:
    text = value.strip()
    try:
        return datetime.strptime(text, _DATE_FORMAT).date()
    except ValueError:
        raise AdminValidationError(texts.INVALID_DATE) from None


def parse_working_hours(value: str) -> tuple[time, time] | None:
    """Разобрать часы дня: ``None`` означает «выходной»."""
    text = value.strip()
    if " ".join(text.casefold().split()) in _NO_WORK_PHRASES:
        return None

    match = _HOURS_PATTERN.match(text.replace(" ", ""))
    if match is None:
        raise AdminValidationError(texts.INVALID_HOURS)
    start_hour, start_minute, end_hour, end_minute = (
        int(item) for item in match.groups()
    )
    if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
        raise AdminValidationError(texts.INVALID_HOURS)
    start = time(hour=start_hour, minute=start_minute)
    end = time(hour=end_hour, minute=end_minute)
    if start >= end:
        raise AdminValidationError(texts.INVALID_HOURS)
    return start, end


def parse_period(value: str, *, tz: ZoneInfo = MOSCOW) -> tuple[datetime, datetime]:
    """Разобрать «ДД.ММ.ГГГГ» или «ДД.ММ.ГГГГ-ДД.ММ.ГГГГ» в интервал по Москве."""
    parts = _PERIOD_SEPARATOR.split(value.strip())
    if any(not part.strip() for part in parts):
        raise AdminValidationError(texts.INVALID_PERIOD)
    if len(parts) == 1:
        first_day = parse_day(parts[0])
        last_day = first_day
    elif len(parts) == 2:
        first_day = parse_day(parts[0])
        last_day = parse_day(parts[1])
        if last_day < first_day:
            raise AdminValidationError(texts.INVALID_PERIOD)
    else:
        raise AdminValidationError(texts.INVALID_PERIOD)

    starts_at = datetime.combine(first_day, time(0, 0), tzinfo=tz)
    ends_at = datetime.combine(last_day, time(0, 0), tzinfo=tz) + timedelta(days=1)
    return starts_at, ends_at


# --------------------------------------------------------------------------- #
# Сервис
# --------------------------------------------------------------------------- #


class AdminService:
    """Административные операции поверх существующих моделей и репозиториев."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        admin_ids: frozenset[int],
        clock: Callable[[], datetime] | None = None,
        timezone: ZoneInfo = MOSCOW,
    ) -> None:
        self._sessions = sessions
        self._admin_ids = frozenset(admin_ids)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tz = timezone

    # ------------------------------------------------------------------ #
    # Права
    # ------------------------------------------------------------------ #

    @property
    def admin_ids(self) -> frozenset[int]:
        """Единственный источник истины о том, кто является администратором."""
        return self._admin_ids

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self._admin_ids

    def _authorize(self, actor_telegram_id: int) -> None:
        if not self.is_admin(actor_telegram_id):
            logger.warning(
                "Отклонено административное действие: нет прав (id=%s)",
                actor_telegram_id,
            )
            raise AdminAccessDenied(texts.ACCESS_DENIED)

    # ------------------------------------------------------------------ #
    # Услуги
    # ------------------------------------------------------------------ #

    async def list_services(
        self, *, actor_telegram_id: int, page: int = 0
    ) -> ServicesPage:
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            services = list(await CatalogRepository(session).list_services())
        info = paginate(len(services), page)
        return ServicesPage(
            rows=services[info.offset : info.offset + PAGE_SIZE],
            total=info.total,
            active=sum(1 for service in services if service.is_active),
            page=info,
        )

    async def get_service(self, *, actor_telegram_id: int, service_id: int) -> Service:
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            service = await CatalogRepository(session).get_service(service_id)
        if service is None:
            raise AdminNotFound(texts.NOT_FOUND)
        return service

    async def create_service(
        self,
        *,
        actor_telegram_id: int,
        name: str,
        price_rub: int,
        duration_minutes: int,
    ) -> Service:
        self._authorize(actor_telegram_id)
        clean_name = parse_service_name(name)
        price = check_price_rub(price_rub)
        duration = check_duration_minutes(duration_minutes)
        async with self._operation() as session:
            repository = CatalogRepository(session)
            try:
                async with session.begin():
                    if await repository.get_service_by_name(clean_name) is not None:
                        raise AdminValidationError(texts.SERVICE_NAME_TAKEN)
                    service = await repository.create_service(
                        name=clean_name,
                        price_rub=price,
                        duration_minutes=duration,
                    )
            except IntegrityError:
                raise AdminValidationError(texts.SERVICE_NAME_TAKEN) from None
            return service

    async def update_service(
        self,
        *,
        actor_telegram_id: int,
        service_id: int,
        name: str | None = None,
        price_rub: int | None = None,
        duration_minutes: int | None = None,
    ) -> Service:
        self._authorize(actor_telegram_id)
        clean_name = parse_service_name(name) if name is not None else None
        price = check_price_rub(price_rub) if price_rub is not None else None
        duration = (
            check_duration_minutes(duration_minutes)
            if duration_minutes is not None
            else None
        )
        if clean_name is None and price is None and duration is None:
            raise AdminValidationError(texts.NOT_FOUND)

        async with self._operation() as session:
            repository = CatalogRepository(session)
            try:
                async with session.begin():
                    service = await repository.get_service_for_update(service_id)
                    if service is None:
                        raise AdminNotFound(texts.NOT_FOUND)
                    if clean_name is not None and clean_name != service.name:
                        if await repository.get_service_by_name(clean_name) is not None:
                            raise AdminValidationError(texts.SERVICE_NAME_TAKEN)
                        service.name = clean_name
                    if price is not None:
                        service.price_rub = price
                    if duration is not None:
                        service.duration_minutes = duration
                    await session.flush()
            except IntegrityError:
                raise AdminValidationError(texts.SERVICE_NAME_TAKEN) from None
            return service

    async def toggle_service(
        self, *, actor_telegram_id: int, service_id: int
    ) -> Service:
        """Переключить услугу атомарно: статус читается под блокировкой строки."""
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            repository = CatalogRepository(session)
            async with session.begin():
                service = await repository.get_service_for_update(service_id)
                if service is None:
                    raise AdminNotFound(texts.NOT_FOUND)
                service.is_active = not service.is_active
                await session.flush()
            return service

    # ------------------------------------------------------------------ #
    # Барберы
    # ------------------------------------------------------------------ #

    async def list_barbers(
        self, *, actor_telegram_id: int, page: int = 0
    ) -> BarbersPage:
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            barbers = list(await CatalogRepository(session).list_barbers())
            hours = await ScheduleRepository(session).list_hours_for_barbers(
                [barber.id for barber in barbers]
            )
        working_days: dict[int, int] = {}
        for row in hours:
            working_days[row.barber_id] = working_days.get(row.barber_id, 0) + 1
        info = paginate(len(barbers), page)
        return BarbersPage(
            rows=barbers[info.offset : info.offset + PAGE_SIZE],
            working_days=working_days,
            total=info.total,
            active=sum(1 for barber in barbers if barber.is_active),
            page=info,
        )

    async def list_all_barbers(self, *, actor_telegram_id: int) -> list[Barber]:
        """Все мастера без пагинации: нужны для выбора фильтра."""
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            return list(await CatalogRepository(session).list_barbers())

    async def get_barber(self, *, actor_telegram_id: int, barber_id: int) -> BarberView:
        """Карточка мастера: профиль, недельный график и отсутствия."""
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            barber = await CatalogRepository(session).get_barber(barber_id)
            if barber is None:
                raise AdminNotFound(texts.NOT_FOUND)
            schedule = ScheduleRepository(session)
            hours = await schedule.list_working_hours(barber.id)
            time_off = await schedule.list_all_time_off(barber.id)
        return BarberView(
            barber=barber,
            hours={row.weekday: row for row in hours},
            time_off=list(time_off),
        )

    async def create_barber(self, *, actor_telegram_id: int, name: str) -> Barber:
        self._authorize(actor_telegram_id)
        clean_name = parse_barber_name(name)
        async with self._operation() as session:
            repository = CatalogRepository(session)
            try:
                async with session.begin():
                    if await repository.get_barber_by_name(clean_name) is not None:
                        raise AdminValidationError(texts.BARBER_NAME_TAKEN)
                    # Новый мастер добавляется отключённым: без расписания он
                    # не должен появляться в клиентском списке.
                    barber = await repository.create_barber(
                        name=clean_name, is_active=False
                    )
            except IntegrityError:
                raise AdminValidationError(texts.BARBER_NAME_TAKEN) from None
            return barber

    async def toggle_barber(self, *, actor_telegram_id: int, barber_id: int) -> Barber:
        """Переключить мастера атомарно: статус читается под блокировкой строки."""
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            repository = CatalogRepository(session)
            async with session.begin():
                barber = await repository.get_barber_for_update(barber_id)
                if barber is None:
                    raise AdminNotFound(texts.NOT_FOUND)
                barber.is_active = not barber.is_active
                await session.flush()
            return barber

    # ------------------------------------------------------------------ #
    # Расписание и отсутствия
    # ------------------------------------------------------------------ #

    async def set_working_hours(
        self,
        *,
        actor_telegram_id: int,
        barber_id: int,
        weekday: int,
        start_time: time,
        end_time: time,
    ) -> BarberWorkingHours:
        self._authorize(actor_telegram_id)
        day_of_week = check_weekday(weekday)
        if start_time >= end_time:
            raise AdminValidationError(texts.INVALID_HOURS)
        now = self._now()

        async with self._operation() as session:
            repository = CatalogRepository(session)
            bookings = BookingRepository(session)
            schedule = ScheduleRepository(session)
            async with session.begin():
                barber = await repository.get_barber_for_update(barber_id)
                if barber is None:
                    raise AdminNotFound(texts.NOT_FOUND)
                conflicts = await self._weekday_conflicts(
                    bookings,
                    barber=barber,
                    weekday=day_of_week,
                    window=(start_time, end_time),
                    now=now,
                )
                if conflicts:
                    raise AdminConflict(
                        texts.schedule_conflict_text(barber.name, conflicts)
                    )
                return await schedule.set_working_hours(
                    barber_id=barber.id,
                    weekday=day_of_week,
                    start_time=start_time,
                    end_time=end_time,
                )

    async def clear_working_hours(
        self, *, actor_telegram_id: int, barber_id: int, weekday: int
    ) -> None:
        self._authorize(actor_telegram_id)
        day_of_week = check_weekday(weekday)
        now = self._now()

        async with self._operation() as session:
            repository = CatalogRepository(session)
            bookings = BookingRepository(session)
            schedule = ScheduleRepository(session)
            async with session.begin():
                barber = await repository.get_barber_for_update(barber_id)
                if barber is None:
                    raise AdminNotFound(texts.NOT_FOUND)
                conflicts = await self._weekday_conflicts(
                    bookings,
                    barber=barber,
                    weekday=day_of_week,
                    window=None,
                    now=now,
                )
                if conflicts:
                    raise AdminConflict(
                        texts.schedule_conflict_text(barber.name, conflicts)
                    )
                await schedule.delete_working_hours(barber.id, day_of_week)

    async def list_time_off(
        self,
        *,
        actor_telegram_id: int,
        barber_id: int,
        page: int = 0,
    ) -> TimeOffPage:
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            barber = await CatalogRepository(session).get_barber(barber_id)
            if barber is None:
                raise AdminNotFound(texts.NOT_FOUND)
            rows = list(await ScheduleRepository(session).list_all_time_off(barber.id))
        info = paginate(len(rows), page)
        return TimeOffPage(
            barber=barber,
            rows=rows[info.offset : info.offset + PAGE_SIZE],
            total=info.total,
            page=info,
        )

    async def add_time_off(
        self,
        *,
        actor_telegram_id: int,
        barber_id: int,
        starts_at: datetime,
        ends_at: datetime,
    ) -> BarberTimeOff:
        self._authorize(actor_telegram_id)
        if starts_at.tzinfo is None or ends_at.tzinfo is None:
            raise AdminValidationError(texts.INVALID_PERIOD)
        if starts_at >= ends_at:
            raise AdminValidationError(texts.INVALID_PERIOD)
        now = self._now()
        if ends_at <= now:
            raise AdminValidationError(texts.PERIOD_IN_PAST)

        async with self._operation() as session:
            repository = CatalogRepository(session)
            bookings = BookingRepository(session)
            schedule = ScheduleRepository(session)
            async with session.begin():
                barber = await repository.get_barber_for_update(barber_id)
                if barber is None:
                    raise AdminNotFound(texts.NOT_FOUND)
                overlapping = await schedule.list_time_off(
                    barber.id, window_start=starts_at, window_end=ends_at
                )
                if overlapping:
                    raise AdminValidationError(texts.PERIOD_OVERLAP)
                conflicts = await self._time_off_conflicts(
                    bookings,
                    barber=barber,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    now=now,
                )
                if conflicts:
                    raise AdminConflict(
                        texts.schedule_conflict_text(barber.name, conflicts)
                    )
                return await schedule.add_time_off(
                    barber_id=barber.id, starts_at=starts_at, ends_at=ends_at
                )

    async def remove_time_off(
        self, *, actor_telegram_id: int, barber_id: int, time_off_id: int
    ) -> None:
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            repository = CatalogRepository(session)
            schedule = ScheduleRepository(session)
            async with session.begin():
                barber = await repository.get_barber_for_update(barber_id)
                if barber is None:
                    raise AdminNotFound(texts.NOT_FOUND)
                row = await schedule.get_time_off_for_update(time_off_id)
                if row is None or row.barber_id != barber.id:
                    raise AdminNotFound(texts.NOT_FOUND)
                await schedule.delete_time_off(row)

    # ------------------------------------------------------------------ #
    # Записи клиентов
    # ------------------------------------------------------------------ #

    async def list_bookings(
        self,
        *,
        actor_telegram_id: int,
        on_date: date | None = None,
        barber_id: int | None = None,
        page: int = 0,
    ) -> BookingsPage:
        self._authorize(actor_telegram_id)
        window_start: datetime | None = None
        window_end: datetime | None = None
        if on_date is not None:
            window_start = datetime.combine(on_date, time(0, 0), tzinfo=self._tz)
            window_end = window_start + timedelta(days=1)

        async with self._operation() as session:
            repository = BookingRepository(session)
            total = await repository.count_for_admin(
                window_start=window_start,
                window_end=window_end,
                barber_id=barber_id,
            )
            info = paginate(total, page)
            rows = await repository.list_for_admin(
                window_start=window_start,
                window_end=window_end,
                barber_id=barber_id,
                limit=PAGE_SIZE,
                offset=info.offset,
            )
        return BookingsPage(rows=list(rows), page=info)

    async def get_booking(self, *, actor_telegram_id: int, booking_id: int) -> Booking:
        self._authorize(actor_telegram_id)
        async with self._operation() as session:
            booking = await BookingRepository(session).get_with_details_for_admin(
                booking_id
            )
        if booking is None:
            raise AdminNotFound(texts.NOT_FOUND)
        return booking

    async def cancel_booking(
        self, *, actor_telegram_id: int, booking_id: int
    ) -> Booking:
        """Отменить запись клиента в обход двухчасового ограничения.

        Права проверяются здесь повторно, статус — под блокировкой строки,
        поэтому повторная или параллельная отмена не может пройти дважды.
        """
        self._authorize(actor_telegram_id)
        now = self._now()
        async with self._operation() as session:
            repository = BookingRepository(session)
            try:
                async with session.begin():
                    booking = await repository.get_for_update(booking_id)
                    if booking is None:
                        raise AdminNotFound(texts.NOT_FOUND)
                    if booking.status == BookingStatus.CANCELLED:
                        raise AdminBookingState(texts.BOOKING_ALREADY_CANCELLED)
                    if booking.status == BookingStatus.COMPLETED:
                        raise AdminBookingState(texts.BOOKING_COMPLETED)
                    await repository.mark_cancelled(booking, cancelled_at=now)
                    cancelled = await repository.get_with_details_for_admin(booking_id)
                    if cancelled is None:  # pragma: no cover - защита от гонки
                        raise AdminDatabaseUnavailable(texts.DATABASE_ERROR)
            except IntegrityError:
                raise AdminDatabaseUnavailable(texts.DATABASE_ERROR) from None
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
        except AdminError:
            raise
        except SQLAlchemyError as error:
            logger.warning(
                "Ошибка базы данных в админ-панели (%s)", type(error).__name__
            )
            raise AdminDatabaseUnavailable(texts.DATABASE_ERROR) from None

    async def _future_confirmed(
        self, repository: BookingRepository, *, barber_id: int, now: datetime
    ) -> Sequence[Booking]:
        return await repository.list_future_confirmed_for_barber(barber_id, after=now)

    async def _weekday_conflicts(
        self,
        repository: BookingRepository,
        *,
        barber: Barber,
        weekday: int,
        window: tuple[time, time] | None,
        now: datetime,
    ) -> list[Booking]:
        """Будущие записи дня недели, которые не помещаются в новые часы."""
        rows = await self._future_confirmed(repository, barber_id=barber.id, now=now)
        conflicts: list[Booking] = []
        for booking in rows:
            local = booking.starts_at.astimezone(self._tz)
            if local.weekday() != weekday:
                continue
            if window is None:
                conflicts.append(booking)
                continue
            start, end = window
            day = local.date()
            window_start = datetime.combine(day, start, tzinfo=self._tz)
            window_end = datetime.combine(day, end, tzinfo=self._tz)
            if booking.starts_at < window_start or booking.ends_at > window_end:
                conflicts.append(booking)
        return conflicts

    async def _time_off_conflicts(
        self,
        repository: BookingRepository,
        *,
        barber: Barber,
        starts_at: datetime,
        ends_at: datetime,
        now: datetime,
    ) -> list[Booking]:
        """Будущие записи, которые попадают в новый период отсутствия."""
        rows = await self._future_confirmed(repository, barber_id=barber.id, now=now)
        return [
            booking
            for booking in rows
            if booking.starts_at < ends_at and starts_at < booking.ends_at
        ]


__all__ = [
    "MAX_DURATION_MINUTES",
    "MAX_PRICE_RUB",
    "MIN_DURATION_MINUTES",
    "PAGE_SIZE",
    "AdminService",
    "BarberView",
    "BarbersPage",
    "BookingsPage",
    "Page",
    "ServicesPage",
    "TimeOffPage",
    "check_duration_minutes",
    "check_price_rub",
    "check_weekday",
    "paginate",
    "parse_barber_name",
    "parse_day",
    "parse_duration",
    "parse_period",
    "parse_price",
    "parse_service_name",
    "parse_working_hours",
]
