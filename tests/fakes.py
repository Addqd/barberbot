"""Фейковый сервис бронирования для unit-тестов навигации (без БД)."""

from __future__ import annotations

from datetime import date, datetime

from barberbot.db.models import Barber, Booking, Service


def make_service(
    *,
    service_id: int = 1,
    name: str = "Обычная стрижка",
    price: int = 500,
    duration: int = 60,
) -> Service:
    """Отсоединённая ORM-модель услуги для unit-тестов (без БД)."""
    return Service(
        id=service_id,
        name=name,
        price_rub=price,
        duration_minutes=duration,
        is_active=True,
    )


def make_barber(*, barber_id: int = 1, name: str = "Елена") -> Barber:
    """Отсоединённая ORM-модель мастера для unit-тестов (без БД)."""
    return Barber(id=barber_id, name=name, is_active=True)


class FakeBookingService:
    """Повторяет публичные методы ``BookingService`` без обращения к БД.

    Тесты настраивают возвращаемые данные и ``error`` — исключение, которое
    будет выброшено при любом вызове. Создание и отмена по умолчанию падают:
    для них есть интеграционные тесты на реальной тестовой базе.
    """

    def __init__(self) -> None:
        self.services: list[Service] = []
        self.barbers: list[Barber] = []
        self.dates: list[date] = []
        self.slots: list[datetime] = []
        self.bookings: list[Booking] = []
        self.error: Exception | None = None
        self.calls: list[str] = []

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.error is not None:
            raise self.error

    async def list_active_services(self) -> list[Service]:
        self._check("list_active_services")
        return list(self.services)

    async def list_active_barbers(self) -> list[Barber]:
        self._check("list_active_barbers")
        return list(self.barbers)

    async def available_dates(
        self,
        *,
        service_id: int,
        barber_id: int,
        start_date: date | None = None,
        days: int | None = None,
    ) -> list[date]:
        self._check("available_dates")
        return list(self.dates)

    async def available_slots(
        self, *, service_id: int, barber_id: int, on_date: date
    ) -> list[datetime]:
        self._check("available_slots")
        return list(self.slots)

    async def create_booking(
        self,
        *,
        telegram_id: int,
        barber_id: int,
        service_id: int,
        starts_at: datetime,
        display_name: str | None = None,
    ) -> Booking:
        self._check("create_booking")
        raise AssertionError("create_booking не ожидается в этом тесте")

    async def list_user_bookings(
        self, telegram_id: int, *, include_cancelled: bool = True
    ) -> list[Booking]:
        self._check("list_user_bookings")
        return list(self.bookings)

    async def cancel_booking(self, *, telegram_id: int, booking_id: int) -> Booking:
        self._check("cancel_booking")
        raise AssertionError("cancel_booking не ожидается в этом тесте")


class FakeAdminService:
    """Минимальная заглушка административного сервиса.

    В тестах авторизации административные обработчики не вызываются: проверяются
    guard-мидлварь и состав главного меню. Полный ``AdminService`` проверяется
    интеграционными тестами на реальной тестовой базе.
    """

    def __init__(self, admin_ids: frozenset[int] = frozenset()) -> None:
        self._admin_ids = frozenset(admin_ids)

    @property
    def admin_ids(self) -> frozenset[int]:
        return self._admin_ids

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self._admin_ids


__all__ = [
    "FakeAdminService",
    "FakeBookingService",
    "make_barber",
    "make_service",
]
