"""Полный FSM-сценарий записи: услуга → мастер → дата → время → подтверждение.

Вся бизнес-логика (рабочие часы, занятость, длительность, защита от
пересечений) остаётся в :class:`barberbot.booking.service.BookingService`.
Обработчики только показывают данные, проверяют, что callback относится к
текущему шагу FSM, и передают окончательное решение сервису.

``callback_data`` — недоверенный ввод: идентификаторы, дата и время из него
перепроверяются по актуальным данным БД перед любым действием.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from math import ceil

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from barberbot import fsm, ui
from barberbot.booking.errors import (
    BarberUnavailable,
    BookingError,
    DatabaseUnavailable,
    InvalidBookingTime,
    ServiceUnavailable,
    SlotUnavailable,
)
from barberbot.booking.service import BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.callbacks import (
    BarberCB,
    ConfirmCB,
    DateCB,
    DatesPageCB,
    MenuBookCB,
    NavBarbersCB,
    NavDatesCB,
    NavServicesCB,
    NavTimesCB,
    ServiceCB,
    TimeCB,
)
from barberbot.db.models import Barber, Service
from barberbot.fsm import BookingFlow
from barberbot.handlers.render import render
from barberbot.keyboards import (
    DATE_PAGE_SIZE,
    barber_choice_keyboard,
    booking_created_keyboard,
    confirm_keyboard,
    dates_keyboard,
    empty_barbers_keyboard,
    empty_dates_keyboard,
    empty_times_keyboard,
    main_menu_keyboard,
    service_choice_keyboard,
    times_keyboard,
)
from barberbot.messages import (
    BARBER_GONE,
    CONFIRM_RETRY,
    DATE_GONE,
    NO_BARBERS,
    NO_DATES,
    NO_SERVICES,
    NO_SLOTS,
    SERVICE_GONE,
    SESSION_EXPIRED,
    SLOT_GONE,
    barber_choice_text,
    booking_created_text,
    confirmation_text,
    dates_text,
    service_choice_text,
    times_text,
)

logger = logging.getLogger(__name__)


def _find_service(services: list[Service], service_id: int) -> Service | None:
    return next((row for row in services if row.id == service_id), None)


def _find_barber(barbers: list[Barber], barber_id: int) -> Barber | None:
    return next((row for row in barbers if row.id == barber_id), None)


def _pages(total: int, page_size: int = DATE_PAGE_SIZE) -> int:
    return max(1, ceil(total / page_size))


def _slot_from_epoch(seconds: int) -> datetime | None:
    """Время начала из callback-данных; диапазон проверяется исключениями."""
    try:
        return datetime.fromtimestamp(seconds, tz=MOSCOW)
    except OverflowError, OSError, ValueError:
        return None


async def _fail(callback: CallbackQuery, state: FSMContext, text: str) -> None:
    """Сообщить о проблеме, сбросить сценарий и показать главное меню."""
    await callback.answer(text, show_alert=True)
    await state.clear()
    await render(callback, text, main_menu_keyboard())


async def _read_ids(
    state: FSMContext,
) -> tuple[int, int] | None:
    data = await state.get_data()
    service_id = fsm.read_int(data, fsm.SERVICE_ID)
    barber_id = fsm.read_int(data, fsm.BARBER_ID)
    if service_id is None or barber_id is None:
        return None
    return service_id, barber_id


# --------------------------------------------------------------------------- #
# Шаги сценария
# --------------------------------------------------------------------------- #


async def start_booking(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Начать запись: показать активные услуги и перейти к их выбору."""
    await callback.answer()
    await state.clear()
    try:
        services = await booking_service.list_active_services()
    except DatabaseUnavailable as error:
        await render(callback, str(error), main_menu_keyboard())
        return
    if not services:
        await render(callback, NO_SERVICES, main_menu_keyboard())
        return
    await state.set_state(BookingFlow.service)
    await render(
        callback, service_choice_text(services), service_choice_keyboard(services)
    )


async def choose_service(
    callback: CallbackQuery,
    callback_data: ServiceCB,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Сохранить услугу и показать активных мастеров."""
    try:
        services = await booking_service.list_active_services()
        service = _find_service(services, callback_data.service_id)
        if service is None:
            await callback.answer(SERVICE_GONE, show_alert=True)
            await state.set_state(BookingFlow.service)
            await state.set_data({})
            await render(
                callback,
                service_choice_text(services),
                service_choice_keyboard(services),
            )
            return
        barbers = await booking_service.list_active_barbers()
    except DatabaseUnavailable as error:
        await _fail(callback, state, str(error))
        return

    await callback.answer()
    await state.set_data({fsm.SERVICE_ID: service.id})
    await state.set_state(BookingFlow.barber)
    if not barbers:
        await render(callback, NO_BARBERS, empty_barbers_keyboard())
        return
    await render(callback, barber_choice_text(barbers), barber_choice_keyboard(barbers))


async def choose_barber(
    callback: CallbackQuery,
    callback_data: BarberCB,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Сохранить мастера и показать доступные даты (с пагинацией)."""
    data = await state.get_data()
    service_id = fsm.read_int(data, fsm.SERVICE_ID)
    if service_id is None:
        await _fail(callback, state, SESSION_EXPIRED)
        return

    try:
        barbers = await booking_service.list_active_barbers()
        barber = _find_barber(barbers, callback_data.barber_id)
        if barber is None:
            await callback.answer(BARBER_GONE, show_alert=True)
            await render(
                callback, barber_choice_text(barbers), barber_choice_keyboard(barbers)
            )
            return
        dates = await booking_service.available_dates(
            service_id=service_id, barber_id=barber.id
        )
    except BookingError as error:
        await _fail(callback, state, str(error))
        return

    await callback.answer()
    await state.set_data(
        {
            fsm.SERVICE_ID: service_id,
            fsm.BARBER_ID: barber.id,
            fsm.DATES_PAGE: 0,
        }
    )
    await state.set_state(BookingFlow.date)
    if not dates:
        await render(callback, NO_DATES, empty_dates_keyboard())
        return
    await render(
        callback,
        dates_text(dates, 0, _pages(len(dates))),
        dates_keyboard(dates, 0),
    )


async def paginate_dates(
    callback: CallbackQuery,
    callback_data: DatesPageCB,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Показать другую страницу доступных дат с актуальными данными."""
    ids = await _read_ids(state)
    if ids is None:
        await _fail(callback, state, SESSION_EXPIRED)
        return
    service_id, barber_id = ids

    try:
        dates = await booking_service.available_dates(
            service_id=service_id, barber_id=barber_id
        )
    except BookingError as error:
        await _fail(callback, state, str(error))
        return

    pages = _pages(len(dates))
    page = min(max(callback_data.page, 0), pages - 1)
    await callback.answer()
    await state.update_data({fsm.DATES_PAGE: page})
    if not dates:
        await render(callback, NO_DATES, empty_dates_keyboard())
        return
    await render(callback, dates_text(dates, page, pages), dates_keyboard(dates, page))


async def choose_date(
    callback: CallbackQuery,
    callback_data: DateCB,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Проверить дату и показать свободное время с шагом 30 минут."""
    ids = await _read_ids(state)
    if ids is None:
        await _fail(callback, state, SESSION_EXPIRED)
        return
    service_id, barber_id = ids
    try:
        day = date.fromisoformat(callback_data.day)
    except ValueError:
        day = None

    try:
        dates = await booking_service.available_dates(
            service_id=service_id, barber_id=barber_id
        )
        slots = (
            await booking_service.available_slots(
                service_id=service_id, barber_id=barber_id, on_date=day
            )
            if day is not None and day in dates
            else None
        )
    except BookingError as error:
        await _fail(callback, state, str(error))
        return

    if day is None or slots is None:
        await callback.answer(DATE_GONE, show_alert=True)
        await state.set_state(BookingFlow.date)
        await state.update_data({fsm.DATES_PAGE: 0})
        if not dates:
            await render(callback, NO_DATES, empty_dates_keyboard())
            return
        await render(
            callback,
            dates_text(dates, 0, _pages(len(dates))),
            dates_keyboard(dates, 0),
        )
        return

    await callback.answer()
    await state.update_data({fsm.DAY: fsm.write_day(day)})
    await state.set_state(BookingFlow.time)
    if not slots:
        await render(callback, NO_SLOTS, empty_times_keyboard())
        return
    await render(callback, times_text(day), times_keyboard(slots))


async def choose_time(
    callback: CallbackQuery,
    callback_data: TimeCB,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Проверить время и показать итоговую информацию для подтверждения."""
    ids = await _read_ids(state)
    data = await state.get_data()
    day = fsm.read_day(data)
    if ids is None or day is None:
        await _fail(callback, state, SESSION_EXPIRED)
        return
    service_id, barber_id = ids

    try:
        slots = await booking_service.available_slots(
            service_id=service_id, barber_id=barber_id, on_date=day
        )
        services = await booking_service.list_active_services()
        barbers = await booking_service.list_active_barbers()
    except BookingError as error:
        await _fail(callback, state, str(error))
        return

    start = _slot_from_epoch(callback_data.start)
    service = _find_service(services, service_id)
    barber = _find_barber(barbers, barber_id)

    if start is None or start not in slots:
        await callback.answer(SLOT_GONE, show_alert=True)
        await state.set_state(BookingFlow.time)
        if slots:
            await render(callback, times_text(day), times_keyboard(slots))
        else:
            await render(callback, NO_SLOTS, empty_times_keyboard())
        return

    if service is None:
        await _fail(callback, state, SERVICE_GONE)
        return
    if barber is None:
        await _fail(callback, state, BARBER_GONE)
        return

    await callback.answer()
    await state.update_data({fsm.START_AT: fsm.write_start(start)})
    await state.set_state(BookingFlow.confirm)
    await render(
        callback,
        confirmation_text(service=service, barber=barber, starts_at=start),
        confirm_keyboard(),
    )


async def confirm_booking(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Создать запись после окончательного подтверждения.

    ``BookingService.create_booking()`` заново проверяет услугу, мастера и
    время и опирается на exclusion constraint PostgreSQL, поэтому повторное
    нажатие не может создать вторую запись на тот же слот.
    """
    data = await state.get_data()
    service_id = fsm.read_int(data, fsm.SERVICE_ID)
    barber_id = fsm.read_int(data, fsm.BARBER_ID)
    day = fsm.read_day(data)
    start = fsm.read_start(data)
    if (
        service_id is None
        or barber_id is None
        or day is None
        or start is None
        or ui.as_moscow(start).date() != day
    ):
        await _fail(callback, state, SESSION_EXPIRED)
        return

    display_name = callback.from_user.full_name.strip()[:255] or None
    try:
        booking = await booking_service.create_booking(
            telegram_id=callback.from_user.id,
            barber_id=barber_id,
            service_id=service_id,
            starts_at=start,
            display_name=display_name,
        )
    except SlotUnavailable as error:
        await callback.answer(str(error), show_alert=True)
        await _refresh_times(
            callback, state, booking_service, service_id, barber_id, day
        )
        return
    except DatabaseUnavailable as error:
        await callback.answer(str(error), show_alert=True)
        await render(callback, f"{error}\n\n{CONFIRM_RETRY}", confirm_keyboard())
        return
    except (
        ServiceUnavailable,
        BarberUnavailable,
        InvalidBookingTime,
    ) as error:
        await _fail(callback, state, str(error))
        return

    await callback.answer()
    await state.clear()
    await render(callback, booking_created_text(booking), booking_created_keyboard())


async def _refresh_times(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    service_id: int,
    barber_id: int,
    day: date,
) -> None:
    """Обновить свободное время после конфликта бронирования."""
    try:
        slots = await booking_service.available_slots(
            service_id=service_id, barber_id=barber_id, on_date=day
        )
    except BookingError as error:
        await state.clear()
        await render(callback, str(error), main_menu_keyboard())
        return
    await state.update_data(
        {
            fsm.SERVICE_ID: service_id,
            fsm.BARBER_ID: barber_id,
            fsm.DAY: fsm.write_day(day),
        }
    )
    await state.set_state(BookingFlow.time)
    if not slots:
        await render(callback, NO_SLOTS, empty_times_keyboard())
        return
    await render(callback, times_text(day), times_keyboard(slots))


# --------------------------------------------------------------------------- #
# Возврат назад
# --------------------------------------------------------------------------- #


async def back_to_services(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Вернуться к выбору услуги, забыв выбранного мастера и время."""
    try:
        services = await booking_service.list_active_services()
    except DatabaseUnavailable as error:
        await _fail(callback, state, str(error))
        return
    await callback.answer()
    await state.set_data({})
    await state.set_state(BookingFlow.service)
    if not services:
        await render(callback, NO_SERVICES, main_menu_keyboard())
        return
    await render(
        callback, service_choice_text(services), service_choice_keyboard(services)
    )


async def back_to_barbers(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Вернуться к выбору мастера, забыв дату и время."""
    data = await state.get_data()
    service_id = fsm.read_int(data, fsm.SERVICE_ID)
    if service_id is None:
        await _fail(callback, state, SESSION_EXPIRED)
        return
    try:
        barbers = await booking_service.list_active_barbers()
    except BookingError as error:
        await _fail(callback, state, str(error))
        return
    await callback.answer()
    await state.set_data({fsm.SERVICE_ID: service_id})
    await state.set_state(BookingFlow.barber)
    if not barbers:
        await render(callback, NO_BARBERS, empty_barbers_keyboard())
        return
    await render(callback, barber_choice_text(barbers), barber_choice_keyboard(barbers))


async def back_to_dates(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Вернуться к выбору даты, забыв выбранное время."""
    ids = await _read_ids(state)
    data = await state.get_data()
    page = fsm.read_page(data)
    if ids is None:
        await _fail(callback, state, SESSION_EXPIRED)
        return
    service_id, barber_id = ids
    try:
        dates = await booking_service.available_dates(
            service_id=service_id, barber_id=barber_id
        )
    except BookingError as error:
        await _fail(callback, state, str(error))
        return

    pages = _pages(len(dates))
    page = min(page, pages - 1)
    await callback.answer()
    await state.set_data(
        {
            fsm.SERVICE_ID: service_id,
            fsm.BARBER_ID: barber_id,
            fsm.DATES_PAGE: page,
        }
    )
    await state.set_state(BookingFlow.date)
    if not dates:
        await render(callback, NO_DATES, empty_dates_keyboard())
        return
    await render(callback, dates_text(dates, page, pages), dates_keyboard(dates, page))


async def back_to_times(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Вернуться к выбору времени, не создавая запись."""
    ids = await _read_ids(state)
    data = await state.get_data()
    day = fsm.read_day(data)
    if ids is None or day is None:
        await _fail(callback, state, SESSION_EXPIRED)
        return
    service_id, barber_id = ids
    try:
        slots = await booking_service.available_slots(
            service_id=service_id, barber_id=barber_id, on_date=day
        )
    except BookingError as error:
        await _fail(callback, state, str(error))
        return
    await callback.answer()
    await state.set_state(BookingFlow.time)
    if not slots:
        await render(callback, NO_SLOTS, empty_times_keyboard())
        return
    await render(callback, times_text(day), times_keyboard(slots))


def build_router() -> Router:
    """Роутер FSM-сценария; каждый callback разрешён только из своего шага."""
    router = Router(name="booking")
    router.callback_query.register(start_booking, MenuBookCB.filter())
    router.callback_query.register(
        choose_service,
        ServiceCB.filter(),
        StateFilter(BookingFlow.service),
    )
    router.callback_query.register(
        choose_barber,
        BarberCB.filter(),
        StateFilter(BookingFlow.barber),
    )
    router.callback_query.register(
        paginate_dates,
        DatesPageCB.filter(),
        StateFilter(BookingFlow.date),
    )
    router.callback_query.register(
        choose_date,
        DateCB.filter(),
        StateFilter(BookingFlow.date),
    )
    router.callback_query.register(
        choose_time,
        TimeCB.filter(),
        StateFilter(BookingFlow.time),
    )
    router.callback_query.register(
        confirm_booking,
        ConfirmCB.filter(),
        StateFilter(BookingFlow.confirm),
    )
    router.callback_query.register(
        back_to_services,
        NavServicesCB.filter(),
        StateFilter(BookingFlow.barber),
    )
    router.callback_query.register(
        back_to_barbers,
        NavBarbersCB.filter(),
        StateFilter(BookingFlow.date),
    )
    router.callback_query.register(
        back_to_dates,
        NavDatesCB.filter(),
        StateFilter(BookingFlow.time),
    )
    router.callback_query.register(
        back_to_times,
        NavTimesCB.filter(),
        StateFilter(BookingFlow.confirm),
    )
    return router


__all__ = ["build_router"]
