"""Административная панель BarberBot.

Модуль собирает доменные ошибки, административный сервис и постраничную
выдачу. Telegram-интерфейс панели живёт в :mod:`barberbot.handlers.admin`,
представление — в подмодулях ``texts``, ``keyboards``, ``callbacks`` и ``fsm``.
"""

from __future__ import annotations

from barberbot.admin.errors import (
    AdminAccessDenied,
    AdminBookingState,
    AdminConflict,
    AdminDatabaseUnavailable,
    AdminError,
    AdminNotFound,
    AdminValidationError,
)
from barberbot.admin.service import (
    PAGE_SIZE,
    AdminService,
    BarbersPage,
    BarberView,
    BookingsPage,
    Page,
    ServicesPage,
    TimeOffPage,
    paginate,
)

__all__ = [
    "PAGE_SIZE",
    "AdminAccessDenied",
    "AdminBookingState",
    "AdminConflict",
    "AdminDatabaseUnavailable",
    "AdminError",
    "AdminNotFound",
    "AdminService",
    "AdminValidationError",
    "BarberView",
    "BarbersPage",
    "BookingsPage",
    "Page",
    "ServicesPage",
    "TimeOffPage",
    "paginate",
]
