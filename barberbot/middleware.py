"""Граница обновлений: клиентские функции только в личных чатах.

Персональные данные (записи, отмена, сценарий бронирования) допустимы только
в личном чате с ботом. Эта проверка выполняется один раз для всех updates —
до фильтров, до обработчиков и до обращения к ``BookingService``.

Правило основано исключительно на контексте чата Telegram (``chat.type``), а
не на ``from_user.id``: в группе отправитель тот же пользователь, но данные
увидят другие участники.

Поведение:

* ``message``/``edited_message`` не из личного чата — обновление игнорируется;
* ``callback_query`` не из личного чата — безопасный ``answer()`` без
  персональных данных, обработка останавливается;
* ``callback_query`` без ``message`` (inline-режим) или с неопределимым чатом —
  запрещается (**fail closed**);
* ``InaccessibleMessage`` содержит ``chat``, поэтому проверяется так же, как
  обычное сообщение;
* личный чат — обновление проходит без изменений.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Chat, TelegramObject, Update

from barberbot.messages import PRIVATE_CHAT_ONLY

logger = logging.getLogger(__name__)


def _is_private_chat(chat: Chat | None) -> bool:
    """Достоверно ли, что чат личный. ``None`` трактуется как «нет»."""
    return chat is not None and chat.type == ChatType.PRIVATE


def _callback_chat(callback: CallbackQuery) -> Chat | None:
    """Чат, к которому относится callback, или ``None``.

    Telegram присылает либо ``Message``, либо ``InaccessibleMessage`` (старое
    или удалённое сообщение) — у обоих есть ``chat``. Для callback без
    ``message`` (inline-режим) чат неизвестен.
    """
    message = callback.message
    if message is None:
        return None
    return message.chat


async def _reject_callback(callback: CallbackQuery) -> None:
    """Подтвердить callback безопасным текстом, чтобы не осталось загрузки."""
    logger.info(
        "Клиентский callback отклонён вне личного чата (callback id=%s)",
        callback.id,
    )
    try:
        await callback.answer(PRIVATE_CHAT_ONLY, show_alert=True)
    except TelegramAPIError:
        logger.warning("Не удалось подтвердить отклонённый callback")


class PrivateChatOnlyMiddleware(BaseMiddleware):
    """Разрешать клиентские обновления только из личных чатов."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        message = event.message or event.edited_message
        if message is not None:
            if not _is_private_chat(message.chat):
                logger.info(
                    "Обновление из чата типа %s проигнорировано", message.chat.type
                )
                return None
            return await handler(event, data)

        callback = event.callback_query
        if callback is not None:
            if not _is_private_chat(_callback_chat(callback)):
                await _reject_callback(callback)
                return None
            return await handler(event, data)

        return await handler(event, data)


__all__ = ["PrivateChatOnlyMiddleware"]
