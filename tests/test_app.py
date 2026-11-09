"""Тесты обработчика ошибок и жизненного цикла приложения."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMe
from aiogram.types import ErrorEvent
from pydantic import SecretStr

from barberbot import app
from barberbot.admin.service import AdminService
from barberbot.app import ERROR_TEXT, build_dispatcher, on_error, run_bot
from barberbot.booking.service import BookingService
from barberbot.config import Settings

from .conftest import NOW, TEST_BOT_TOKEN, TEST_CHAT_ID, FakeSession, build_update
from .fakes import FakeBookingService

INTERNAL_DETAIL = "internal-detail-must-not-leak"


def _message_payload() -> dict[str, Any]:
    return {
        "message_id": 1,
        "date": NOW,
        "chat": {"id": TEST_CHAT_ID, "type": "private"},
        "from": {"id": TEST_CHAT_ID, "is_bot": False, "first_name": "Тест"},
        "text": "/start",
    }


@pytest.mark.asyncio
async def test_error_is_logged_but_hidden_from_user(
    bot: Bot,
    fake_session: FakeSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    update = build_update(bot, {"update_id": 1, "message": _message_payload()})
    event = ErrorEvent(update=update, exception=RuntimeError(INTERNAL_DETAIL))

    with caplog.at_level(logging.ERROR, logger="barberbot.app"):
        handled = await on_error(event)

    assert handled is True
    assert INTERNAL_DETAIL in caplog.text

    sent = fake_session.requests
    assert len(sent) == 1
    assert getattr(sent[0], "text", None) == ERROR_TEXT
    assert INTERNAL_DETAIL not in ERROR_TEXT


def test_build_dispatcher_injects_booking_service() -> None:
    stub = FakeBookingService()

    dispatcher = build_dispatcher(stub)  # type: ignore[arg-type]

    assert dispatcher.workflow_data["booking_service"] is stub
    assert dispatcher.workflow_data["admin_service"] is None
    assert dispatcher.workflow_data["admin_ids"] == frozenset()


@pytest.mark.asyncio
async def test_run_bot_builds_admin_service_with_configured_ids(
    monkeypatch: pytest.MonkeyPatch,
    bot: Bot,
    fake_session: FakeSession,
) -> None:
    database = FakeDatabase()
    dispatcher = RecordingDispatcher()
    captured: dict[str, object] = {}

    def fake_build(service: object, admin_service: object = None) -> object:
        captured["service"] = service
        captured["admin_service"] = admin_service
        return dispatcher

    monkeypatch.setattr(app, "create_database", lambda: database)
    monkeypatch.setattr(app, "build_dispatcher", fake_build)
    monkeypatch.setattr(app, "Bot", lambda token: bot)
    settings = Settings(
        bot_token=SecretStr(TEST_BOT_TOKEN),
        admin_telegram_ids=frozenset({4242}),
    )

    await run_bot(settings)

    admin_service = captured["admin_service"]
    assert isinstance(admin_service, AdminService)
    assert admin_service.admin_ids == frozenset({4242})
    assert isinstance(captured["service"], BookingService)


class RecordingDispatcher:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.close_bot_session: bool | None = None

    async def start_polling(self, bot: Bot, *, close_bot_session: bool) -> None:
        self.close_bot_session = close_bot_session
        if self.error is not None:
            raise self.error


class FakeDatabase:
    def __init__(self) -> None:
        self.sessions = object()
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def settings() -> Settings:
    return Settings(bot_token=SecretStr(TEST_BOT_TOKEN))


@pytest.mark.asyncio
async def test_run_bot_disposes_database_after_polling_stops(
    monkeypatch: pytest.MonkeyPatch,
    bot: Bot,
    fake_session: FakeSession,
    settings: Settings,
) -> None:
    database = FakeDatabase()
    dispatcher = RecordingDispatcher()
    monkeypatch.setattr(app, "create_database", lambda: database)
    monkeypatch.setattr(
        app, "build_dispatcher", lambda service, admin_service=None: dispatcher
    )
    monkeypatch.setattr(app, "Bot", lambda token: bot)

    await run_bot(settings)

    assert database.disposed is True
    assert fake_session.closed is True
    assert dispatcher.close_bot_session is False


@pytest.mark.asyncio
async def test_run_bot_disposes_database_when_polling_fails(
    monkeypatch: pytest.MonkeyPatch,
    bot: Bot,
    fake_session: FakeSession,
    settings: Settings,
) -> None:
    database = FakeDatabase()
    failure = TelegramNetworkError(method=GetMe(), message="network is down")
    dispatcher = RecordingDispatcher(error=failure)
    monkeypatch.setattr(app, "create_database", lambda: database)
    monkeypatch.setattr(
        app, "build_dispatcher", lambda service, admin_service=None: dispatcher
    )
    monkeypatch.setattr(app, "Bot", lambda token: bot)

    with pytest.raises(TelegramNetworkError):
        await run_bot(settings)

    assert database.disposed is True
    assert fake_session.closed is True
