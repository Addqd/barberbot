"""Типизированные callback-данные административной панели.

``callback_data`` приходит от Telegram и является недоверенным вводом:
идентификаторы передаются как ``int``, поле правки услуги — как
``Literal``. Неверный префикс, количество полей или тип не проходят фильтр,
поэтому такие нажатия разбирает fallback-обработчик.

Права администратора никогда не передаются в callback-данных: они всегда
проверяются по ``event.from_user.id``.
"""

from __future__ import annotations

from typing import Literal

from aiogram.filters.callback_data import CallbackData

ServiceField = Literal["name", "price", "duration"]


class AdminPanelCB(CallbackData, prefix="adm_panel"):
    """Открыть главную страницу админ-панели."""


class AdminServicesCB(CallbackData, prefix="adm_services"):
    """Список услуг (включая отключённые)."""

    page: int = 0


class AdminServiceCB(CallbackData, prefix="adm_service"):
    """Карточка услуги."""

    service_id: int


class AdminServiceToggleCB(CallbackData, prefix="adm_service_toggle"):
    """Включить или отключить услугу."""

    service_id: int


class AdminServiceEditCB(CallbackData, prefix="adm_service_edit"):
    """Начать правку поля услуги."""

    service_id: int
    field: ServiceField


class AdminServiceAddCB(CallbackData, prefix="adm_service_add"):
    """Начать добавление услуги."""


class AdminBarbersCB(CallbackData, prefix="adm_barbers"):
    """Список мастеров (включая отключённых)."""

    page: int = 0


class AdminBarberCB(CallbackData, prefix="adm_barber"):
    """Карточка мастера."""

    barber_id: int


class AdminBarberToggleCB(CallbackData, prefix="adm_barber_toggle"):
    """Включить или отключить мастера."""

    barber_id: int


class AdminBarberAddCB(CallbackData, prefix="adm_barber_add"):
    """Начать добавление мастера."""


class AdminScheduleCB(CallbackData, prefix="adm_schedule"):
    """Недельное расписание мастера."""

    barber_id: int


class AdminWeekdayCB(CallbackData, prefix="adm_weekday"):
    """Изменить рабочие часы дня недели."""

    barber_id: int
    weekday: int


class AdminTimeOffCB(CallbackData, prefix="adm_timeoff"):
    """Список отсутствий мастера."""

    barber_id: int


class AdminTimeOffAddCB(CallbackData, prefix="adm_timeoff_add"):
    """Добавить период отсутствия."""

    barber_id: int


class AdminTimeOffRemoveCB(CallbackData, prefix="adm_timeoff_remove"):
    """Удалить период отсутствия."""

    barber_id: int
    time_off_id: int


class AdminBookingsCB(CallbackData, prefix="adm_bookings"):
    """Список записей клиентов."""

    page: int = 0


class AdminBookingCB(CallbackData, prefix="adm_booking"):
    """Карточка записи клиента."""

    booking_id: int


class AdminBookingCancelCB(CallbackData, prefix="adm_booking_cancel"):
    """Запросить подтверждение отмены записи."""

    booking_id: int


class AdminBookingCancelConfirmCB(CallbackData, prefix="adm_booking_cancel_ok"):
    """Подтвердить отмену записи."""

    booking_id: int


class AdminFilterDateCB(CallbackData, prefix="adm_filter_date"):
    """Задать фильтр по дате."""


class AdminFilterBarberCB(CallbackData, prefix="adm_filter_barber"):
    """Выбрать фильтр по мастеру."""


class AdminFilterBarberSetCB(CallbackData, prefix="adm_filter_barber_set"):
    """Применить фильтр по мастеру; ``barber_id=0`` — все мастера."""

    barber_id: int


class AdminFilterResetCB(CallbackData, prefix="adm_filter_reset"):
    """Сбросить фильтры списка записей."""


__all__ = [
    "AdminBarberAddCB",
    "AdminBarberCB",
    "AdminBarberToggleCB",
    "AdminBarbersCB",
    "AdminBookingCB",
    "AdminBookingCancelCB",
    "AdminBookingCancelConfirmCB",
    "AdminBookingsCB",
    "AdminFilterBarberCB",
    "AdminFilterBarberSetCB",
    "AdminFilterDateCB",
    "AdminFilterResetCB",
    "AdminPanelCB",
    "AdminScheduleCB",
    "AdminServiceAddCB",
    "AdminServiceCB",
    "AdminServiceEditCB",
    "AdminServiceToggleCB",
    "AdminServicesCB",
    "AdminTimeOffAddCB",
    "AdminTimeOffCB",
    "AdminTimeOffRemoveCB",
    "AdminWeekdayCB",
    "ServiceField",
]
