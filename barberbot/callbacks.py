"""Типизированные callback-данные inline-кнопок.

``callback_data`` приходит от Telegram и является недоверенным вводом.
Использование :class:`aiogram.filters.callback_data.CallbackData` даёт строгий
разбор: неверный префикс, количество полей или тип (например, ``int``) не
проходят фильтр, поэтому такие нажатия обрабатывает fallback-обработчик.

Идентификаторы сущностей и номер страницы передаются как ``int``; дата — как
строка ISO (``ГГГГ-ММ-ДД``), время начала — как Unix timestamp. Разделитель
``:`` внутри значений недопустим, поэтому ISO-datetime не используется.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuBookCB(CallbackData, prefix="menu_book"):
    """Открыть сценарий записи."""


class MenuServicesCB(CallbackData, prefix="menu_services"):
    """Открыть раздел «Услуги и цены»."""


class MenuBookingsCB(CallbackData, prefix="menu_bookings"):
    """Открыть раздел «Мои записи»."""


class NavMainCB(CallbackData, prefix="nav_main"):
    """Вернуться в главное меню (с очисткой FSM)."""


class FlowCancelCB(CallbackData, prefix="flow_cancel"):
    """Отменить текущий сценарий записи."""


class NavServicesCB(CallbackData, prefix="nav_services"):
    """Вернуться к выбору услуги."""


class NavBarbersCB(CallbackData, prefix="nav_barbers"):
    """Вернуться к выбору мастера."""


class NavDatesCB(CallbackData, prefix="nav_dates"):
    """Вернуться к выбору даты."""


class NavTimesCB(CallbackData, prefix="nav_times"):
    """Вернуться к выбору времени."""


class NavBookingsCB(CallbackData, prefix="nav_bookings"):
    """Вернуться к списку своих записей."""


class ServiceCB(CallbackData, prefix="svc"):
    service_id: int


class BarberCB(CallbackData, prefix="brb"):
    barber_id: int


class DatesPageCB(CallbackData, prefix="dpg"):
    page: int


class DateCB(CallbackData, prefix="day"):
    day: str


class TimeCB(CallbackData, prefix="tm"):
    start: int


class ConfirmCB(CallbackData, prefix="ok"):
    """Подтвердить создание записи."""


class BookingsPageCB(CallbackData, prefix="bpg"):
    page: int


class BookingCB(CallbackData, prefix="bk"):
    booking_id: int


class CancelPromptCB(CallbackData, prefix="cx"):
    booking_id: int


class CancelConfirmCB(CallbackData, prefix="cxok"):
    booking_id: int


__all__ = [
    "BarberCB",
    "BookingCB",
    "BookingsPageCB",
    "CancelConfirmCB",
    "CancelPromptCB",
    "ConfirmCB",
    "DateCB",
    "DatesPageCB",
    "FlowCancelCB",
    "MenuBookCB",
    "MenuBookingsCB",
    "MenuServicesCB",
    "NavBarbersCB",
    "NavBookingsCB",
    "NavDatesCB",
    "NavMainCB",
    "NavServicesCB",
    "NavTimesCB",
    "ServiceCB",
    "TimeCB",
]
