"""Интеграционные тесты «Мои записи» и отмены на реальной тестовой БД."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher

from barberbot import messages
from barberbot.booking.errors import DatabaseUnavailable
from barberbot.booking.service import MESSAGE_DATABASE, MESSAGE_TOO_LATE, BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.callbacks import (
    BookingCB,
    BookingsPageCB,
    CancelConfirmCB,
    CancelPromptCB,
    MenuBookingsCB,
)
from barberbot.db.models import BookingStatus

from .chat import Chat
from .conftest import FakeSession


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, 7, hour, minute, tzinfo=MOSCOW)


def chat_for(
    dispatcher: Dispatcher, bot: Bot, session: FakeSession, user_id: int
) -> Chat:
    return Chat(dispatcher, bot, session, user_id=user_id)


async def make_booking(
    booking_service: BookingService,
    factory: Any,
    *,
    telegram_id: int,
    hour: int = 12,
) -> Any:
    barber = await factory.barber()
    service = await factory.service()
    return await booking_service.create_booking(
        telegram_id=telegram_id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(hour),
    )


@pytest.mark.asyncio
async def test_my_bookings_shows_only_own_records(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    user_a = factory.telegram_id()
    user_b = factory.telegram_id()
    booking_a = await make_booking(booking_service, factory, telegram_id=user_a)
    booking_b = await make_booking(booking_service, factory, telegram_id=user_b)

    chat_a = chat_for(live_dispatcher, bot, fake_session, user_a)
    await chat_a.press(MenuBookingsCB().pack())

    assert booking_a.service.name in chat_a.text
    assert booking_b.service.name not in chat_a.text

    chat_b = chat_for(live_dispatcher, bot, fake_session, user_b)
    await chat_b.press(MenuBookingsCB().pack())

    assert booking_b.service.name in chat_b.text
    assert booking_a.service.name not in chat_b.text


@pytest.mark.asyncio
async def test_foreign_booking_cannot_be_opened_or_cancelled(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    owner = factory.telegram_id()
    stranger = factory.telegram_id()
    booking = await make_booking(booking_service, factory, telegram_id=owner)
    chat = chat_for(live_dispatcher, bot, fake_session, stranger)

    await chat.press(MenuBookingsCB().pack())
    chat.reset()
    await chat.press(BookingCB(booking_id=booking.id).pack())
    assert chat.answers[0].text == messages.BOOKING_GONE

    chat.reset()
    await chat.press(CancelConfirmCB(booking_id=booking.id).pack())
    assert chat.answers[0].text == messages.BOOKING_GONE

    bookings = await booking_service.list_user_bookings(owner)
    assert bookings[0].status is BookingStatus.CONFIRMED


@pytest.mark.asyncio
async def test_cancel_requires_confirmation_and_works_once(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    telegram_id = factory.telegram_id()
    booking = await make_booking(booking_service, factory, telegram_id=telegram_id)
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await chat.press(MenuBookingsCB().pack())
    await chat.press(BookingCB(booking_id=booking.id).pack())
    assert "Подтверждена" in chat.text
    buttons = [
        button.text
        for row in chat.edits[-1].reply_markup.inline_keyboard
        for button in row
    ]
    assert "❌ Отменить запись" in buttons

    await chat.press(CancelPromptCB(booking_id=booking.id).pack())
    assert "Отменить запись?" in chat.text
    assert await booking_service.list_user_bookings(telegram_id) != []

    chat.reset()
    await chat.press(CancelConfirmCB(booking_id=booking.id).pack())
    assert "Запись отменена" in chat.text
    assert chat.answers[-1].text is None

    bookings = await booking_service.list_user_bookings(telegram_id)
    assert bookings[0].status is BookingStatus.CANCELLED

    # Повторное нажатие по уже отменённой записи.
    chat.reset()
    await chat.press(CancelConfirmCB(booking_id=booking.id).pack())
    assert chat.answers[0].text == messages.CANCEL_ALREADY
    bookings = await booking_service.list_user_bookings(telegram_id)
    assert bookings[0].status is BookingStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_is_rejected_by_two_hour_deadline(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    telegram_id = factory.telegram_id()
    # Фиксированное «сейчас» сервиса — 08:00, до записи ровно один час.
    booking = await make_booking(
        booking_service, factory, telegram_id=telegram_id, hour=9
    )
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await chat.press(MenuBookingsCB().pack())
    await chat.press(BookingCB(booking_id=booking.id).pack())
    await chat.press(CancelPromptCB(booking_id=booking.id).pack())

    chat.reset()
    await chat.press(CancelConfirmCB(booking_id=booking.id).pack())

    assert chat.answers[0].text == MESSAGE_TOO_LATE
    assert "Подтверждена" in chat.text
    bookings = await booking_service.list_user_bookings(telegram_id)
    assert bookings[0].status is BookingStatus.CONFIRMED


@pytest.mark.asyncio
async def test_completed_booking_cannot_be_cancelled(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    telegram_id = factory.telegram_id()
    user = await factory.user(telegram_id=telegram_id)
    barber = await factory.barber()
    service = await factory.service()
    booking = await factory.booking(
        user_id=user.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(13),
        status=BookingStatus.COMPLETED,
    )
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await chat.press(MenuBookingsCB().pack())
    await chat.press(BookingCB(booking_id=booking.id).pack())
    buttons = [
        button.text
        for row in chat.edits[-1].reply_markup.inline_keyboard
        for button in row
    ]
    assert "❌ Отменить запись" not in buttons

    chat.reset()
    await chat.press(CancelConfirmCB(booking_id=booking.id).pack())
    assert chat.answers[0].text == messages.CANCEL_COMPLETED
    bookings = await booking_service.list_user_bookings(telegram_id)
    assert bookings[0].status is BookingStatus.COMPLETED


@pytest.mark.asyncio
async def test_cancel_database_error_is_safe(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
    mocker: Any,
) -> None:
    telegram_id = factory.telegram_id()
    booking = await make_booking(booking_service, factory, telegram_id=telegram_id)
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await chat.press(MenuBookingsCB().pack())
    await chat.press(BookingCB(booking_id=booking.id).pack())
    await chat.press(CancelPromptCB(booking_id=booking.id).pack())

    mocker.patch.object(
        booking_service,
        "cancel_booking",
        side_effect=DatabaseUnavailable(MESSAGE_DATABASE),
    )
    chat.reset()
    await chat.press(CancelConfirmCB(booking_id=booking.id).pack())

    assert chat.answers[0].text == MESSAGE_DATABASE
    assert "Подтверждена" in chat.text
    assert "postgresql" not in chat.text.lower()
    bookings = await booking_service.list_user_bookings(telegram_id)
    assert bookings[0].status is BookingStatus.CONFIRMED


@pytest.mark.asyncio
async def test_my_bookings_are_paginated(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    telegram_id = factory.telegram_id()
    for _ in range(6):
        await make_booking(booking_service, factory, telegram_id=telegram_id)
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await chat.press(MenuBookingsCB().pack())
    assert "Страница 1 из 2" in chat.text

    await chat.press(BookingsPageCB(page=1).pack())
    assert "Страница 2 из 2" in chat.text

    await chat.press(BookingsPageCB(page=999).pack())
    assert "Страница 2 из 2" in chat.text


@pytest.mark.asyncio
async def test_empty_my_bookings(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
) -> None:
    chat = chat_for(live_dispatcher, bot, fake_session, factory.telegram_id())

    await chat.press(MenuBookingsCB().pack())

    assert chat.text == messages.EMPTY_BOOKINGS
