"""Регрессионные тесты: клиентские функции доступны только в личных чатах.

Проверяется единая граница ``PrivateChatOnlyMiddleware`` через настоящий
``Dispatcher.feed_update``: в личном чате поведение прежнее, в группе и
супергруппе бот не читает записи, не вызывает ``BookingService`` и не
отправляет персональные данные, а callback подтверждается безопасным текстом.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import InaccessibleMessage

from barberbot import messages
from barberbot.booking.service import BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.callbacks import (
    BookingCB,
    BookingsPageCB,
    CancelConfirmCB,
    CancelPromptCB,
    MenuBookCB,
    MenuBookingsCB,
    MenuServicesCB,
    NavMainCB,
)
from barberbot.db.models import BookingStatus
from barberbot.handlers.common import START_TEXT

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
from .fakes import FakeBookingService, make_service

GROUP_ID = -1001234567890
GROUP_CHAT_TYPES = ["group", "supergroup"]

CLIENT_CALLBACKS = [
    MenuBookCB().pack(),
    MenuServicesCB().pack(),
    MenuBookingsCB().pack(),
    NavMainCB().pack(),
    BookingsPageCB(page=1).pack(),
    BookingCB(booking_id=1).pack(),
    CancelPromptCB(booking_id=1).pack(),
    CancelConfirmCB(booking_id=1).pack(),
]


def all_texts(session: FakeSession) -> list[str]:
    """Все тексты, отправленные или отредактированные ботом."""
    texts = []
    for request in session.requests:
        text = getattr(request, "text", None)
        if isinstance(text, str):
            texts.append(text)
    return texts


async def send_message(
    dispatcher: Dispatcher,
    bot: Bot,
    text: str,
    *,
    user_id: int,
    chat_id: int,
    chat_type: str,
) -> None:
    await dispatcher.feed_update(
        bot,
        build_update(
            bot,
            {
                "update_id": 1,
                "message": message_payload(
                    text, user_id=user_id, chat_id=chat_id, chat_type=chat_type
                ),
            },
        ),
    )


async def press_callback(
    dispatcher: Dispatcher,
    bot: Bot,
    data: str,
    *,
    user_id: int,
    chat_id: int | None = None,
    chat_type: str = "private",
    include_message: bool = True,
    inaccessible_chat_id: int | None = None,
    inaccessible_chat_type: str = "private",
) -> None:
    payload = callback_payload(
        data,
        user_id=user_id,
        chat_id=chat_id,
        chat_type=chat_type,
        include_message=include_message,
    )
    if inaccessible_chat_id is not None:
        # date=0 отличает InaccessibleMessage от обычного Message.
        payload["message"] = {
            "message_id": 2,
            "date": 0,
            "chat": {"id": inaccessible_chat_id, "type": inaccessible_chat_type},
        }
    await dispatcher.feed_update(
        bot, build_update(bot, {"update_id": 2, "callback_query": payload})
    )


# --------------------------------------------------------------------------- #
# Личный чат: прежнее поведение
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_start_in_private_chat_still_works(
    dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await send_message(
        dispatcher,
        bot,
        "/start",
        user_id=TEST_CHAT_ID,
        chat_id=TEST_CHAT_ID,
        chat_type="private",
    )

    messages_sent = sent_messages(fake_session)
    assert len(messages_sent) == 1
    assert messages_sent[0].text == START_TEXT


@pytest.mark.asyncio
async def test_private_callbacks_still_work(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    booking_service_stub.services = [make_service(name="Стрижка с укладкой")]

    await press_callback(dispatcher, bot, MenuServicesCB().pack(), user_id=TEST_CHAT_ID)

    assert "Стрижка с укладкой" in last_text(fake_session)
    assert booking_service_stub.calls == ["list_active_services"]
    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text is None


# --------------------------------------------------------------------------- #
# Группа и супергруппа: сообщения игнорируются
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("chat_type", GROUP_CHAT_TYPES)
@pytest.mark.asyncio
async def test_start_in_group_is_ignored(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
    chat_type: str,
) -> None:
    await send_message(
        dispatcher,
        bot,
        "/start",
        user_id=TEST_CHAT_ID,
        chat_id=GROUP_ID,
        chat_type=chat_type,
    )

    assert fake_session.requests == []
    assert booking_service_stub.calls == []


@pytest.mark.parametrize("chat_type", GROUP_CHAT_TYPES)
@pytest.mark.asyncio
async def test_my_bookings_in_group_is_ignored(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
    chat_type: str,
) -> None:
    booking_service_stub.services = [make_service(name="Секретная стрижка")]

    await press_callback(
        dispatcher,
        bot,
        MenuBookingsCB().pack(),
        user_id=TEST_CHAT_ID,
        chat_id=GROUP_ID,
        chat_type=chat_type,
    )

    assert booking_service_stub.calls == []
    assert sent_messages(fake_session) == []
    assert edited_messages(fake_session) == []
    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text == messages.PRIVATE_CHAT_ONLY
    assert answers[0].show_alert is True
    assert "Секретная стрижка" not in answers[0].text
    assert len(fake_session.requests) == 1


# --------------------------------------------------------------------------- #
# Группа и супергруппа: любой клиентский callback отклоняется
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("chat_type", GROUP_CHAT_TYPES)
@pytest.mark.parametrize("data", CLIENT_CALLBACKS)
@pytest.mark.asyncio
async def test_group_callback_is_rejected_safely(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
    chat_type: str,
    data: str,
) -> None:
    await press_callback(
        dispatcher,
        bot,
        data,
        user_id=TEST_CHAT_ID,
        chat_id=GROUP_ID,
        chat_type=chat_type,
    )

    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text == messages.PRIVATE_CHAT_ONLY
    assert answers[0].show_alert is True
    assert booking_service_stub.calls == []
    assert sent_messages(fake_session) == []
    assert edited_messages(fake_session) == []


# --------------------------------------------------------------------------- #
# Fail closed: чат невозможно определить достоверно
# --------------------------------------------------------------------------- #


def test_inaccessible_payload_is_parsed_as_inaccessible_message(bot: Bot) -> None:
    """Тестовая фикстура действительно создаёт InaccessibleMessage (date=0)."""
    update = build_update(
        bot,
        {
            "update_id": 1,
            "callback_query": {
                "id": "callback-1",
                "from": {"id": TEST_CHAT_ID, "is_bot": False, "first_name": "Тест"},
                "chat_instance": "chat-instance",
                "data": MenuServicesCB().pack(),
                "message": {
                    "message_id": 2,
                    "date": 0,
                    "chat": {"id": TEST_CHAT_ID, "type": "private"},
                },
            },
        },
    )

    assert update.callback_query is not None
    assert isinstance(update.callback_query.message, InaccessibleMessage)


@pytest.mark.asyncio
async def test_callback_without_message_is_rejected(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    await press_callback(
        dispatcher,
        bot,
        MenuBookingsCB().pack(),
        user_id=TEST_CHAT_ID,
        include_message=False,
    )

    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text == messages.PRIVATE_CHAT_ONLY
    assert answers[0].show_alert is True
    assert booking_service_stub.calls == []
    assert sent_messages(fake_session) == []
    assert edited_messages(fake_session) == []


@pytest.mark.asyncio
async def test_inaccessible_group_message_is_rejected(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    await press_callback(
        dispatcher,
        bot,
        CancelConfirmCB(booking_id=1).pack(),
        user_id=TEST_CHAT_ID,
        inaccessible_chat_id=GROUP_ID,
        inaccessible_chat_type="supergroup",
    )

    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text == messages.PRIVATE_CHAT_ONLY
    assert booking_service_stub.calls == []
    assert sent_messages(fake_session) == []
    assert edited_messages(fake_session) == []


@pytest.mark.asyncio
async def test_inaccessible_private_message_still_works(
    dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    booking_service_stub: FakeBookingService,
) -> None:
    booking_service_stub.services = [make_service(name="Стрижка с укладкой")]
    await press_callback(
        dispatcher,
        bot,
        MenuServicesCB().pack(),
        user_id=TEST_CHAT_ID,
        inaccessible_chat_id=TEST_CHAT_ID,
    )

    assert "Стрижка с укладкой" in last_text(fake_session)
    assert booking_service_stub.calls == ["list_active_services"]
    assert callback_answers(fake_session)[0].text is None


# --------------------------------------------------------------------------- #
# Интеграция с реальной тестовой БД: данные не читаются и не меняются
# --------------------------------------------------------------------------- #


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, 7, hour, minute, tzinfo=MOSCOW)


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


@pytest.mark.parametrize("chat_type", GROUP_CHAT_TYPES)
@pytest.mark.asyncio
async def test_group_my_bookings_does_not_leak_real_data(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
    chat_type: str,
) -> None:
    telegram_id = factory.telegram_id()
    booking = await make_booking(booking_service, factory, telegram_id=telegram_id)

    await press_callback(
        live_dispatcher,
        bot,
        MenuBookingsCB().pack(),
        user_id=telegram_id,
        chat_id=GROUP_ID,
        chat_type=chat_type,
    )

    assert sent_messages(fake_session) == []
    assert edited_messages(fake_session) == []
    assert all(booking.service.name not in text for text in all_texts(fake_session))
    assert all(str(booking.id) not in text for text in all_texts(fake_session))
    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text == messages.PRIVATE_CHAT_ONLY


@pytest.mark.parametrize("chat_type", GROUP_CHAT_TYPES)
@pytest.mark.asyncio
async def test_group_cancel_does_not_change_booking(
    live_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    booking_service: BookingService,
    chat_type: str,
) -> None:
    telegram_id = factory.telegram_id()
    booking = await make_booking(booking_service, factory, telegram_id=telegram_id)

    await press_callback(
        live_dispatcher,
        bot,
        CancelConfirmCB(booking_id=booking.id).pack(),
        user_id=telegram_id,
        chat_id=GROUP_ID,
        chat_type=chat_type,
    )

    answers = callback_answers(fake_session)
    assert len(answers) == 1
    assert answers[0].text == messages.PRIVATE_CHAT_ONLY
    assert sent_messages(fake_session) == []
    assert edited_messages(fake_session) == []

    bookings = await booking_service.list_user_bookings(telegram_id)
    assert [row.id for row in bookings] == [booking.id]
    assert bookings[0].status is BookingStatus.CONFIRMED
