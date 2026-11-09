"""Inline-клавиатуры административной панели.

Кнопки используют только типизированные callback-данные из
:mod:`barberbot.admin.callbacks`; права администратора в callback-данных не
передаются и всегда проверяются заново по Telegram ID отправителя.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from barberbot import callbacks as cb
from barberbot.admin import callbacks as admin_cb
from barberbot.admin import texts
from barberbot.db.models import (
    Barber,
    BarberTimeOff,
    BarberWorkingHours,
    Booking,
    Service,
)


def _button(text: str, data: CallbackData) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def _main_menu_row() -> list[InlineKeyboardButton]:
    return [_button("🏠 Главное меню", cb.NavMainCB())]


def _back_row(target: CallbackData) -> list[InlineKeyboardButton]:
    return [_button("⬅️ Назад", target), *_main_menu_row()]


def _arrows(
    page: int, pages: int, factory: Callable[[int], CallbackData]
) -> list[list[InlineKeyboardButton]]:
    if pages <= 1:
        return []
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(_button("◀️", factory(page - 1)))
    if page < pages - 1:
        row.append(_button("▶️", factory(page + 1)))
    return [row] if row else []


def panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("💈 Услуги", admin_cb.AdminServicesCB())],
            [_button("👤 Барберы", admin_cb.AdminBarbersCB())],
            [_button("📅 Записи клиентов", admin_cb.AdminBookingsCB())],
            _main_menu_row(),
        ]
    )


def prompt_keyboard(target: CallbackData) -> InlineKeyboardMarkup:
    """Клавиатура шага ввода текста: только отмена и главное меню."""
    return InlineKeyboardMarkup(inline_keyboard=[_back_row(target)])


# --------------------------------------------------------------------------- #
# Услуги
# --------------------------------------------------------------------------- #


def services_keyboard(
    services: Sequence[Service], *, page: int, pages: int
) -> InlineKeyboardMarkup:
    rows = [
        [
            _button(
                texts.service_button_label(service),
                admin_cb.AdminServiceCB(service_id=service.id),
            )
        ]
        for service in services
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *rows,
            *_arrows(page, pages, lambda value: admin_cb.AdminServicesCB(page=value)),
            [_button("➕ Добавить услугу", admin_cb.AdminServiceAddCB())],
            _back_row(admin_cb.AdminPanelCB()),
        ]
    )


def service_card_keyboard(service: Service) -> InlineKeyboardMarkup:
    service_id = service.id
    rows = [
        [
            _button(
                "✏️ Название",
                admin_cb.AdminServiceEditCB(service_id=service_id, field="name"),
            ),
            _button(
                "💰 Цена",
                admin_cb.AdminServiceEditCB(service_id=service_id, field="price"),
            ),
        ],
        [
            _button(
                "⏱ Длительность",
                admin_cb.AdminServiceEditCB(service_id=service_id, field="duration"),
            )
        ],
        [
            _button(
                "🟢 Включить" if not service.is_active else "🔴 Отключить",
                admin_cb.AdminServiceToggleCB(service_id=service_id),
            )
        ],
        _back_row(admin_cb.AdminServicesCB()),
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------- #
# Барберы
# --------------------------------------------------------------------------- #


def barbers_keyboard(
    barbers: Sequence[Barber],
    working_days: dict[int, int],
    *,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    rows = [
        [
            _button(
                texts.barber_button_label(barber, working_days.get(barber.id, 0)),
                admin_cb.AdminBarberCB(barber_id=barber.id),
            )
        ]
        for barber in barbers
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *rows,
            *_arrows(page, pages, lambda value: admin_cb.AdminBarbersCB(page=value)),
            [_button("➕ Добавить мастера", admin_cb.AdminBarberAddCB())],
            _back_row(admin_cb.AdminPanelCB()),
        ]
    )


def barber_card_keyboard(barber: Barber) -> InlineKeyboardMarkup:
    barber_id = barber.id
    rows = [
        [
            _button("🕐 Расписание", admin_cb.AdminScheduleCB(barber_id=barber_id)),
            _button("🚫 Отсутствия", admin_cb.AdminTimeOffCB(barber_id=barber_id)),
        ],
        [
            _button(
                "🟢 Включить" if not barber.is_active else "🔴 Отключить",
                admin_cb.AdminBarberToggleCB(barber_id=barber_id),
            )
        ],
        _back_row(admin_cb.AdminBarbersCB()),
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_keyboard(
    barber: Barber, hours: dict[int, BarberWorkingHours]
) -> InlineKeyboardMarkup:
    rows = [
        [
            _button(
                texts.schedule_button_label(weekday, hours.get(weekday)),
                admin_cb.AdminWeekdayCB(barber_id=barber.id, weekday=weekday),
            )
        ]
        for weekday in range(7)
    ]
    rows.append(_back_row(admin_cb.AdminBarberCB(barber_id=barber.id)))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_off_keyboard(
    barber_id: int,
    rows: Sequence[BarberTimeOff],
    *,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    buttons = [
        [
            _button(
                texts.time_off_button_label(row),
                admin_cb.AdminTimeOffRemoveCB(
                    barber_id=barber_id, time_off_id=row.id, page=page
                ),
            )
        ]
        for row in rows
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *buttons,
            *_arrows(
                page,
                pages,
                lambda value: admin_cb.AdminTimeOffCB(barber_id=barber_id, page=value),
            ),
            [
                _button(
                    "➕ Добавить период",
                    admin_cb.AdminTimeOffAddCB(barber_id=barber_id),
                )
            ],
            _back_row(admin_cb.AdminBarberCB(barber_id=barber_id)),
        ]
    )


# --------------------------------------------------------------------------- #
# Записи клиентов
# --------------------------------------------------------------------------- #


def bookings_keyboard(
    bookings: Sequence[Booking],
    *,
    page: int,
    pages: int,
    has_filters: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            _button(
                texts.booking_button_label(booking),
                admin_cb.AdminBookingCB(booking_id=booking.id),
            )
        ]
        for booking in bookings
    ]
    rows.extend(
        _arrows(page, pages, lambda value: admin_cb.AdminBookingsCB(page=value))
    )
    rows.append(
        [
            _button("📅 Фильтр по дате", admin_cb.AdminFilterDateCB()),
            _button("👤 Фильтр по мастеру", admin_cb.AdminFilterBarberCB()),
        ]
    )
    if has_filters:
        rows.append([_button("♻️ Сбросить фильтры", admin_cb.AdminFilterResetCB())])
    rows.append(_back_row(admin_cb.AdminPanelCB()))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bookings_barber_filter_keyboard(
    barbers: Sequence[Barber], *, current_barber_id: int | None
) -> InlineKeyboardMarkup:
    all_mark = "👉 " if current_barber_id is None else ""
    rows = [
        [
            _button(
                all_mark + "Все мастера",
                admin_cb.AdminFilterBarberSetCB(barber_id=0),
            )
        ]
    ]
    rows.extend(
        [
            _button(
                ("👉 " if current_barber_id == barber.id else "")
                + texts.barber_choice_label(barber),
                admin_cb.AdminFilterBarberSetCB(barber_id=barber.id),
            )
        ]
        for barber in barbers
    )
    rows.append(_back_row(admin_cb.AdminBookingsCB()))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_card_keyboard(
    booking: Booking, *, cancellable: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if cancellable:
        rows.append(
            [
                _button(
                    "❌ Отменить запись",
                    admin_cb.AdminBookingCancelCB(booking_id=booking.id),
                )
            ]
        )
    rows.append(_back_row(admin_cb.AdminBookingsCB()))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_cancel_confirm_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(
                    "✅ Да, отменить",
                    admin_cb.AdminBookingCancelConfirmCB(booking_id=booking_id),
                )
            ],
            [
                _button(
                    "⬅️ Нет, оставить",
                    admin_cb.AdminBookingCB(booking_id=booking_id),
                ),
                *_main_menu_row(),
            ],
        ]
    )


__all__ = [
    "barber_card_keyboard",
    "barbers_keyboard",
    "booking_cancel_confirm_keyboard",
    "booking_card_keyboard",
    "bookings_barber_filter_keyboard",
    "bookings_keyboard",
    "panel_keyboard",
    "prompt_keyboard",
    "schedule_keyboard",
    "service_card_keyboard",
    "services_keyboard",
    "time_off_keyboard",
]
