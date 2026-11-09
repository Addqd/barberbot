"""Слой доступа к данным: SQLAlchemy-запросы без бизнес-правил.

Каждый репозиторий получает готовую ``AsyncSession``; транзакциями и сессиями
управляет вызывающий код (booking service). Это позволяет переиспользовать
репозитории в разных операциях без Unit of Work boilerplate.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    async def get_barber(self, barber_id: int) -> Barber | None:
        return await self._session.get(Barber, barber_id)


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


__all__ = [
    "BookingRepository",
    "CatalogRepository",
    "ScheduleRepository",
    "UserRepository",
]
