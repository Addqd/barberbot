"""Состояния административных форм и ключи их данных.

Используется штатное хранилище aiogram. Состояние может потеряться при
перезапуске процесса, поэтому административные обработчики не полагаются на
его наличие: при отсутствии данных раздел открывается заново с понятным
сообщением.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

#: Ключи данных административных форм.
SERVICE_ID = "admin_service_id"
BARBER_ID = "admin_barber_id"
WEEKDAY = "admin_weekday"
EDIT_FIELD = "admin_edit_field"
NEW_NAME = "admin_new_name"
NEW_PRICE = "admin_new_price"
NEW_DURATION = "admin_new_duration"
FILTER_DAY = "admin_filter_day"
FILTER_BARBER = "admin_filter_barber"
FILTER_BARBER_NAME = "admin_filter_barber_name"


class AdminFlow(StatesGroup):
    """Ввод данных администратором: только текстовые формы."""

    service_add_name = State()
    service_add_price = State()
    service_add_duration = State()
    service_edit_value = State()
    barber_add_name = State()
    working_hours = State()
    time_off_add = State()
    bookings_date_filter = State()


__all__ = [
    "BARBER_ID",
    "EDIT_FIELD",
    "FILTER_BARBER",
    "FILTER_BARBER_NAME",
    "FILTER_DAY",
    "NEW_DURATION",
    "NEW_NAME",
    "NEW_PRICE",
    "SERVICE_ID",
    "WEEKDAY",
    "AdminFlow",
]
