"""Форматирование данных для сообщений: только представление, без бизнес-логики.

Все даты и время показываются по Москве (``Europe/Moscow``) в форматах
``ДД.ММ.ГГГГ`` и ``ЧЧ:ММ``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime

from barberbot.booking.slots import CANCELLATION_DEADLINE, MOSCOW
from barberbot.db.models import Booking, BookingStatus, Service

WEEKDAY_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

STATUS_LABELS: dict[BookingStatus, str] = {
    BookingStatus.CONFIRMED: "✅ Подтверждена",
    BookingStatus.CANCELLED: "❌ Отменена",
    BookingStatus.COMPLETED: "🏁 Завершена",
}


def as_moscow(value: datetime) -> datetime:
    """Привести момент времени к часовому поясу барбершопа."""
    return value.astimezone(MOSCOW)


def format_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def format_day_short(day: date) -> str:
    return f"{WEEKDAY_SHORT[day.weekday()]}, {day.strftime('%d.%m')}"


def format_time(value: datetime) -> str:
    return as_moscow(value).strftime("%H:%M")


def format_datetime(value: datetime) -> str:
    local = as_moscow(value)
    return f"{format_date(local.date())} {format_time(local)}"


def format_price(price_rub: int) -> str:
    return f"{price_rub} ₽"


def format_duration(minutes: int) -> str:
    """Русская форма слова «минута» для длительности услуги."""
    remainder_100 = minutes % 100
    if 11 <= remainder_100 <= 14:
        word = "минут"
    elif minutes % 10 == 1:
        word = "минута"
    elif 2 <= minutes % 10 <= 4:
        word = "минуты"
    else:
        word = "минут"
    return f"{minutes} {word}"


def status_label(status: BookingStatus) -> str:
    return STATUS_LABELS.get(status, status.value)


def service_line(service: Service) -> str:
    return (
        f"{service.name} — {format_price(service.price_rub)}, "
        f"{format_duration(service.duration_minutes)}"
    )


def service_button(service: Service) -> str:
    return f"{service.name} · {format_price(service.price_rub)}"


def appointment_lines(
    *,
    service_name: str,
    barber_name: str,
    starts_at: datetime,
    duration_minutes: int,
    price_rub: int,
) -> list[str]:
    """Строки с параметрами будущей или существующей записи."""
    local = as_moscow(starts_at)
    return [
        f"💈 Услуга: {service_name}",
        f"👤 Мастер: {barber_name}",
        f"📅 Дата: {format_date(local.date())}",
        f"🕐 Время: {format_time(local)}",
        f"⏱ Длительность: {format_duration(duration_minutes)}",
        f"💰 Стоимость: {format_price(price_rub)}",
    ]


def booking_lines(booking: Booking) -> list[str]:
    return [
        *appointment_lines(
            service_name=booking.service.name,
            barber_name=booking.barber.name,
            starts_at=booking.starts_at,
            duration_minutes=booking.duration_minutes_at_booking,
            price_rub=booking.price_rub_at_booking,
        ),
        f"📌 Статус: {status_label(booking.status)}",
    ]


def is_cancellable(booking: Booking, *, now: datetime | None = None) -> bool:
    """Можно ли показать кнопку отмены (окончательно решает сервис)."""
    moment = now or datetime.now(UTC)
    return (
        booking.status is BookingStatus.CONFIRMED
        and moment <= booking.starts_at - CANCELLATION_DEADLINE
    )


def sort_for_display(
    bookings: Iterable[Booking], *, now: datetime | None = None
) -> list[Booking]:
    """Будущие записи — от ближайшей, прошедшие — от последней."""
    moment = now or datetime.now(UTC)
    rows = list(bookings)
    upcoming = sorted(
        (row for row in rows if row.starts_at >= moment),
        key=lambda row: row.starts_at,
    )
    past = sorted(
        (row for row in rows if row.starts_at < moment),
        key=lambda row: row.starts_at,
        reverse=True,
    )
    return [*upcoming, *past]


def booking_row_label(booking: Booking) -> str:
    """Короткая подпись записи для inline-кнопки и списка."""
    return (
        f"{format_datetime(booking.starts_at)} · "
        f"{status_label(booking.status).split(' ', 1)[0]} "
        f"{booking.service.name}"
    )


__all__ = [
    "appointment_lines",
    "as_moscow",
    "booking_lines",
    "booking_row_label",
    "format_date",
    "format_datetime",
    "format_day_short",
    "format_duration",
    "format_price",
    "format_time",
    "is_cancellable",
    "service_button",
    "service_line",
    "sort_for_display",
    "status_label",
]
