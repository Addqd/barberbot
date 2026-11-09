"""Тексты и подписи административной панели на русском языке.

Модуль не обращается к базе и не содержит бизнес-правил: только сборка
сообщений и подписей кнопок из уже полученных данных.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from barberbot import ui
from barberbot.db.models import (
    Barber,
    BarberTimeOff,
    BarberWorkingHours,
    Booking,
    Service,
)

WEEKDAYS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

#: Сколько конфликтующих записей показывать в объяснении отказа.
CONFLICT_LIMIT = 5

PANEL_TEXT = (
    "⚙️ Админ-панель\n"
    "\n"
    "Выберите раздел:\n"
    "• 💈 Услуги — названия, цены и длительность;\n"
    "• 👤 Барберы — расписание и отсутствия;\n"
    "• 📅 Записи клиентов — все записи и отмена."
)

ACCESS_DENIED = "⛔ Недостаточно прав: действие доступно только администратору."
SESSION_EXPIRED = (
    "Данные действия потеряны: состояние формы сброшено.\n"
    "Откройте раздел заново через «⚙️ Админ-панель»."
)
TEXT_ONLY = "Отправьте, пожалуйста, текстовое сообщение."
NOT_FOUND = "Объект не найден: возможно, он уже изменён или удалён."
DATABASE_ERROR = "Сервис временно недоступен. Попробуйте позже."

SERVICE_NAME_TAKEN = "Услуга с таким названием уже существует."
BOOKING_ALREADY_CANCELLED = "Запись уже отменена: повторная отмена невозможна."
BOOKING_COMPLETED = "Завершённую запись отменить нельзя."
BARBER_NAME_TAKEN = "Мастер с таким именем уже существует."

ADD_SERVICE_NAME_PROMPT = "Введите название новой услуги (до 160 символов)."
ADD_SERVICE_PRICE_PROMPT = "Введите цену услуги в рублях: целое число, 0 или больше."
ADD_SERVICE_DURATION_PROMPT = (
    "Введите длительность услуги в минутах: целое число от 1 до 60."
)
ADD_BARBER_NAME_PROMPT = (
    "Введите имя нового мастера (до 120 символов).\n"
    "\n"
    "Мастер будет добавлен отключённым: настройте расписание и включите его."
)
EDIT_SERVICE_PROMPTS = {
    "name": "Введите новое название услуги (до 160 символов).",
    "price": "Введите новую цену услуги: целое число рублей, 0 или больше.",
    "duration": "Введите новую длительность услуги: целое число от 1 до 60 минут.",
}
WORKING_HOURS_PROMPT = (
    "Отправьте рабочие часы дня «{weekday}» в формате 09:00-18:00 "
    "или слово «выходной», чтобы сделать день нерабочим."
)
TIME_OFF_PROMPT = (
    "Отправьте период отсутствия:\n"
    "• ДД.ММ.ГГГГ — один день;\n"
    "• ДД.ММ.ГГГГ-ДД.ММ.ГГГГ — диапазон дней.\n"
    "\n"
    "Время указано по Москве."
)
BOOKINGS_DATE_PROMPT = "Отправьте дату в формате ДД.ММ.ГГГГ."
FILTER_BARBER_PROMPT = (
    "👤 Выберите мастера: будут показаны только его записи.\n"
    "Пункт «Все мастера» снимает этот фильтр."
)

INVALID_NAME = "Название должно содержать от 1 до {limit} символов."
INVALID_PRICE = "Цена должна быть целым числом рублей, 0 или больше."
INVALID_DURATION = "Длительность должна быть целым числом минут от 1 до 60."
INVALID_HOURS = (
    "Не удалось разобрать часы. Отправьте 09:00-18:00 или слово «выходной»; "
    "начало должно быть раньше окончания."
)
INVALID_DATE = "Не удалось разобрать дату. Отправьте её в формате ДД.ММ.ГГГГ."
INVALID_PERIOD = (
    "Не удалось разобрать период. Отправьте ДД.ММ.ГГГГ или ДД.ММ.ГГГГ-ДД.ММ.ГГГГ."
)
PERIOD_IN_PAST = "Период отсутствия должен заканчиваться в будущем."
PERIOD_OVERLAP = "Такой период отсутствия уже добавлен."

NOTE_SAVED = "✅ Сохранено."
NOTE_SERVICE_CREATED = "✅ Услуга добавлена."
NOTE_BARBER_CREATED = "✅ Мастер добавлен и пока отключён."
NOTE_TIME_OFF_ADDED = "✅ Период отсутствия добавлен."
NOTE_TIME_OFF_REMOVED = "✅ Период отсутствия удалён."
NOTE_BOOKING_CANCELLED = "✅ Запись отменена."
NOTE_FILTERS_RESET = "♻️ Фильтры сброшены."

SERVICE_ENABLED_NOTE = "🟢 Услуга включена."
SERVICE_DISABLED_NOTE = "🔴 Услуга отключена: история записей сохранена."
BARBER_ENABLED_NOTE = "🟢 Мастер включён."
BARBER_DISABLED_NOTE = "🔴 Мастер отключён: история записей сохранена."


def page_label(page: int, pages: int) -> str:
    return f"Страница {page + 1} из {pages}."


def weekday_name(weekday: int) -> str:
    return WEEKDAYS[weekday]


def weekday_short(weekday: int) -> str:
    return ui.WEEKDAY_SHORT[weekday]


def hours_label(row: BarberWorkingHours | None) -> str:
    if row is None:
        return "выходной"
    return f"{row.start_time.strftime('%H:%M')}–{row.end_time.strftime('%H:%M')}"


def service_status(is_active: bool) -> str:
    return "✅ включена" if is_active else "🔴 отключена"


def barber_status(is_active: bool) -> str:
    return "✅ работает" if is_active else "🔴 отключён"


def time_off_period(row: BarberTimeOff) -> str:
    """Период отсутствия в виде «ДД.ММ.ГГГГ» или «ДД.ММ.ГГГГ–ДД.ММ.ГГГГ»."""
    first = ui.as_moscow(row.starts_at).date()
    last = ui.as_moscow(row.ends_at - timedelta(microseconds=1)).date()
    if first == last:
        return ui.format_date(first)
    return f"{ui.format_date(first)}–{ui.format_date(last)}"


# --------------------------------------------------------------------------- #
# Услуги
# --------------------------------------------------------------------------- #


def services_text(
    rows: Sequence[Service],
    *,
    total: int,
    active: int,
    page: int,
    pages: int,
) -> str:
    lines = ["💈 Услуги", ""]
    if total == 0:
        lines.extend(["Услуг пока нет.", ""])
    else:
        lines.append(f"Всего: {total}, из них включено: {active}.")
        if pages > 1:
            lines.append(page_label(page, pages))
    if rows:
        lines.extend(["", "Нажмите на услугу, чтобы открыть карточку."])
    return "\n".join(lines)


def service_button_label(service: Service) -> str:
    mark = "✅" if service.is_active else "🔴"
    return f"{mark} {service.name} · {ui.format_price(service.price_rub)}"


def service_card_text(service: Service) -> str:
    return "\n".join(
        [
            f"💈 Услуга №{service.id}",
            "",
            f"Название: {service.name}",
            f"Цена: {ui.format_price(service.price_rub)}",
            f"Длительность: {ui.format_duration(service.duration_minutes)}",
            f"Статус: {service_status(service.is_active)}",
            "",
            (
                "Изменение цены и длительности не затрагивает уже созданные "
                "записи: в них сохраняются условия на момент записи."
            ),
        ]
    )


# --------------------------------------------------------------------------- #
# Барберы
# --------------------------------------------------------------------------- #


def barbers_text(
    rows: Sequence[Barber],
    *,
    total: int,
    active: int,
    page: int,
    pages: int,
) -> str:
    lines = ["👤 Барберы", ""]
    if total == 0:
        lines.extend(["Мастеров пока нет.", ""])
    else:
        lines.append(f"Всего: {total}, из них включено: {active}.")
        if pages > 1:
            lines.append(page_label(page, pages))
    lines.extend(["", "Нажмите на мастера, чтобы открыть карточку."])
    return "\n".join(lines)


def barber_choice_label(barber: Barber) -> str:
    mark = "✅" if barber.is_active else "🔴"
    return f"{mark} {barber.name}"


def barber_button_label(barber: Barber, working_days: int) -> str:
    mark = "✅" if barber.is_active else "🔴"
    return f"{mark} {barber.name} · {working_days} дн."


def barber_card_text(
    barber: Barber,
    hours: dict[int, BarberWorkingHours],
    time_off: Sequence[BarberTimeOff],
) -> str:
    lines = [
        f"👤 Мастер №{barber.id}",
        "",
        f"Имя: {barber.name}",
        f"Статус: {barber_status(barber.is_active)}",
        "",
        "Рабочие дни:",
    ]
    if hours:
        lines.extend(
            f"• {weekday_short(weekday)}: {hours_label(hours.get(weekday))}"
            for weekday in range(7)
            if weekday in hours
        )
    else:
        lines.append("• расписание не настроено")
    lines.extend(["", f"Периодов отсутствия: {len(time_off)}."])
    if not barber.is_active:
        lines.extend(
            [
                "",
                "Мастер отключён: новые записи недоступны, история сохранена.",
            ]
        )
    return "\n".join(lines)


def schedule_text(barber: Barber, hours: dict[int, BarberWorkingHours]) -> str:
    lines = [f"🕐 Расписание — {barber.name}", ""]
    lines.extend(
        f"{weekday_short(weekday)}: {hours_label(hours.get(weekday))}"
        for weekday in range(7)
    )
    lines.extend(
        [
            "",
            "Нажмите на день недели, чтобы изменить рабочие часы.",
            (
                "Изменение отклоняется, если из-за него будущие записи станут "
                "недействительными."
            ),
        ]
    )
    return "\n".join(lines)


def schedule_button_label(weekday: int, row: BarberWorkingHours | None) -> str:
    return f"{weekday_short(weekday)} · {hours_label(row)}"


def time_off_text(
    barber: Barber, rows: Sequence[BarberTimeOff], *, page: int, pages: int
) -> str:
    lines = [f"🚫 Отсутствия — {barber.name}", ""]
    if not rows:
        lines.extend(["Периодов отсутствия нет.", ""])
    else:
        if pages > 1:
            lines.append(page_label(page, pages))
            lines.append("")
        lines.extend(f"• {time_off_period(row)}" for row in rows)
        lines.extend(["", "Нажмите на период, чтобы удалить его."])
    return "\n".join(lines)


def time_off_button_label(row: BarberTimeOff) -> str:
    return f"❌ {time_off_period(row)}"


def schedule_conflict_text(barber_name: str, conflicts: Sequence[Booking]) -> str:
    lines = [
        (
            "⚠️ Изменение отклонено: есть будущие записи, которые станут "
            "недействительными."
        ),
        "",
        f"Мастер: {barber_name}",
    ]
    lines.extend(
        f"• {ui.format_datetime(row.starts_at)} — {row.service.name} (запись №{row.id})"
        for row in conflicts[:CONFLICT_LIMIT]
    )
    if len(conflicts) > CONFLICT_LIMIT:
        lines.append(f"…и ещё {len(conflicts) - CONFLICT_LIMIT}.")
    lines.extend(
        [
            "",
            "Сначала отмените эти записи в разделе «📅 Записи клиентов».",
        ]
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Записи клиентов
# --------------------------------------------------------------------------- #


def filters_label(on_date: date | None, barber_name: str | None) -> str:
    parts: list[str] = []
    if on_date is not None:
        parts.append(f"дата — {ui.format_date(on_date)}")
    if barber_name is not None:
        parts.append(f"мастер — {barber_name}")
    if not parts:
        return "Фильтры: не заданы."
    return "Фильтры: " + "; ".join(parts) + "."


def bookings_text(
    rows: Sequence[Booking],
    *,
    total: int,
    page: int,
    pages: int,
    filters: str,
) -> str:
    lines = ["📅 Записи клиентов", "", filters]
    if total == 0:
        lines.extend(["", "Записей не найдено."])
        return "\n".join(lines)
    lines.append(f"Всего: {total}.")
    if pages > 1:
        lines.append(page_label(page, pages))
    lines.extend(["", "Нажмите на запись, чтобы открыть карточку."])
    return "\n".join(lines)


def booking_button_label(booking: Booking) -> str:
    local = ui.as_moscow(booking.starts_at)
    mark = ui.status_label(booking.status).split(" ", 1)[0]
    return (
        f"{local.strftime('%d.%m %H:%M')} · "
        f"{booking.barber.name} · {booking.service.name} · {mark}"
    )


def client_label(booking: Booking) -> str:
    name = (booking.user.display_name or "").strip() or "без имени"
    return f"{name} (ID {booking.user.telegram_id})"


def booking_card_text(booking: Booking) -> str:
    return "\n".join(
        [
            f"📅 Запись №{booking.id}",
            "",
            f"👤 Клиент: {client_label(booking)}",
            *ui.booking_lines(booking),
        ]
    )


def cancel_prompt_text(booking: Booking) -> str:
    return "\n".join(
        [
            "❓ Отменить запись клиента?",
            "",
            *ui.booking_lines(booking),
            "",
            (
                "Администратор может отменить запись в любое время, "
                "включая последние 2 часа до начала."
            ),
            ("Отмена необратима: запись останется в истории со статусом «отменена»."),
        ]
    )


def cancelled_text(booking: Booking) -> str:
    return "\n".join(["✅ Запись отменена.", "", *ui.booking_lines(booking)])


__all__ = [
    "ACCESS_DENIED",
    "ADD_BARBER_NAME_PROMPT",
    "ADD_SERVICE_DURATION_PROMPT",
    "ADD_SERVICE_NAME_PROMPT",
    "ADD_SERVICE_PRICE_PROMPT",
    "BARBER_DISABLED_NOTE",
    "BARBER_ENABLED_NOTE",
    "BARBER_NAME_TAKEN",
    "BOOKINGS_DATE_PROMPT",
    "BOOKING_ALREADY_CANCELLED",
    "BOOKING_COMPLETED",
    "CONFLICT_LIMIT",
    "DATABASE_ERROR",
    "EDIT_SERVICE_PROMPTS",
    "FILTER_BARBER_PROMPT",
    "INVALID_DATE",
    "INVALID_DURATION",
    "INVALID_HOURS",
    "INVALID_NAME",
    "INVALID_PERIOD",
    "INVALID_PRICE",
    "NOTE_BARBER_CREATED",
    "NOTE_BOOKING_CANCELLED",
    "NOTE_FILTERS_RESET",
    "NOTE_SAVED",
    "NOTE_SERVICE_CREATED",
    "NOTE_TIME_OFF_ADDED",
    "NOTE_TIME_OFF_REMOVED",
    "NOT_FOUND",
    "PANEL_TEXT",
    "PERIOD_IN_PAST",
    "PERIOD_OVERLAP",
    "SERVICE_DISABLED_NOTE",
    "SERVICE_ENABLED_NOTE",
    "SERVICE_NAME_TAKEN",
    "SESSION_EXPIRED",
    "TEXT_ONLY",
    "TIME_OFF_PROMPT",
    "WEEKDAYS",
    "WORKING_HOURS_PROMPT",
    "barber_button_label",
    "barber_card_text",
    "barber_choice_label",
    "barber_status",
    "barbers_text",
    "booking_button_label",
    "booking_card_text",
    "bookings_text",
    "cancel_prompt_text",
    "cancelled_text",
    "client_label",
    "filters_label",
    "hours_label",
    "page_label",
    "schedule_button_label",
    "schedule_conflict_text",
    "schedule_text",
    "service_button_label",
    "service_card_text",
    "service_status",
    "services_text",
    "time_off_button_label",
    "time_off_period",
    "time_off_text",
    "weekday_name",
    "weekday_short",
]
