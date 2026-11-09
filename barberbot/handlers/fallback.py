"""Fallback для нераспознанных и устаревших callback-кнопок.

Сюда попадают нажатия с неверным префиксом/полями/типами, а также кнопки,
нажатые не на текущем шаге FSM. Callback всегда подтверждается, чтобы у
пользователя не оставался индикатор загрузки.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import CallbackQuery

from barberbot.messages import STALE_CALLBACK

logger = logging.getLogger(__name__)


async def handle_stale_callback(callback: CallbackQuery) -> None:
    logger.info(
        "Устаревший или неизвестный callback от пользователя id=%s",
        callback.from_user.id,
    )
    await callback.answer(STALE_CALLBACK, show_alert=True)


def build_router() -> Router:
    router = Router(name="fallback")
    router.callback_query.register(handle_stale_callback)
    return router


__all__ = ["build_router", "handle_stale_callback"]
