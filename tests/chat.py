"""Драйвер фейкового Telegram-диалога поверх Dispatcher.feed_update.

Никаких сетевых запросов: ``FakeSession`` записывает методы Bot API, а
обновления подаются в dispatcher напрямую.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot, Dispatcher

from .conftest import (
    FakeSession,
    build_update,
    callback_answers,
    callback_payload,
    edited_messages,
    last_text,
    message_payload,
)


class Chat:
    """Пользователь в личном чате с ботом (один Telegram ID)."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        bot: Bot,
        session: FakeSession,
        *,
        user_id: int,
    ) -> None:
        self.dispatcher = dispatcher
        self.bot = bot
        self.session = session
        self.user_id = user_id
        self._update_id = 0

    async def send(self, text: str) -> None:
        self._update_id += 1
        update = build_update(
            self.bot,
            {
                "update_id": self._update_id,
                "message": message_payload(text, user_id=self.user_id),
            },
        )
        await self.dispatcher.feed_update(self.bot, update)

    async def press(self, data: str, *, message_id: int = 2) -> None:
        self._update_id += 1
        update = build_update(
            self.bot,
            {
                "update_id": self._update_id,
                "callback_query": callback_payload(
                    data, user_id=self.user_id, message_id=message_id
                ),
            },
        )
        await self.dispatcher.feed_update(self.bot, update)

    async def type(self, text: str) -> None:
        """Отправить обычный текст без command-энтити (ввод формы)."""
        self._update_id += 1
        payload = message_payload(text, user_id=self.user_id)
        payload.pop("entities", None)
        update = build_update(
            self.bot,
            {"update_id": self._update_id, "message": payload},
        )
        await self.dispatcher.feed_update(self.bot, update)

    @property
    def text(self) -> str:
        return last_text(self.session)

    @property
    def answers(self) -> list[Any]:
        return callback_answers(self.session)

    @property
    def edits(self) -> list[Any]:
        return edited_messages(self.session)

    def reset(self) -> None:
        self.session.requests.clear()

    async def state(self) -> str | None:
        context = self.dispatcher.fsm.get_context(
            bot=self.bot, chat_id=self.user_id, user_id=self.user_id
        )
        return await context.get_state()

    async def state_data(self) -> dict[str, Any]:
        context = self.dispatcher.fsm.get_context(
            bot=self.bot, chat_id=self.user_id, user_id=self.user_id
        )
        return await context.get_data()


__all__ = ["Chat"]
