"""Движок бронирования, независимый от Telegram-интерфейса."""

from __future__ import annotations

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
from barberbot.booking.service import BookingService

__all__ = [
    "BarberUnavailable",
    "BookingAlreadyCancelled",
    "BookingError",
    "BookingNotCancellable",
    "BookingNotFound",
    "BookingService",
    "CancellationTooLate",
    "DatabaseUnavailable",
    "InvalidBookingTime",
    "NotBookingOwner",
    "ServiceUnavailable",
    "SlotUnavailable",
]
