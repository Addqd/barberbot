"""Общие фикстуры тестов: бот без сети, dispatcher и фейковая сессия Telegram."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update

from barberbot.app import build_dispatcher

TEST_BOT_TOKEN = "123456789:TEST-token-value-for-unit-tests-only"
TEST_CHAT_ID = 42
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeSession(BaseSession):
    """Сессия Bot API, которая записывает запросы вместо сети."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.closed = False
        self._last_message_id = 100

    async def close(self) -> None:
        self.closed = True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:
        yield b""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, SendMessage):
            self._last_message_id += 1
            return Message(
                message_id=self._last_message_id,
                date=datetime.now(UTC),
                chat=Chat(id=TEST_CHAT_ID, type="private"),
                text=method.text,
            )
        raise AssertionError(f"Неожиданный запрос к Bot API: {type(method).__name__}")


def build_update(bot: Bot, payload: dict[str, Any]) -> Update:
    """Собрать Update так же, как это делает aiogram при получении из Telegram.

    Контекст ``bot`` обязателен: без него ``message.answer`` и ``callback.answer``
    не смогут отправить запрос.
    """
    return Update.model_validate(payload, context={"bot": bot})


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def bot(fake_session: FakeSession) -> Bot:
    return Bot(token=TEST_BOT_TOKEN, session=fake_session)


@pytest.fixture
def dispatcher() -> Dispatcher:
    return build_dispatcher()
