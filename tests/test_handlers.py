"""Тесты команд и кнопок через реальный Dispatcher (без сети и без БД)."""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup

from barberbot import fsm, messages
from barberbot.booking.errors import DatabaseUnavailable
from barberbot.callbacks import (
    MenuBookCB,
    MenuBookingsCB,
    MenuServicesCB,
    ServiceCB,
)
from barberbot.fsm import BookingFlow
from barberbot.handlers.common import HELP_TEXT, START_TEXT

from .conftest import (
    TEST_CHAT_ID,
    FakeSession,
    build_update,
    callback_answers,
    callback_payload,
    edited_messages,
    last_text,
    message_payload,
    sent_messages,
)
from .fakes import FakeBookingService, make_barber, make_service

DATABASE_ERROR = "Сервис записи временно недоступен. Попробуйте позже."


@pytest.mark.asyncio
async def test_start_sends_greeting_with_three_buttons(
    dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    update = build_update(bot, {"update_id": 1, "message": message_payload("/start")})

    await dispatcher.feed_update(bot, update)

    messages_sent = sent_messages(fake_session)
    assert len(messages_sent) == 1
    assert messages_sent[0].text == START_TEXT
    assert isinstance(messages_sent[0].reply_markup, InlineKeyboardMarkup)

    buttons = [
        button
        for row in messages_sent[0].reply_markup.inline_keyboard
        for button in row
    ]
    assert [button.text for button in buttons] == [
        "✂️ Записаться",
        "💈 Услуги и цены",
        "📅 Мои записи",
    ]
    assert [button.callback_data for button in buttons] == [
        MenuBookCB().pack(),
        MenuServicesCB().pack(),
        MenuBookingsCB().pack(),
    ]


@pytest.mark.asyncio
async def test_start_clears_unfinished_booking_state(
    dispatcher: Dispatcher, bot: Bot
) -> None:
    context = dispatcher.fsm.get_context(
        bot=bot, chat_id=TEST_CHAT_ID, user_id=TEST_CHAT_ID
    )
    await context.set_state(BookingFlow.confirm)
    await context.update_data({fsm.SERVICE_ID: 1, fsm.BARBER_ID: 2})

    update = build_update(bot, {"update_id": 1, "message": message_payload("/start")})
    await dispatcher.feed_update(bot, update)

    assert await context.get_state() is None
    assert await context.get_data() == {}


@pytest.mark.asyncio
async def test_help_sends_reference(
    dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    update = build_update(bot, {"update_id": 1, "message": message_payload("/help")})

    await dispatcher.feed_update(bot, update)

    messages_sent = sent_messages(fake_session)
    assert len(messages_sent) == 1
    assert messages_sent[0].text == HELP_TEXT
    assert "/start" in HELP_TEXT
    assert "/help" in HELP_TEXT


@pytest.mark.parametrize(
    "callback",
    [MenuBookCB().pack(), MenuServicesCB().pack(), MenuBookingsCB().pack()],
    ids=["book", "services", "my_bookings"],
)
@pytest.mark.asyncio
async def test_menu_button_is_acknowledged(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    callback: str,
) -> None:
    update = build_update(
        bot,
        {
            "update_id": 2,
            "callback_query": callback_payload(callback),
        },
    )

    await dispatcher.feed_update(bot, update)

    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].callback_query_id == "callback-1"


@pytest.mark.asyncio
async def test_services_section_shows_active_catalog(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    booking_service_stub.services = [
        make_service(name="Стрижка с укладкой", price=650, duration=60)
    ]

    update = build_update(
        bot,
        {"update_id": 2, "callback_query": callback_payload(MenuServicesCB().pack())},
    )
    await dispatcher.feed_update(bot, update)

    text = last_text(fake_session)
    assert "Услуги и цены" in text
    assert "Стрижка с укладкой" in text
    assert "650 ₽" in text
    assert "60 минут" in text
    assert booking_service_stub.calls == ["list_active_services"]


@pytest.mark.asyncio
async def test_services_section_reports_database_error_safely(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    booking_service_stub.error = DatabaseUnavailable(DATABASE_ERROR)

    update = build_update(
        bot,
        {"update_id": 2, "callback_query": callback_payload(MenuServicesCB().pack())},
    )
    await dispatcher.feed_update(bot, update)

    assert last_text(fake_session) == DATABASE_ERROR
    assert "postgresql" not in DATABASE_ERROR.lower()


@pytest.mark.asyncio
async def test_my_bookings_handles_database_error_safely(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    booking_service_stub.error = DatabaseUnavailable(DATABASE_ERROR)

    update = build_update(
        bot,
        {"update_id": 2, "callback_query": callback_payload(MenuBookingsCB().pack())},
    )
    await dispatcher.feed_update(bot, update)

    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text == DATABASE_ERROR
    assert last_text(fake_session) == DATABASE_ERROR


@pytest.mark.asyncio
async def test_my_bookings_empty_state(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
) -> None:
    update = build_update(
        bot,
        {"update_id": 2, "callback_query": callback_payload(MenuBookingsCB().pack())},
    )
    await dispatcher.feed_update(bot, update)

    assert last_text(fake_session) == messages.EMPTY_BOOKINGS


@pytest.mark.asyncio
async def test_book_menu_shows_services_from_database(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    booking_service_stub.services = [make_service()]
    booking_service_stub.barbers = [make_barber()]

    update = build_update(
        bot,
        {"update_id": 2, "callback_query": callback_payload(MenuBookCB().pack())},
    )
    await dispatcher.feed_update(bot, update)

    text = last_text(fake_session)
    assert "Выберите услугу" in text
    assert "Обычная стрижка" in text


@pytest.mark.asyncio
async def test_book_menu_reports_missing_services(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
) -> None:
    update = build_update(
        bot,
        {"update_id": 2, "callback_query": callback_payload(MenuBookCB().pack())},
    )
    await dispatcher.feed_update(bot, update)

    assert last_text(fake_session) == messages.NO_SERVICES


@pytest.mark.asyncio
async def test_selecting_service_without_barbers(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    booking_service_stub.services = [make_service()]

    await dispatcher.feed_update(
        bot,
        build_update(
            bot,
            {
                "update_id": 2,
                "callback_query": callback_payload(MenuBookCB().pack()),
            },
        ),
    )
    await dispatcher.feed_update(
        bot,
        build_update(
            bot,
            {
                "update_id": 3,
                "callback_query": callback_payload(ServiceCB(service_id=1).pack()),
            },
        ),
    )

    assert last_text(fake_session) == messages.NO_BARBERS


@pytest.mark.asyncio
async def test_book_menu_reports_database_error_safely(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    booking_service_stub.error = DatabaseUnavailable(DATABASE_ERROR)

    await dispatcher.feed_update(
        bot,
        build_update(
            bot,
            {
                "update_id": 2,
                "callback_query": callback_payload(MenuBookCB().pack()),
            },
        ),
    )

    assert last_text(fake_session) == DATABASE_ERROR
    assert "psycopg" not in last_text(fake_session).lower()


@pytest.mark.parametrize(
    "callback_data",
    [
        "unknown:1",
        "svc:not-a-number",
        "day:2030-13-45",
        "ok",
    ],
    ids=["unknown-prefix", "bad-int", "bad-date", "confirm-without-state"],
)
@pytest.mark.asyncio
async def test_unknown_or_stale_callback_is_answered(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    callback_data: str,
) -> None:
    update = build_update(
        bot,
        {
            "update_id": 2,
            "callback_query": callback_payload(callback_data),
        },
    )

    await dispatcher.feed_update(bot, update)

    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text == messages.STALE_CALLBACK
    assert answers[0].show_alert is True
    assert edited_messages(fake_session) == []
    assert sent_messages(fake_session) == []
