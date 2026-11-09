"""Раздел «💈 Услуги и цены»: данные только из активного каталога БД."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from barberbot.booking.errors import DatabaseUnavailable
from barberbot.booking.service import BookingService
from barberbot.callbacks import MenuServicesCB
from barberbot.handlers.render import render
from barberbot.keyboards import main_menu_keyboard
from barberbot.messages import services_section_text


async def show_services(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    """Показать активные услуги, цены и длительность из PostgreSQL."""
    await callback.answer()
    await state.clear()
    try:
        services = await booking_service.list_active_services()
    except DatabaseUnavailable as error:
        await render(callback, str(error), main_menu_keyboard())
        return
    await render(callback, services_section_text(services), main_menu_keyboard())


def build_router() -> Router:
    router = Router(name="services")
    router.callback_query.register(show_services, MenuServicesCB.filter())
    return router


__all__ = ["build_router", "show_services"]
