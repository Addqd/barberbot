"""Обработчики команд и кнопок."""

from __future__ import annotations

from aiogram import Router

from barberbot.handlers.common import build_router as build_common_router


def build_main_router() -> Router:
    """Собрать корневой роутер приложения из роутеров разделов."""
    router = Router(name="main")
    router.include_router(build_common_router())
    return router
