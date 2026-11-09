"""Раздел «📅 Мои записи»: только записи текущего Telegram-пользователя.

Пользователь определяется исключительно по ``event.from_user.id``. Номера
записей из ``callback_data`` перепроверяются по списку собственных записей,
поэтому действие над чужой записью невозможно даже при подмене callback.
Отмена выполняется только через :meth:`BookingService.cancel_booking`.
"""

from __future__ import annotations

import logging
from math import ceil

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from barberbot import messages, ui
from barberbot.booking.errors import BookingError, DatabaseUnavailable
from barberbot.booking.service import MESSAGE_DATABASE, BookingService
from barberbot.callbacks import (
    BookingCB,
    BookingsPageCB,
    CancelConfirmCB,
    CancelPromptCB,
    MenuBookingsCB,
    NavBookingsCB,
)
from barberbot.db.models import Booking, BookingStatus
from barberbot.handlers.render import render
from barberbot.keyboards import (
    BOOKING_PAGE_SIZE,
    booking_detail_keyboard,
    bookings_keyboard,
    cancel_confirmation_keyboard,
    cancelled_keyboard,
    empty_bookings_keyboard,
    main_menu_keyboard,
)

logger = logging.getLogger(__name__)


def _find(bookings: list[Booking], booking_id: int) -> Booking | None:
    return next((row for row in bookings if row.id == booking_id), None)


def _cancel_block_reason(booking: Booking) -> str | None:
    """Понятная причина, по которой кнопка отмены не показывается/не работает."""
    if booking.status is BookingStatus.CANCELLED:
        return messages.CANCEL_ALREADY
    if booking.status is not BookingStatus.CONFIRMED:
        return messages.CANCEL_COMPLETED
    if not ui.is_cancellable(booking):
        return messages.CANCEL_NOT_AVAILABLE
    return None


async def _load(
    booking_service: BookingService, telegram_id: int
) -> list[Booking] | None:
    """Свои записи или ``None`` при ошибке БД (текст ошибки не раскрывается)."""
    try:
        return await booking_service.list_user_bookings(telegram_id)
    except DatabaseUnavailable:
        logger.warning("Не удалось загрузить записи пользователя")
        return None


async def _render_list(
    callback: CallbackQuery, bookings: list[Booking], page: int
) -> None:
    ordered = ui.sort_for_display(bookings)
    if not ordered:
        await render(callback, messages.EMPTY_BOOKINGS, empty_bookings_keyboard())
        return
    pages = max(1, ceil(len(ordered) / BOOKING_PAGE_SIZE))
    current = min(max(page, 0), pages - 1)
    await render(
        callback,
        messages.bookings_list_text(
            ordered[current * BOOKING_PAGE_SIZE : (current + 1) * BOOKING_PAGE_SIZE],
            current,
            pages,
        ),
        bookings_keyboard(ordered, current),
    )


async def _render_booking(callback: CallbackQuery, booking: Booking) -> None:
    await render(
        callback,
        messages.booking_card_text(booking),
        booking_detail_keyboard(
            booking.id, cancellable=_cancel_block_reason(booking) is None
        ),
    )


async def _render_after_error(
    callback: CallbackQuery,
    booking_service: BookingService,
    booking_id: int,
) -> None:
    """Обновить интерфейс после доменной ошибки (callback уже подтверждён)."""
    try:
        bookings = await booking_service.list_user_bookings(callback.from_user.id)
    except DatabaseUnavailable as error:
        await render(callback, str(error), main_menu_keyboard())
        return
    booking = _find(bookings, booking_id)
    if booking is None:
        await _render_list(callback, bookings, 0)
        return
    await _render_booking(callback, booking)


async def show_my_bookings(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Показать список своих записей; незавершённый сценарий сбрасывается."""
    await state.clear()
    bookings = await _load(booking_service, callback.from_user.id)
    if bookings is None:
        await callback.answer(MESSAGE_DATABASE, show_alert=True)
        await render(callback, MESSAGE_DATABASE, main_menu_keyboard())
        return
    await callback.answer()
    await _render_list(callback, bookings, 0)


async def paginate_bookings(
    callback: CallbackQuery,
    callback_data: BookingsPageCB,
    booking_service: BookingService,
) -> None:
    bookings = await _load(booking_service, callback.from_user.id)
    if bookings is None:
        await callback.answer(MESSAGE_DATABASE, show_alert=True)
        await render(callback, MESSAGE_DATABASE, main_menu_keyboard())
        return
    await callback.answer()
    await _render_list(callback, bookings, callback_data.page)


async def show_booking(
    callback: CallbackQuery,
    callback_data: BookingCB,
    booking_service: BookingService,
) -> None:
    """Открыть карточку записи, только если она принадлежит пользователю."""
    bookings = await _load(booking_service, callback.from_user.id)
    if bookings is None:
        await callback.answer(MESSAGE_DATABASE, show_alert=True)
        await render(callback, MESSAGE_DATABASE, main_menu_keyboard())
        return
    booking = _find(bookings, callback_data.booking_id)
    if booking is None:
        await callback.answer(messages.BOOKING_GONE, show_alert=True)
        await _render_list(callback, bookings, 0)
        return
    await callback.answer()
    await _render_booking(callback, booking)


async def ask_cancel(
    callback: CallbackQuery,
    callback_data: CancelPromptCB,
    booking_service: BookingService,
) -> None:
    """Запросить подтверждение отмены подходящей записи."""
    bookings = await _load(booking_service, callback.from_user.id)
    if bookings is None:
        await callback.answer(MESSAGE_DATABASE, show_alert=True)
        await render(callback, MESSAGE_DATABASE, main_menu_keyboard())
        return
    booking = _find(bookings, callback_data.booking_id)
    if booking is None:
        await callback.answer(messages.BOOKING_GONE, show_alert=True)
        await _render_list(callback, bookings, 0)
        return
    reason = _cancel_block_reason(booking)
    if reason is not None:
        await callback.answer(reason, show_alert=True)
        await _render_booking(callback, booking)
        return
    await callback.answer()
    await render(
        callback,
        messages.cancel_prompt_text(booking),
        cancel_confirmation_keyboard(booking.id),
    )


async def perform_cancel(
    callback: CallbackQuery,
    callback_data: CancelConfirmCB,
    booking_service: BookingService,
) -> None:
    """Отменить запись после отдельного подтверждения.

    Повторные нажатия и уже отменённые записи обрабатываются как доменные
    ошибки: интерфейс перерисовывается актуальными данными.
    """
    booking_id = callback_data.booking_id
    bookings = await _load(booking_service, callback.from_user.id)
    if bookings is None:
        await callback.answer(MESSAGE_DATABASE, show_alert=True)
        await render(callback, MESSAGE_DATABASE, main_menu_keyboard())
        return
    booking = _find(bookings, booking_id)
    if booking is None:
        await callback.answer(messages.BOOKING_GONE, show_alert=True)
        await _render_list(callback, bookings, 0)
        return
    reason = _cancel_block_reason(booking)
    if reason is not None:
        await callback.answer(reason, show_alert=True)
        await _render_booking(callback, booking)
        return

    try:
        cancelled = await booking_service.cancel_booking(
            telegram_id=callback.from_user.id, booking_id=booking_id
        )
    except DatabaseUnavailable as error:
        await callback.answer(str(error), show_alert=True)
        await _render_after_error(callback, booking_service, booking_id)
        return
    except BookingError as error:
        await callback.answer(str(error), show_alert=True)
        await _render_after_error(callback, booking_service, booking_id)
        return

    await callback.answer()
    await render(callback, messages.cancelled_text(cancelled), cancelled_keyboard())


def build_router() -> Router:
    router = Router(name="my_bookings")
    router.callback_query.register(show_my_bookings, MenuBookingsCB.filter())
    router.callback_query.register(show_my_bookings, NavBookingsCB.filter())
    router.callback_query.register(paginate_bookings, BookingsPageCB.filter())
    router.callback_query.register(show_booking, BookingCB.filter())
    router.callback_query.register(ask_cancel, CancelPromptCB.filter())
    router.callback_query.register(perform_cancel, CancelConfirmCB.filter())
    return router


__all__ = ["build_router"]
