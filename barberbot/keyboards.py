"""Клавиатуры и callback-данные клиентского интерфейса.

Все кнопки используют типизированные callback-данные из
:mod:`barberbot.callbacks`. Устаревшие кнопки не удаётся «обмануть»: переход
разрешён только из ожидаемого состояния FSM (``StateFilter``).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from math import ceil

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from barberbot import callbacks as cb
from barberbot import ui
from barberbot.db.models import Barber, Booking, Service

#: Сколько дат показывать на одной странице списка.
DATE_PAGE_SIZE = 6

#: Сколько записей показывать на одной странице списка.
BOOKING_PAGE_SIZE = 5


def _button(text: str, data: CallbackData) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню: три раздела, доступные из ``/start``."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("✂️ Записаться", cb.MenuBookCB())],
            [_button("💈 Услуги и цены", cb.MenuServicesCB())],
            [_button("📅 Мои записи", cb.MenuBookingsCB())],
        ]
    )


def _flow_nav(back: CallbackData | None) -> list[list[InlineKeyboardButton]]:
    """Ряд возврата и отмены сценария."""
    first_row = []
    if back is not None:
        first_row.append(_button("⬅️ Назад", back))
    first_row.append(_button("🏠 Главное меню", cb.NavMainCB()))
    return [first_row, [_button("❌ Отменить действие", cb.FlowCancelCB())]]


def service_choice_keyboard(services: Sequence[Service]) -> InlineKeyboardMarkup:
    rows = [
        [_button(ui.service_button(service), cb.ServiceCB(service_id=service.id))]
        for service in services
    ]
    return InlineKeyboardMarkup(inline_keyboard=[*rows, *_flow_nav(None)])


def barber_choice_keyboard(barbers: Sequence[Barber]) -> InlineKeyboardMarkup:
    rows = [
        [_button(barber.name, cb.BarberCB(barber_id=barber.id))] for barber in barbers
    ]
    return InlineKeyboardMarkup(inline_keyboard=[*rows, *_flow_nav(cb.NavServicesCB())])


def empty_barbers_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_flow_nav(cb.NavServicesCB()))


def dates_keyboard(
    dates: Sequence[date], page: int, *, page_size: int = DATE_PAGE_SIZE
) -> InlineKeyboardMarkup:
    """Страница доступных дат: пары кнопок и навигация ◀️/▶️."""
    pages = max(1, ceil(len(dates) / page_size))
    current = min(max(page, 0), pages - 1)
    chunk = dates[current * page_size : (current + 1) * page_size]
    buttons = [
        _button(ui.format_day_short(day), cb.DateCB(day=day.isoformat()))
        for day in chunk
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    if pages > 1:
        arrows = []
        if current > 0:
            arrows.append(_button("◀️", cb.DatesPageCB(page=current - 1)))
        if current < pages - 1:
            arrows.append(_button("▶️", cb.DatesPageCB(page=current + 1)))
        rows.append(arrows)
    return InlineKeyboardMarkup(inline_keyboard=[*rows, *_flow_nav(cb.NavBarbersCB())])


def empty_dates_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_flow_nav(cb.NavBarbersCB()))


def times_keyboard(slots: Sequence[datetime]) -> InlineKeyboardMarkup:
    buttons = [
        _button(
            ui.format_time(slot),
            cb.TimeCB(start=int(slot.timestamp())),
        )
        for slot in slots
    ]
    rows = [buttons[index : index + 4] for index in range(0, len(buttons), 4)]
    return InlineKeyboardMarkup(inline_keyboard=[*rows, *_flow_nav(cb.NavDatesCB())])


def empty_times_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_flow_nav(cb.NavDatesCB()))


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("✅ Подтвердить", cb.ConfirmCB())],
            *_flow_nav(cb.NavTimesCB()),
        ]
    )


def booking_created_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("📅 Мои записи", cb.MenuBookingsCB())],
            [_button("🏠 Главное меню", cb.NavMainCB())],
        ]
    )


def empty_bookings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("✂️ Записаться", cb.MenuBookCB())],
            [_button("🏠 Главное меню", cb.NavMainCB())],
        ]
    )


def bookings_keyboard(
    bookings: Sequence[Booking],
    page: int,
    *,
    page_size: int = BOOKING_PAGE_SIZE,
) -> InlineKeyboardMarkup:
    pages = max(1, ceil(len(bookings) / page_size))
    current = min(max(page, 0), pages - 1)
    chunk = bookings[current * page_size : (current + 1) * page_size]
    rows = [
        [_button(ui.booking_row_label(booking), cb.BookingCB(booking_id=booking.id))]
        for booking in chunk
    ]
    if pages > 1:
        arrows = []
        if current > 0:
            arrows.append(_button("◀️", cb.BookingsPageCB(page=current - 1)))
        if current < pages - 1:
            arrows.append(_button("▶️", cb.BookingsPageCB(page=current + 1)))
        rows.append(arrows)
    rows.append([_button("🏠 Главное меню", cb.NavMainCB())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_detail_keyboard(
    booking_id: int, *, cancellable: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if cancellable:
        rows.append(
            [_button("❌ Отменить запись", cb.CancelPromptCB(booking_id=booking_id))]
        )
    rows.append([_button("⬅️ К списку", cb.NavBookingsCB())])
    rows.append([_button("🏠 Главное меню", cb.NavMainCB())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_confirmation_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("✅ Да, отменить", cb.CancelConfirmCB(booking_id=booking_id))],
            [_button("⬅️ Нет, оставить", cb.BookingCB(booking_id=booking_id))],
            [_button("🏠 Главное меню", cb.NavMainCB())],
        ]
    )


def cancelled_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("📅 Мои записи", cb.NavBookingsCB())],
            [_button("🏠 Главное меню", cb.NavMainCB())],
        ]
    )


__all__ = [
    "BOOKING_PAGE_SIZE",
    "DATE_PAGE_SIZE",
    "barber_choice_keyboard",
    "booking_created_keyboard",
    "booking_detail_keyboard",
    "bookings_keyboard",
    "cancel_confirmation_keyboard",
    "cancelled_keyboard",
    "confirm_keyboard",
    "dates_keyboard",
    "empty_barbers_keyboard",
    "empty_bookings_keyboard",
    "empty_dates_keyboard",
    "empty_times_keyboard",
    "main_menu_keyboard",
    "service_choice_keyboard",
    "times_keyboard",
]
