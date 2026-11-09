"""Тесты команд и кнопок через реальный Dispatcher (без сети)."""

from __future__ import annotations

from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import InlineKeyboardMarkup

from barberbot.handlers.common import HELP_TEXT, IN_DEVELOPMENT_TEXT, START_TEXT
from barberbot.keyboards import CALLBACK_BOOK, CALLBACK_MY_BOOKINGS, CALLBACK_SERVICES

from .conftest import NOW, TEST_CHAT_ID, FakeSession, build_update


def _message_payload(text: str) -> dict[str, Any]:
    return {
        "message_id": 1,
        "date": NOW,
        "chat": {"id": TEST_CHAT_ID, "type": "private"},
        "from": {"id": TEST_CHAT_ID, "is_bot": False, "first_name": "Тест"},
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(text)}],
    }


def _callback_payload(data: str) -> dict[str, Any]:
    message = _message_payload(START_TEXT)
    message["message_id"] = 2
    return {
        "id": "callback-1",
        "from": {"id": TEST_CHAT_ID, "is_bot": False, "first_name": "Тест"},
        "chat_instance": "chat-instance",
        "data": data,
        "message": message,
    }


def sent_messages(session: FakeSession) -> list[SendMessage]:
    return [request for request in session.requests if isinstance(request, SendMessage)]


def callback_answers(session: FakeSession) -> list[AnswerCallbackQuery]:
    return [
        request
        for request in session.requests
        if isinstance(request, AnswerCallbackQuery)
    ]


@pytest.mark.asyncio
async def test_start_sends_greeting_with_three_buttons(
    dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    update = build_update(bot, {"update_id": 1, "message": _message_payload("/start")})

    await dispatcher.feed_update(bot, update)

    messages = sent_messages(fake_session)
    assert len(messages) == 1
    assert messages[0].text == START_TEXT
    assert isinstance(messages[0].reply_markup, InlineKeyboardMarkup)

    buttons = [
        button for row in messages[0].reply_markup.inline_keyboard for button in row
    ]
    assert [button.text for button in buttons] == [
        "✂️ Записаться",
        "💈 Услуги и цены",
        "📅 Мои записи",
    ]
    assert [button.callback_data for button in buttons] == [
        CALLBACK_BOOK,
        CALLBACK_SERVICES,
        CALLBACK_MY_BOOKINGS,
    ]


@pytest.mark.asyncio
async def test_help_sends_reference(
    dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    update = build_update(bot, {"update_id": 1, "message": _message_payload("/help")})

    await dispatcher.feed_update(bot, update)

    messages = sent_messages(fake_session)
    assert len(messages) == 1
    assert messages[0].text == HELP_TEXT
    assert "/start" in HELP_TEXT
    assert "/help" in HELP_TEXT


@pytest.mark.parametrize(
    "callback_data",
    [CALLBACK_BOOK, CALLBACK_SERVICES, CALLBACK_MY_BOOKINGS],
    ids=["book", "services", "my_bookings"],
)
@pytest.mark.asyncio
async def test_menu_button_is_acknowledged_and_answered(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    callback_data: str,
) -> None:
    update = build_update(
        bot,
        {"update_id": 2, "callback_query": _callback_payload(callback_data)},
    )

    await dispatcher.feed_update(bot, update)

    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].callback_query_id == "callback-1"
    assert answers[0].text == IN_DEVELOPMENT_TEXT

    messages = sent_messages(fake_session)
    assert len(messages) == 1
    assert messages[0].chat_id == TEST_CHAT_ID
    assert messages[0].text == IN_DEVELOPMENT_TEXT
