"""Слой доступа к данным: SQLAlchemy-запросы без бизнес-правил.

Каждый репозиторий получает готовую ``AsyncSession``; транзакциями и сессиями
управляет вызывающий код (booking service). Это позволяет переиспользовать
репозитории в разных операциях без Unit of Work boilerplate.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from barberbot.db.models import (
    ACTIVE_BOOKING_STATUSES,
    Barber,
    BarberTimeOff,
    BarberWorkingHours,
    Booking,
    BookingStatus,
    Service,
    User,
)


class UserRepository:
    """Пользователи Telegram."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, telegram_id: int, display_name: str | None = None
    ) -> User:
        """Найти или создать пользователя, безопасно при параллельных запросах.

        ``INSERT ... ON CONFLICT DO NOTHING`` не падает на гонке двух
        одновременных первых сообщений от одного Telegram ID.
        """
        existing = await self.get_by_telegram_id(telegram_id)
        if existing is not None:
            return existing

        insert_statement = (
            pg_insert(User)
            .values(telegram_id=telegram_id, display_name=display_name)
            .on_conflict_do_nothing(index_elements=[User.telegram_id])
            .returning(User.id)
        )
        await self._session.execute(insert_statement)

        created = await self.get_by_telegram_id(telegram_id)
        if created is None:  # pragma: no cover - защита от невозможного состояния
            raise RuntimeError("Не удалось создать пользователя")
        return created


class CatalogRepository:
    """Услуги и мастера."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_services(self) -> Sequence[Service]:
        result = await self._session.execute(
            select(Service).where(Service.is_active.is_(True)).order_by(Service.id)
        )
        return result.scalars().all()

    async def list_active_barbers(self) -> Sequence[Barber]:
        result = await self._session.execute(
            select(Barber).where(Barber.is_active.is_(True)).order_by(Barber.id)
        )
        return result.scalars().all()

    async def get_service(self, service_id: int) -> Service | None:
        return await self._session.get(Service, service_id)

    async def get_service_for_update(self, service_id: int) -> Service | None:
        """Услуга с блокировкой строки на время правки."""
        result = await self._session.execute(
            select(Service).where(Service.id == service_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_barber(self, barber_id: int) -> Barber | None:
        return await self._session.get(Barber, barber_id)

    async def list_services(self) -> Sequence[Service]:
        """Все услуги, включая отключённые (админ-панель)."""
        result = await self._session.execute(select(Service).order_by(Service.id))
        return result.scalars().all()

    async def list_barbers(self) -> Sequence[Barber]:
        """Все мастера, включая отключённых (админ-панель)."""
        result = await self._session.execute(select(Barber).order_by(Barber.id))
        return result.scalars().all()

    async def get_service_by_name(self, name: str) -> Service | None:
        result = await self._session.execute(
            select(Service).where(Service.name == name)
        )
        return result.scalar_one_or_none()

    async def get_barber_by_name(self, name: str) -> Barber | None:
        result = await self._session.execute(select(Barber).where(Barber.name == name))
        return result.scalar_one_or_none()

    async def get_barber_for_update(self, barber_id: int) -> Barber | None:
        """Мастер с блокировкой строки: сериализует правки расписания."""
        result = await self._session.execute(
            select(Barber).where(Barber.id == barber_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_service(
        self,
        *,
        name: str,
        price_rub: int,
        duration_minutes: int,
        is_active: bool = True,
    ) -> Service:
        service = Service(
            name=name,
            price_rub=price_rub,
            duration_minutes=duration_minutes,
            is_active=is_active,
        )
        self._session.add(service)
        await self._session.flush()
        return service

    async def create_barber(self, *, name: str, is_active: bool = False) -> Barber:
        barber = Barber(name=name, is_active=is_active)
        self._session.add(barber)
        await self._session.flush()
        return barber


class ScheduleRepository:
    """Графики мастеров и исключения из графиков."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_working_hours(self, barber_id: int) -> Sequence[BarberWorkingHours]:
        result = await self._session.execute(
            select(BarberWorkingHours)
            .where(BarberWorkingHours.barber_id == barber_id)
            .order_by(BarberWorkingHours.weekday)
        )
        return result.scalars().all()

    async def get_working_hours(
        self, barber_id: int, weekday: int
    ) -> BarberWorkingHours | None:
        result = await self._session.execute(
            select(BarberWorkingHours).where(
                BarberWorkingHours.barber_id == barber_id,
                BarberWorkingHours.weekday == weekday,
            )
        )
        return result.scalar_one_or_none()

    async def list_time_off(
        self, barber_id: int, *, window_start: datetime, window_end: datetime
    ) -> Sequence[BarberTimeOff]:
        """Исключения, пересекающиеся с интервалом ``[window_start, window_end)``."""
        result = await self._session.execute(
            select(BarberTimeOff)
            .where(
                BarberTimeOff.barber_id == barber_id,
                BarberTimeOff.starts_at < window_end,
                BarberTimeOff.ends_at > window_start,
            )
            .order_by(BarberTimeOff.starts_at)
        )
        return result.scalars().all()

    async def list_hours_for_barbers(
        self, barber_ids: Sequence[int]
    ) -> Sequence[BarberWorkingHours]:
        """Недельный график сразу для нескольких мастеров."""
        if not barber_ids:
            return []
        result = await self._session.execute(
            select(BarberWorkingHours)
            .where(BarberWorkingHours.barber_id.in_(barber_ids))
            .order_by(BarberWorkingHours.barber_id, BarberWorkingHours.weekday)
        )
        return result.scalars().all()

    async def list_all_time_off(self, barber_id: int) -> Sequence[BarberTimeOff]:
        """Все периоды отсутствия мастера, начиная с самого раннего."""
        result = await self._session.execute(
            select(BarberTimeOff)
            .where(BarberTimeOff.barber_id == barber_id)
            .order_by(BarberTimeOff.starts_at)
        )
        return result.scalars().all()

    async def get_time_off_for_update(self, time_off_id: int) -> BarberTimeOff | None:
        """Период отсутствия с блокировкой строки (защита от двойного удаления)."""
        result = await self._session.execute(
            select(BarberTimeOff)
            .where(BarberTimeOff.id == time_off_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def set_working_hours(
        self, *, barber_id: int, weekday: int, start_time: time, end_time: time
    ) -> BarberWorkingHours:
        """Создать или обновить рабочие часы дня недели (``uq_barber_weekday``)."""
        existing = await self.get_working_hours(barber_id, weekday)
        if existing is None:
            row = BarberWorkingHours(
                barber_id=barber_id,
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
            )
            self._session.add(row)
            await self._session.flush()
            return row
        existing.start_time = start_time
        existing.end_time = end_time
        await self._session.flush()
        return existing

    async def delete_working_hours(self, barber_id: int, weekday: int) -> bool:
        """Удалить рабочие часы дня недели. ``True`` — строка была удалена."""
        row = await self.get_working_hours(barber_id, weekday)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def add_time_off(
        self,
        *,
        barber_id: int,
        starts_at: datetime,
        ends_at: datetime,
        reason: str | None = None,
    ) -> BarberTimeOff:
        row = BarberTimeOff(
            barber_id=barber_id, starts_at=starts_at, ends_at=ends_at, reason=reason
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def delete_time_off(self, row: BarberTimeOff) -> None:
        await self._session.delete(row)
        await self._session.flush()


class BookingRepository:
    """Записи клиентов."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_between(
        self, barber_id: int, *, window_start: datetime, window_end: datetime
    ) -> Sequence[Booking]:
        """Активные записи мастера, занимающие время в интервале."""
        result = await self._session.execute(
            select(Booking)
            .where(
                Booking.barber_id == barber_id,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.starts_at < window_end,
                Booking.ends_at > window_start,
            )
            .order_by(Booking.starts_at)
        )
        return result.scalars().all()

    async def create(
        self,
        *,
        user_id: int,
        barber_id: int,
        service_id: int,
        starts_at: datetime,
        ends_at: datetime,
        price_rub: int,
        duration_minutes: int,
    ) -> Booking:
        """Вставить запись и получить её первичный ключ.

        Пересечение активных записей одного мастера отклоняется PostgreSQL
        (SQLSTATE ``23P01``); исключение пробрасывается вызывающему коду.
        """
        booking = Booking(
            user_id=user_id,
            barber_id=barber_id,
            service_id=service_id,
            starts_at=starts_at,
            ends_at=ends_at,
            price_rub_at_booking=price_rub,
            duration_minutes_at_booking=duration_minutes,
            status=BookingStatus.CONFIRMED,
        )
        self._session.add(booking)
        await self._session.flush()
        return booking

    async def get(self, booking_id: int) -> Booking | None:
        return await self._session.get(Booking, booking_id)

    async def get_with_details(self, booking_id: int) -> Booking | None:
        result = await self._session.execute(
            select(Booking)
            .where(Booking.id == booking_id)
            .options(selectinload(Booking.barber), selectinload(Booking.service))
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, booking_id: int) -> Booking | None:
        """Загрузить запись с блокировкой строки до конца транзакции."""
        result = await self._session.execute(
            select(Booking).where(Booking.id == booking_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def mark_cancelled(self, booking: Booking, *, cancelled_at: datetime) -> None:
        """Отметить запись отменённой; освобождение слота делает сама БД."""
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = cancelled_at
        await self._session.flush()

    async def complete_finished(self, *, now: datetime) -> int:
        """Завершить подтверждённые записи и вернуть их количество."""
        updated = (
            update(Booking)
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.ends_at <= now,
            )
            .values(status=BookingStatus.COMPLETED)
            .returning(Booking.id)
            .cte("completed_rows")
        )

        result = await self._session.execute(select(func.count()).select_from(updated))
        return result.scalar_one()

    async def list_for_user(
        self, user_id: int, *, include_cancelled: bool = True
    ) -> Sequence[Booking]:
        statement = (
            select(Booking)
            .where(Booking.user_id == user_id)
            .options(selectinload(Booking.barber), selectinload(Booking.service))
            .order_by(Booking.starts_at)
        )
        if not include_cancelled:
            statement = statement.where(Booking.status != BookingStatus.CANCELLED)
        result = await self._session.execute(statement)
        return result.scalars().all()

    # ------------------------------------------------------------------ #
    # Админ-панель
    # ------------------------------------------------------------------ #

    async def get_with_details_for_admin(self, booking_id: int) -> Booking | None:
        """Запись с услугой, мастером и клиентом (карточка админ-панели)."""
        result = await self._session.execute(
            select(Booking)
            .where(Booking.id == booking_id)
            .options(
                selectinload(Booking.barber),
                selectinload(Booking.service),
                selectinload(Booking.user),
            )
        )
        return result.scalar_one_or_none()

    async def list_future_confirmed_for_barber(
        self, barber_id: int, *, after: datetime
    ) -> Sequence[Booking]:
        """Будущие подтверждённые записи мастера (проверка правок графика)."""
        result = await self._session.execute(
            select(Booking)
            .where(
                Booking.barber_id == barber_id,
                Booking.status == BookingStatus.CONFIRMED,
                Booking.starts_at > after,
            )
            .options(selectinload(Booking.service))
            .order_by(Booking.starts_at)
        )
        return result.scalars().all()

    async def list_for_admin(
        self,
        *,
        window_start: datetime | None,
        window_end: datetime | None,
        barber_id: int | None,
        limit: int,
        offset: int,
    ) -> Sequence[Booking]:
        """Страница записей всех клиентов с фильтрами по дате и мастеру."""
        statement = (
            select(Booking)
            .where(*_admin_booking_filters(window_start, window_end, barber_id))
            .options(
                selectinload(Booking.barber),
                selectinload(Booking.service),
                selectinload(Booking.user),
            )
            .order_by(Booking.starts_at.desc(), Booking.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def count_for_admin(
        self,
        *,
        window_start: datetime | None,
        window_end: datetime | None,
        barber_id: int | None,
    ) -> int:
        """Общее количество записей под теми же фильтрами (для пагинации)."""
        statement = (
            select(func.count())
            .select_from(Booking)
            .where(*_admin_booking_filters(window_start, window_end, barber_id))
        )
        result = await self._session.execute(statement)
        return result.scalar_one()


def _admin_booking_filters(
    window_start: datetime | None,
    window_end: datetime | None,
    barber_id: int | None,
) -> list[ColumnElement[bool]]:
    """Условия фильтрации списка записей админ-панели."""
    filters: list[ColumnElement[bool]] = []
    if window_start is not None:
        filters.append(Booking.starts_at >= window_start)
    if window_end is not None:
        filters.append(Booking.starts_at < window_end)
    if barber_id is not None:
        filters.append(Booking.barber_id == barber_id)
    return filters


__all__ = [
    "BookingRepository",
    "CatalogRepository",
    "ScheduleRepository",
    "UserRepository",
]
