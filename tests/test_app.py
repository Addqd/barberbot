"""Тесты обработчика ошибок: детали остаются в логе, не у пользователя."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from aiogram import Bot
from aiogram.types import ErrorEvent

from barberbot.app import ERROR_TEXT, on_error

from .conftest import NOW, TEST_CHAT_ID, FakeSession, build_update

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
