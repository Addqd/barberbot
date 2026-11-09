"""Единая точка обновления сообщения с inline-клавиатурой.

Сообщение по возможности редактируется, чтобы не засорять чат. Если сообщение
недоступно (старое или удалённое) или Telegram не разрешает редактирование,
бот отправляет новое сообщение.
"""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

MESSAGE_NOT_MODIFIED = "message is not modified"


async def render(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    """Показать ``text`` и ``keyboard``, отредактировав текущее сообщение."""
    message = callback.message
    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as error:
            if MESSAGE_NOT_MODIFIED in str(error):
                return
            logger.warning(
                "Не удалось отредактировать сообщение (%s), отправляем новое",
                type(error).__name__,
            )
            await message.answer(text, reply_markup=keyboard)
        return

    if message is not None:
        # InaccessibleMessage: редактирование недоступно, но ответ — да.
        await message.answer(text, reply_markup=keyboard)
        return

    bot = callback.bot
    if bot is None:  # pragma: no cover - защита от невозможного состояния
        logger.warning("Нет доступа к Bot для ответа на callback")
        return
    await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)


__all__ = ["render"]
