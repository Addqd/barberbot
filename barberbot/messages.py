"""Тексты клиентского интерфейса на русском языке.

Функции не обращаются к базе и не содержат бизнес-правил: только сборка
сообщений из уже полученных данных. Тексты доменных ошибок приходят из
``BookingService`` и не дублируются в обработчиках.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from barberbot import ui
from barberbot.db.models import Barber, Booking, Service

NO_SERVICES = "Сейчас нет доступных услуг. Попробуйте позже."
NO_BARBERS = "Сейчас нет доступных мастеров. Попробуйте позже."
NO_DATES = (
    "😔 На ближайшие 30 дней свободных дат нет.\nПопробуйте выбрать другого мастера."
)
NO_SLOTS = (
    "😔 На этот день свободного времени нет.\nВыберите другую дату или другого мастера."
)
EMPTY_BOOKINGS = (
    "📅 Мои записи\n\n"
    "У вас пока нет записей.\n"
    "Записаться можно через «✂️ Записаться» в главном меню."
)
SESSION_EXPIRED = (
    "Сессия записи истекла, данные потеряны.\nНачните запись заново через /start."
)
STALE_CALLBACK = "Эта кнопка устарела.\nНачните сценарий заново через /start."
SERVICE_GONE = "Эта услуга больше недоступна."
BARBER_GONE = "Этот мастер больше недоступен."
DATE_GONE = "Эта дата больше недоступна. Выберите другую."
SLOT_GONE = "Это время больше недоступно. Выберите другое."
BOOKING_GONE = "Запись не найдена или уже недоступна."
CANCEL_NOT_AVAILABLE = "Отмена недоступна: до начала записи осталось меньше 2 часов."
CANCEL_ALREADY = "Запись уже отменена."
CANCEL_COMPLETED = "Завершённую запись отменить нельзя."
CONFIRM_RETRY = "Повторите попытку или вернитесь в главное меню."
TIMEZONE_HINT = "Время указано по Москве, шаг записи — 30 минут."


def services_section_text(services: Sequence[Service]) -> str:
    lines = ["💈 Услуги и цены", ""]
    if not services:
        lines.append(NO_SERVICES)
        return "\n".join(lines)
    lines.extend(f"• {ui.service_line(service)}" for service in services)
    lines.extend(["", "Чтобы записаться, нажмите «✂️ Записаться» в главном меню."])
    return "\n".join(lines)


def service_choice_text(services: Sequence[Service]) -> str:
    lines = ["✂️ Выберите услугу", ""]
    lines.extend(f"• {ui.service_line(service)}" for service in services)
    lines.extend(["", TIMEZONE_HINT])
    return "\n".join(lines)


def barber_choice_text(barbers: Sequence[Barber]) -> str:
    lines = ["👤 Выберите мастера", ""]
    lines.extend(f"• {barber.name}" for barber in barbers)
    return "\n".join(lines)


def dates_text(dates: Sequence[date], page: int, pages: int) -> str:
    lines = [
        "📅 Выберите дату",
        "",
        "Показаны только дни, где есть свободное время.",
    ]
    if pages > 1:
        lines.append(f"Страница {page + 1} из {pages}.")
    return "\n".join(lines)


def times_text(day: date) -> str:
    return "\n".join(
        [
            "🕐 Выберите время",
            "",
            f"Дата: {ui.format_date(day)}",
            TIMEZONE_HINT,
        ]
    )


def confirmation_text(
    *,
    service: Service,
    barber: Barber,
    starts_at: datetime,
) -> str:
    lines = [
        "📝 Проверьте данные записи",
        "",
        *ui.appointment_lines(
            service_name=service.name,
            barber_name=barber.name,
            starts_at=starts_at,
            duration_minutes=service.duration_minutes,
            price_rub=service.price_rub,
        ),
        "",
        "Всё верно? Подтвердите запись.",
    ]
    return "\n".join(lines)


def booking_created_text(booking: Booking) -> str:
    lines = [
        "✅ Запись создана!",
        "",
        f"Номер записи: {booking.id}",
        *ui.booking_lines(booking),
        "",
        "Мы ждём вас в барбершопе.",
    ]
    return "\n".join(lines)


def booking_card_text(booking: Booking) -> str:
    return "\n".join(
        [
            f"📅 Запись №{booking.id}",
            "",
            *ui.booking_lines(booking),
        ]
    )


def cancel_prompt_text(booking: Booking) -> str:
    return "\n".join(
        [
            "❓ Отменить запись?",
            "",
            *ui.booking_lines(booking),
            "",
            "Отмена возможна не позднее чем за 2 часа до начала.",
        ]
    )


def cancelled_text(booking: Booking) -> str:
    return "\n".join(
        [
            "✅ Запись отменена.",
            "",
            *ui.booking_lines(booking),
        ]
    )


def bookings_list_text(bookings: Sequence[Booking], page: int, pages: int) -> str:
    lines = ["📅 Мои записи", ""]
    if pages > 1:
        lines.append(f"Страница {page + 1} из {pages}.")
    lines.extend(f"• {ui.booking_row_label(booking)}" for booking in bookings)
    lines.extend(["", "Нажмите на запись, чтобы открыть подробности."])
    return "\n".join(lines)


__all__ = [
    "BARBER_GONE",
    "BOOKING_GONE",
    "CANCEL_ALREADY",
    "CANCEL_COMPLETED",
    "CANCEL_NOT_AVAILABLE",
    "CONFIRM_RETRY",
    "DATE_GONE",
    "EMPTY_BOOKINGS",
    "NO_BARBERS",
    "NO_DATES",
    "NO_SERVICES",
    "NO_SLOTS",
    "SERVICE_GONE",
    "SESSION_EXPIRED",
    "SLOT_GONE",
    "STALE_CALLBACK",
    "TIMEZONE_HINT",
    "barber_choice_text",
    "booking_card_text",
    "booking_created_text",
    "bookings_list_text",
    "cancel_prompt_text",
    "cancelled_text",
    "confirmation_text",
    "dates_text",
    "service_choice_text",
    "services_section_text",
    "times_text",
]
