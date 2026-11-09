"""Обработчики команд и кнопок."""

from __future__ import annotations

from aiogram import Router

from barberbot.handlers.admin import build_router as build_admin_router
from barberbot.handlers.booking import build_router as build_booking_router
from barberbot.handlers.common import build_router as build_common_router
from barberbot.handlers.fallback import build_router as build_fallback_router
from barberbot.handlers.my_bookings import build_router as build_bookings_router
from barberbot.handlers.services import build_router as build_services_router


def build_main_router(admin_ids: frozenset[int] = frozenset()) -> Router:
    """Собрать корневой роутер приложения из роутеров разделов.

    Админ-панель подключается после клиентских разделов, fallback — последним:
    он обрабатывает только те callback, которые не подошли ни одному разделу
    или пришли не на текущем шаге FSM. ``admin_ids`` — единственный источник
    прав для guard-мидлвари панели (пустой список запрещает всё).
    """
    router = Router(name="main")
    router.include_router(build_common_router())
    router.include_router(build_services_router())
    router.include_router(build_booking_router())
    router.include_router(build_bookings_router())
    router.include_router(build_admin_router(admin_ids))
    router.include_router(build_fallback_router())
    return router


__all__ = ["build_main_router"]
