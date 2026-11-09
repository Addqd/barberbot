"""Доменные ошибки движка бронирования.

Сообщения предназначены для показа пользователю: только понятный текст на
русском языке, без SQL, DSN, имён таблиц и прочих внутренних подробностей.
"""

from __future__ import annotations


class BookingError(Exception):
    """Базовая ошибка домена бронирования."""


class ServiceUnavailable(BookingError):
    """Услуга не найдена или отключена."""


class BarberUnavailable(BookingError):
    """Мастер не найден или отключён."""


class BookingNotFound(BookingError):
    """Запись не найдена."""


class InvalidBookingTime(BookingError):
    """Недопустимые дата или время начала записи."""


class SlotUnavailable(BookingError):
    """Выбранное время занято другим активным бронированием или отсутствием мастера."""


class BookingAlreadyCancelled(BookingError):
    """Запись уже отменена."""


class BookingNotCancellable(BookingError):
    """Запись нельзя отменить (например, услуга уже оказана)."""


class NotBookingOwner(BookingError):
    """Попытка управлять чужой записью."""


class CancellationTooLate(BookingError):
    """Срок разрешённой отмены истёк."""


class DatabaseUnavailable(BookingError):
    """Временная ошибка базы данных; подробности не раскрываются."""


__all__ = [
    "BarberUnavailable",
    "BookingAlreadyCancelled",
    "BookingError",
    "BookingNotCancellable",
    "BookingNotFound",
    "CancellationTooLate",
    "DatabaseUnavailable",
    "InvalidBookingTime",
    "NotBookingOwner",
    "ServiceUnavailable",
    "SlotUnavailable",
]
