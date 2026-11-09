"""Пакет работы с базой данных: ORM-модели, движок и репозитории."""

from __future__ import annotations

from barberbot.db.base import Base
from barberbot.db.engine import Database, create_database
from barberbot.db.models import (
    ACTIVE_BOOKING_STATUSES,
    Barber,
    BarberTimeOff,
    BarberWorkingHours,
    Booking,
    BookingStatus,
    Reminder,
    ReminderStatus,
    Service,
    User,
)
from barberbot.db.repositories import (
    BookingRepository,
    CatalogRepository,
    ScheduleRepository,
    UserRepository,
)

__all__ = [
    "ACTIVE_BOOKING_STATUSES",
    "Barber",
    "BarberTimeOff",
    "BarberWorkingHours",
    "Base",
    "Booking",
    "BookingRepository",
    "BookingStatus",
    "CatalogRepository",
    "Database",
    "Reminder",
    "ReminderStatus",
    "ScheduleRepository",
    "Service",
    "User",
    "UserRepository",
    "create_database",
]
