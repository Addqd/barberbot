"""Интеграционные тесты FSM-сценария записи на реальной базе ``barberbot_test``.

Обработчики вызываются через настоящий Dispatcher и ``feed_update``;
Telegram не используется — ``FakeSession`` только записывает методы Bot API.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from math import ceil
from typing import Any

import pytest
from aiogram import Bot, Dispatcher

from barberbot import messages
from barberbot.app import ERROR_TEXT
from barberbot.booking.errors import DatabaseUnavailable
from barberbot.booking.service import MESSAGE_DATABASE, BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.callbacks import (
    BarberCB,
    BookingCB,
    ConfirmCB,
    DateCB,
    DatesPageCB,
    FlowCancelCB,
    MenuBookCB,
    MenuBookingsCB,
    MenuServicesCB,
    NavBarbersCB,
    NavDatesCB,
    NavMainCB,
    NavServicesCB,
    NavTimesCB,
    ServiceCB,
    TimeCB,
)
from barberbot.db.models import BookingStatus
from barberbot.fsm import BARBER_ID, DATES_PAGE, SERVICE_ID, BookingFlow

from .chat import Chat
from .conftest import FakeSession, callback_answers

MONDAY = date(2030, 1, 7)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, 7, hour, minute, tzinfo=MOSCOW)


def chat_for(
    dispatcher: Dispatcher, bot: Bot, session: FakeSession, user_id: int
) -> Chat:
    return Chat(dispatcher, bot, session, user_id=user_id)


async def open_service_choice(chat: Chat) -> None:
    await chat.press(MenuBookCB().pack())
    assert await chat.state() == BookingFlow.service.state


async def open_barber_choice(chat: Chat, service_id: int) -> None:
    await chat.press(ServiceCB(service_id=service_id).pack())
    assert await chat.state() == BookingFlow.barber.state


async def open_date_choice(chat: Chat, barber_id: int) -> None:
    await chat.press(BarberCB(barber_id=barber_id).pack())
    assert await chat.state() == BookingFlow.date.state


async def open_time_choice(chat: Chat, day: date = MONDAY) -> None:
    await chat.press(DateCB(day=day.isoformat()).pack())
    assert await chat.state() == BookingFlow.time.state


async def open_confirmation(chat: Chat, start: datetime) -> None:
    await chat.press(TimeCB(start=int(start.timestamp())).pack())
    assert await chat.state() == BookingFlow.confirm.state


@pytest.mark.asyncio
async def test_catalog_and_barbers_come_from_database(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
) -> None:
    active_service = await factory.service(price=700, duration=60)
    inactive_service = await factory.service(is_active=False)
    active_barber = await factory.barber()
    inactive_barber = await factory.barber(is_active=False)
    chat = chat_for(live_dispatcher, bot, fake_session, factory.telegram_id())

    await chat.press(MenuServicesCB().pack())
    text = chat.text
    assert "Услуги и цены" in text
    assert active_service.name in text
    assert "700 ₽" in text
    assert "60 минут" in text
    assert inactive_service.name not in text

    await open_service_choice(chat)
    text = chat.text
    assert active_service.name in text
    assert inactive_service.name not in text

    await open_barber_choice(chat, active_service.id)
    text = chat.text
    assert active_barber.name in text
    assert inactive_barber.name not in text


@pytest.mark.asyncio
async def test_full_booking_scenario_creates_one_booking(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service(price=500, duration=60)
    telegram_id = factory.telegram_id()
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    await open_time_choice(chat)
    await open_confirmation(chat, at(10))

    text = chat.text
    assert "Проверьте данные записи" in text
    assert service.name in text
    assert barber.name in text
    assert "07.01.2030" in text
    assert "10:00" in text
    assert "500 ₽" in text
    assert "60 минут" in text

    await chat.press(ConfirmCB().pack())

    text = chat.text
    assert "Запись создана" in text
    bookings = await booking_service.list_user_bookings(telegram_id)
    assert len(bookings) == 1
    booking = bookings[0]
    assert str(booking.id) in text
    assert booking.starts_at == at(10)
    assert booking.service.name == service.name
    assert booking.barber.name == barber.name
    assert booking.price_rub_at_booking == 500
    assert booking.duration_minutes_at_booking == 60
    assert await chat.state() is None


@pytest.mark.asyncio
async def test_dates_are_paginated(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    telegram_id = factory.telegram_id()
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    dates = await booking_service.available_dates(
        service_id=service.id, barber_id=barber.id
    )
    pages = ceil(len(dates) / 6)
    assert pages > 1

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    assert f"Страница 1 из {pages}" in chat.text

    await chat.press(DatesPageCB(page=1).pack())
    assert f"Страница 2 из {pages}" in chat.text

    # Выход за пределы списка страниц не ломает интерфейс и не создаёт запись.
    await chat.press(DatesPageCB(page=999).pack())
    assert f"Страница {pages} из {pages}" in chat.text

    await chat.press(DateCB(day=dates[6].isoformat()).pack())
    assert "Выберите время" in chat.text
    assert await booking_service.list_user_bookings(telegram_id) == []


@pytest.mark.asyncio
async def test_barber_without_schedule_has_no_dates(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
) -> None:
    barber = await factory.barber(weekdays=[])
    service = await factory.service()
    chat = chat_for(live_dispatcher, bot, fake_session, factory.telegram_id())

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)

    assert chat.text == messages.NO_DATES
    assert await chat.state() == BookingFlow.date.state

    await chat.press(NavBarbersCB().pack())
    assert await chat.state() == BookingFlow.barber.state
    assert barber.name in chat.text


@pytest.mark.asyncio
async def test_stale_time_reports_no_slots(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service(duration=60)
    chat = chat_for(live_dispatcher, bot, fake_session, factory.telegram_id())

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    await open_time_choice(chat)
    button_texts = [
        button.text
        for row in chat.edits[-1].reply_markup.inline_keyboard
        for button in row
    ]
    assert "09:00" in button_texts

    other = await factory.user()
    await factory.booking(
        user_id=other.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
        duration=60,
    )
    # Занимаем все остальные слоты, чтобы после конфликта их не осталось.
    for hour in range(10, 17):
        await factory.booking(
            user_id=other.id,
            barber_id=barber.id,
            service_id=service.id,
            starts_at=at(hour),
            duration=60,
        )

    chat.reset()
    await chat.press(TimeCB(start=int(at(9).timestamp())).pack())

    assert chat.answers[0].text == messages.SLOT_GONE
    assert chat.text == messages.NO_SLOTS
    assert await chat.state() == BookingFlow.time.state


@pytest.mark.asyncio
async def test_slot_conflict_on_confirm_offers_other_time(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service(duration=60)
    telegram_id = factory.telegram_id()
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    await open_time_choice(chat)
    await open_confirmation(chat, at(10))

    other = await factory.user()
    await factory.booking(
        user_id=other.id,
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(10),
        duration=60,
    )

    chat.reset()
    await chat.press(ConfirmCB().pack())

    assert "занято" in (chat.answers[0].text or "")
    assert "Выберите время" in chat.text
    assert "10:00" not in [
        button.text
        for row in chat.edits[-1].reply_markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert await chat.state() == BookingFlow.time.state
    assert await booking_service.list_user_bookings(telegram_id) == []


@pytest.mark.asyncio
async def test_repeated_confirm_does_not_create_second_booking(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service(duration=60)
    telegram_id = factory.telegram_id()
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    await open_time_choice(chat)
    await open_confirmation(chat, at(11))
    await chat.press(ConfirmCB().pack())
    assert "Запись создана" in chat.text

    chat.reset()
    await chat.press(ConfirmCB().pack())

    assert chat.answers[0].text == messages.STALE_CALLBACK
    bookings = await booking_service.list_user_bookings(telegram_id)
    assert len(bookings) == 1


@pytest.mark.asyncio
async def test_concurrent_confirm_creates_one_booking(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    telegram_id = factory.telegram_id()
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    await open_time_choice(chat)
    await open_confirmation(chat, at(11))

    chat.reset()
    # Два одновременных нажатия «Подтвердить»: изоляция событий aiogram
    # сериализует обновления одного чата, поэтому второе видит уже очищенный FSM.
    await asyncio.gather(
        chat.press(ConfirmCB().pack()),
        chat.press(ConfirmCB().pack()),
    )

    bookings = await booking_service.list_user_bookings(telegram_id)
    assert len(bookings) == 1
    answers = callback_answers(fake_session)
    assert len(answers) == 2
    assert [answer.text for answer in answers].count(messages.STALE_CALLBACK) == 1
    assert "Запись создана" in chat.text


@pytest.mark.asyncio
async def test_callback_from_wrong_step_is_rejected(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    service = await factory.service()
    telegram_id = factory.telegram_id()
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await open_service_choice(chat)
    chat.reset()
    # Кнопка даты нажата до выбора услуги и мастера.
    await chat.press(DateCB(day=MONDAY.isoformat()).pack())

    assert chat.answers[0].text == messages.STALE_CALLBACK
    assert await chat.state() == BookingFlow.service.state
    assert await booking_service.list_user_bookings(telegram_id) == []

    # Кнопка подтверждения в момент выбора мастера.
    await open_barber_choice(chat, service.id)
    chat.reset()
    await chat.press(ConfirmCB().pack())
    assert chat.answers[0].text == messages.STALE_CALLBACK
    assert await chat.state() == BookingFlow.barber.state
    assert await booking_service.list_user_bookings(telegram_id) == []


@pytest.mark.asyncio
async def test_unknown_ids_and_malformed_values_are_rejected(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    telegram_id = factory.telegram_id()
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await open_service_choice(chat)
    chat.reset()
    await chat.press(ServiceCB(service_id=service.id + 10_000_000).pack())
    assert chat.answers[0].text == messages.SERVICE_GONE
    assert await chat.state() == BookingFlow.service.state

    await open_barber_choice(chat, service.id)
    chat.reset()
    await chat.press(BarberCB(barber_id=barber.id + 10_000_000).pack())
    assert chat.answers[0].text == messages.BARBER_GONE
    assert await chat.state() == BookingFlow.barber.state

    await open_date_choice(chat, barber.id)
    chat.reset()
    await chat.press(DateCB(day="2030-13-45").pack())
    assert chat.answers[0].text == messages.DATE_GONE
    assert await chat.state() == BookingFlow.date.state

    await open_time_choice(chat)
    chat.reset()
    await chat.press(TimeCB(start=10**15).pack())
    assert chat.answers[0].text == messages.SLOT_GONE
    assert await chat.state() == BookingFlow.time.state
    assert await booking_service.list_user_bookings(telegram_id) == []


@pytest.mark.asyncio
async def test_back_navigation_clears_dependent_fsm_data(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    chat = chat_for(live_dispatcher, bot, fake_session, factory.telegram_id())

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    assert (await chat.state_data()) == {
        SERVICE_ID: service.id,
        BARBER_ID: barber.id,
        DATES_PAGE: 0,
    }

    await chat.press(NavBarbersCB().pack())
    assert await chat.state() == BookingFlow.barber.state
    assert (await chat.state_data()) == {SERVICE_ID: service.id}

    await chat.press(NavServicesCB().pack())
    assert await chat.state() == BookingFlow.service.state
    assert (await chat.state_data()) == {}

    await open_barber_choice(chat, service.id)
    await chat.press(NavMainCB().pack())
    assert await chat.state() is None
    assert chat.text.startswith("💈 Добро пожаловать")

    await open_service_choice(chat)
    await chat.press(FlowCancelCB().pack())
    assert await chat.state() is None


@pytest.mark.asyncio
async def test_database_error_on_confirm_is_safe_and_keeps_state(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
    mocker: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    telegram_id = factory.telegram_id()
    chat = chat_for(live_dispatcher, bot, fake_session, telegram_id)

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    await open_time_choice(chat)
    await open_confirmation(chat, at(12))

    mocker.patch.object(
        booking_service,
        "create_booking",
        side_effect=RuntimeError("SQL detail must not leak"),
    )
    chat.reset()
    await chat.press(ConfirmCB().pack())

    # Неожиданное исключение перехватывает глобальный обработчик ошибок:
    # пользователь видит только общий текст.
    assert chat.answers[0].text == ERROR_TEXT
    assert "SQL detail" not in str(chat.answers[0].text)

    mocker.patch.object(
        booking_service,
        "create_booking",
        side_effect=DatabaseUnavailable(MESSAGE_DATABASE),
    )
    chat.reset()
    await chat.press(ConfirmCB().pack())

    assert chat.answers[0].text == MESSAGE_DATABASE
    assert MESSAGE_DATABASE in chat.text
    assert "SQL" not in chat.text
    assert await chat.state() == BookingFlow.confirm.state
    assert await booking_service.list_user_bookings(telegram_id) == []


@pytest.mark.asyncio
async def test_back_from_time_and_confirmation_refreshes_choice(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    chat = chat_for(live_dispatcher, bot, fake_session, factory.telegram_id())

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    await open_date_choice(chat, barber.id)
    await open_time_choice(chat)

    await chat.press(NavDatesCB().pack())
    assert await chat.state() == BookingFlow.date.state
    assert "Выберите дату" in chat.text

    await open_time_choice(chat)
    await open_confirmation(chat, at(10))
    await chat.press(NavTimesCB().pack())

    assert await chat.state() == BookingFlow.time.state
    assert "Выберите время" in chat.text


@pytest.mark.asyncio
async def test_database_error_during_selection_is_safe(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
    mocker: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    chat = chat_for(live_dispatcher, bot, fake_session, factory.telegram_id())
    await open_service_choice(chat)

    mocker.patch.object(
        booking_service,
        "list_active_barbers",
        side_effect=DatabaseUnavailable(MESSAGE_DATABASE),
    )
    chat.reset()
    await chat.press(ServiceCB(service_id=service.id).pack())

    assert chat.answers[0].text == MESSAGE_DATABASE
    assert chat.text == MESSAGE_DATABASE
    assert "postgres" not in chat.text.lower()
    assert await chat.state() is None

    # Сценарий можно начать заново сразу после ошибки.
    mocker.stopall()
    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    mocker.patch.object(
        booking_service,
        "available_dates",
        side_effect=DatabaseUnavailable(MESSAGE_DATABASE),
    )
    chat.reset()
    await chat.press(BarberCB(barber_id=barber.id).pack())

    assert chat.answers[0].text == MESSAGE_DATABASE
    assert chat.text == MESSAGE_DATABASE
    assert await chat.state() is None


@pytest.mark.asyncio
async def test_my_bookings_entry_clears_unfinished_flow(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
) -> None:
    service = await factory.service()
    chat = chat_for(live_dispatcher, bot, fake_session, factory.telegram_id())

    await open_service_choice(chat)
    await open_barber_choice(chat, service.id)
    assert await chat.state() == BookingFlow.barber.state

    await chat.press(MenuBookingsCB().pack())
    assert await chat.state() is None
    assert chat.text == messages.EMPTY_BOOKINGS


@pytest.mark.asyncio
async def test_booking_completed_status_is_shown_in_card(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    telegram_id = factory.telegram_id()
    user = await factory.user(telegram_id=telegram_id)
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

    assert "Завершена" in chat.text
    assert await booking_service.list_user_bookings(telegram_id) != []
