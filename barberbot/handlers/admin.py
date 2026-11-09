"""Административная панель: guard-мидлварь и обработчики Telegram-интерфейса.

Права администратора проверяются дважды и всегда по ``event.from_user.id``:

* middleware роутера панели — до вызова любого административного обработчика
  (fail closed: пустой список администраторов запрещает всё);
* каждый метод :class:`barberbot.admin.service.AdminService` — повторно, в
  бизнес-логике.

Используется **inner** middleware: ``outer_middleware`` роутера выполняется до
проверки фильтров и срабатывал бы на любые сообщения пользователей, которые к
панели не относятся, а inner — только для уже сопоставленного обработчика.

``PrivateChatOnlyMiddleware`` на уровне dispatcher уже запрещает не-личные
чаты для всех обновлений, поэтому проверка типа чата здесь не дублируется.

Идентификаторы из ``callback_data`` — недоверенный ввод: они всегда
перепроверяются по актуальным данным PostgreSQL, а действие выполняет сервис.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from aiogram import BaseMiddleware, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from barberbot import fsm
from barberbot.admin import callbacks as admin_cb
from barberbot.admin import keyboards, texts
from barberbot.admin.errors import AdminError, AdminValidationError
from barberbot.admin.fsm import (
    BARBER_ID,
    EDIT_FIELD,
    FILTER_BARBER,
    FILTER_BARBER_NAME,
    FILTER_DAY,
    NEW_NAME,
    NEW_PRICE,
    SERVICE_ID,
    WEEKDAY,
    AdminFlow,
)
from barberbot.admin.service import (
    AdminService,
    BarbersPage,
    BarberView,
    BookingsPage,
    ServicesPage,
    TimeOffPage,
    check_weekday,
    parse_barber_name,
    parse_day,
    parse_duration,
    parse_period,
    parse_price,
    parse_service_name,
    parse_working_hours,
)
from barberbot.db.models import Booking, BookingStatus, Service
from barberbot.handlers.render import render

logger = logging.getLogger(__name__)

#: Допустимые поля правки услуги (значения приходят из callback-данных).
_SERVICE_FIELDS = frozenset({"name", "price", "duration"})


# --------------------------------------------------------------------------- #
# Проверка прав
# --------------------------------------------------------------------------- #


class AdminOnlyMiddleware(BaseMiddleware):
    """Пропускать к панели только Telegram ID из ``ADMIN_TELEGRAM_IDS``."""

    def __init__(self, admin_ids: frozenset[int]) -> None:
        self._admin_ids = frozenset(admin_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id not in self._admin_ids:
            await self._reject(event)
            return None
        return await handler(event, data)

    async def _reject(self, event: TelegramObject) -> None:
        logger.warning("Отклонено обращение к админ-панели без прав")
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(texts.ACCESS_DENIED, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(texts.ACCESS_DENIED)
        except TelegramAPIError:
            logger.warning("Не удалось отправить отказ в доступе")


def _actor(event: CallbackQuery | Message) -> int:
    """Telegram ID отправителя. Значение проверено guard-мидлварью."""
    user = event.from_user
    return user.id if user is not None else 0


# --------------------------------------------------------------------------- #
# Общие помощники
# --------------------------------------------------------------------------- #


async def _fail(callback: CallbackQuery, state: FSMContext, error: AdminError) -> None:
    """Показать доменную ошибку администратору и вернуть его в панель."""
    await callback.answer(str(error), show_alert=True)
    await state.clear()
    await render(
        callback,
        f"{error}\n\n{texts.PANEL_TEXT}",
        keyboards.panel_keyboard(),
    )


def _message_text(message: Message) -> str | None:
    """Текст сообщения или ``None`` (фото, стикеры и т.п.)."""
    text = message.text
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def _read_day(data: dict[str, Any]) -> date | None:
    value = data.get(FILTER_DAY)
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _read_text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _services_view(
    result: ServicesPage,
) -> tuple[str, InlineKeyboardMarkup]:
    page = result.page
    return (
        texts.services_text(
            result.rows,
            total=result.total,
            active=result.active,
            page=page.number,
            pages=page.pages,
        ),
        keyboards.services_keyboard(result.rows, page=page.number, pages=page.pages),
    )


def _barbers_view(result: BarbersPage) -> tuple[str, InlineKeyboardMarkup]:
    page = result.page
    return (
        texts.barbers_text(
            result.rows,
            total=result.total,
            active=result.active,
            page=page.number,
            pages=page.pages,
        ),
        keyboards.barbers_keyboard(
            result.rows,
            result.working_days,
            page=page.number,
            pages=page.pages,
        ),
    )


def _schedule_view(
    view: BarberView, note: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    text = texts.schedule_text(view.barber, view.hours)
    if note:
        text = f"{note}\n\n{text}"
    return text, keyboards.schedule_keyboard(view.barber, view.hours)


def _time_off_view(
    result: TimeOffPage, note: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    page = result.page
    text = texts.time_off_text(
        result.barber, result.rows, page=page.number, pages=page.pages
    )
    if note:
        text = f"{note}\n\n{text}"
    return (
        text,
        keyboards.time_off_keyboard(
            result.barber.id,
            result.rows,
            page=page.number,
            pages=page.pages,
        ),
    )


def _bookings_view(
    result: BookingsPage,
    *,
    on_date: date | None,
    barber_name: str | None,
) -> tuple[str, InlineKeyboardMarkup]:
    page = result.page
    return (
        texts.bookings_text(
            result.rows,
            total=result.page.total,
            page=page.number,
            pages=page.pages,
            filters=texts.filters_label(on_date, barber_name),
        ),
        keyboards.bookings_keyboard(
            result.rows,
            page=page.number,
            pages=page.pages,
            has_filters=on_date is not None or barber_name is not None,
        ),
    )


async def _send(message: Message, text: str, keyboard: InlineKeyboardMarkup) -> None:
    await message.answer(text, reply_markup=keyboard)


# --------------------------------------------------------------------------- #
# Панель
# --------------------------------------------------------------------------- #


async def open_panel(callback: CallbackQuery, state: FSMContext) -> None:
    """Открыть главную страницу панели; черновики и фильтры сбрасываются."""
    await callback.answer()
    await state.clear()
    await render(callback, texts.PANEL_TEXT, keyboards.panel_keyboard())


# --------------------------------------------------------------------------- #
# Услуги
# --------------------------------------------------------------------------- #


async def show_services(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminServicesCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.clear()
    try:
        result = await admin_service.list_services(
            actor_telegram_id=_actor(callback), page=callback_data.page
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer()
    await render(callback, *_services_view(result))


async def show_service(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminServiceCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.clear()
    try:
        service = await admin_service.get_service(
            actor_telegram_id=_actor(callback),
            service_id=callback_data.service_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer()
    await render(
        callback,
        texts.service_card_text(service),
        keyboards.service_card_keyboard(service),
    )


async def toggle_service(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminServiceToggleCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.set_state(None)
    try:
        service = await admin_service.toggle_service(
            actor_telegram_id=_actor(callback),
            service_id=callback_data.service_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    note = (
        texts.SERVICE_ENABLED_NOTE if service.is_active else texts.SERVICE_DISABLED_NOTE
    )
    await callback.answer(note)
    await render(
        callback,
        texts.service_card_text(service),
        keyboards.service_card_keyboard(service),
    )


async def start_add_service(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminFlow.service_add_name)
    await callback.answer()
    await render(
        callback,
        texts.ADD_SERVICE_NAME_PROMPT,
        keyboards.prompt_keyboard(admin_cb.AdminServicesCB()),
    )


async def add_service_name(message: Message, state: FSMContext) -> None:
    text = _message_text(message)
    if text is None:
        await message.answer(texts.TEXT_ONLY)
        return
    try:
        name = parse_service_name(text)
    except AdminValidationError as error:
        await message.answer(str(error))
        return
    await state.update_data({NEW_NAME: name})
    await state.set_state(AdminFlow.service_add_price)
    await message.answer(
        texts.ADD_SERVICE_PRICE_PROMPT,
        reply_markup=keyboards.prompt_keyboard(admin_cb.AdminServicesCB()),
    )


async def add_service_price(message: Message, state: FSMContext) -> None:
    text = _message_text(message)
    if text is None:
        await message.answer(texts.TEXT_ONLY)
        return
    try:
        price = parse_price(text)
    except AdminValidationError as error:
        await message.answer(str(error))
        return
    await state.update_data({NEW_PRICE: price})
    await state.set_state(AdminFlow.service_add_duration)
    await message.answer(
        texts.ADD_SERVICE_DURATION_PROMPT,
        reply_markup=keyboards.prompt_keyboard(admin_cb.AdminServicesCB()),
    )


async def add_service_duration(
    message: Message, state: FSMContext, admin_service: AdminService
) -> None:
    text = _message_text(message)
    if text is None:
        await message.answer(texts.TEXT_ONLY)
        return
    data = await state.get_data()
    name = _read_text(data, NEW_NAME)
    price = fsm.read_int(data, NEW_PRICE)
    if name is None or price is None:
        await state.clear()
        await message.answer(
            texts.SESSION_EXPIRED, reply_markup=keyboards.panel_keyboard()
        )
        return
    try:
        duration = parse_duration(text)
    except AdminValidationError as error:
        await message.answer(str(error))
        return

    try:
        service = await admin_service.create_service(
            actor_telegram_id=_actor(message),
            name=name,
            price_rub=price,
            duration_minutes=duration,
        )
    except AdminError as error:
        await state.clear()
        await message.answer(
            f"{error}\n\n{texts.PANEL_TEXT}",
            reply_markup=keyboards.panel_keyboard(),
        )
        return

    await state.clear()
    await _send(
        message,
        f"{texts.NOTE_SERVICE_CREATED}\n\n{texts.service_card_text(service)}",
        keyboards.service_card_keyboard(service),
    )


async def start_edit_service(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminServiceEditCB,
    state: FSMContext,
) -> None:
    field = callback_data.field
    if field not in _SERVICE_FIELDS:  # pragma: no cover - отсекается фильтром
        await state.clear()
        await callback.answer(texts.NOT_FOUND, show_alert=True)
        return
    await state.clear()
    await state.update_data({SERVICE_ID: callback_data.service_id, EDIT_FIELD: field})
    await state.set_state(AdminFlow.service_edit_value)
    await callback.answer()
    await render(
        callback,
        texts.EDIT_SERVICE_PROMPTS[field],
        keyboards.prompt_keyboard(
            admin_cb.AdminServiceCB(service_id=callback_data.service_id)
        ),
    )


async def save_service_value(
    message: Message, state: FSMContext, admin_service: AdminService
) -> None:
    data = await state.get_data()
    service_id = fsm.read_int(data, SERVICE_ID)
    field = _read_text(data, EDIT_FIELD)
    if service_id is None or field not in _SERVICE_FIELDS:
        await state.clear()
        await message.answer(
            texts.SESSION_EXPIRED, reply_markup=keyboards.panel_keyboard()
        )
        return
    text = _message_text(message)
    if text is None:
        await message.answer(texts.TEXT_ONLY)
        return

    try:
        service = await _update_service_field(
            admin_service,
            actor=_actor(message),
            service_id=service_id,
            field=field,
            value=text,
        )
    except AdminValidationError as error:
        # Остаёмся в том же шаге: администратор может повторить ввод.
        await message.answer(str(error))
        return
    except AdminError as error:
        await state.clear()
        await message.answer(str(error), reply_markup=keyboards.panel_keyboard())
        return

    await state.clear()
    await _send(
        message,
        f"{texts.NOTE_SAVED}\n\n{texts.service_card_text(service)}",
        keyboards.service_card_keyboard(service),
    )


async def _update_service_field(
    admin_service: AdminService,
    *,
    actor: int,
    service_id: int,
    field: str,
    value: str,
) -> Service:
    if field == "name":
        return await admin_service.update_service(
            actor_telegram_id=actor, service_id=service_id, name=value
        )
    if field == "price":
        return await admin_service.update_service(
            actor_telegram_id=actor,
            service_id=service_id,
            price_rub=parse_price(value),
        )
    return await admin_service.update_service(
        actor_telegram_id=actor,
        service_id=service_id,
        duration_minutes=parse_duration(value),
    )


# --------------------------------------------------------------------------- #
# Барберы
# --------------------------------------------------------------------------- #


async def show_barbers(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminBarbersCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.clear()
    try:
        result = await admin_service.list_barbers(
            actor_telegram_id=_actor(callback), page=callback_data.page
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer()
    await render(callback, *_barbers_view(result))


async def show_barber(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminBarberCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.clear()
    try:
        view = await admin_service.get_barber(
            actor_telegram_id=_actor(callback),
            barber_id=callback_data.barber_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer()
    await render(
        callback,
        texts.barber_card_text(view.barber, view.hours, view.time_off),
        keyboards.barber_card_keyboard(view.barber),
    )


async def toggle_barber(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminBarberToggleCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.set_state(None)
    try:
        barber = await admin_service.toggle_barber(
            actor_telegram_id=_actor(callback),
            barber_id=callback_data.barber_id,
        )
        view = await admin_service.get_barber(
            actor_telegram_id=_actor(callback), barber_id=barber.id
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    note = texts.BARBER_ENABLED_NOTE if barber.is_active else texts.BARBER_DISABLED_NOTE
    await callback.answer(note)
    await render(
        callback,
        texts.barber_card_text(view.barber, view.hours, view.time_off),
        keyboards.barber_card_keyboard(view.barber),
    )


async def start_add_barber(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminFlow.barber_add_name)
    await callback.answer()
    await render(
        callback,
        texts.ADD_BARBER_NAME_PROMPT,
        keyboards.prompt_keyboard(admin_cb.AdminBarbersCB()),
    )


async def add_barber_name(
    message: Message, state: FSMContext, admin_service: AdminService
) -> None:
    text = _message_text(message)
    if text is None:
        await message.answer(texts.TEXT_ONLY)
        return
    try:
        name = parse_barber_name(text)
    except AdminValidationError as error:
        await message.answer(str(error))
        return

    try:
        barber = await admin_service.create_barber(
            actor_telegram_id=_actor(message), name=name
        )
        view = await admin_service.get_barber(
            actor_telegram_id=_actor(message), barber_id=barber.id
        )
    except AdminError as error:
        await state.clear()
        await message.answer(
            f"{error}\n\n{texts.PANEL_TEXT}",
            reply_markup=keyboards.panel_keyboard(),
        )
        return

    await state.clear()
    await _send(
        message,
        f"{texts.NOTE_BARBER_CREATED}\n\n"
        f"{texts.barber_card_text(view.barber, view.hours, view.time_off)}",
        keyboards.barber_card_keyboard(view.barber),
    )


# --------------------------------------------------------------------------- #
# Расписание и отсутствия
# --------------------------------------------------------------------------- #


async def show_schedule(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminScheduleCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.set_state(None)
    try:
        view = await admin_service.get_barber(
            actor_telegram_id=_actor(callback),
            barber_id=callback_data.barber_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer()
    await render(callback, *_schedule_view(view))


async def start_edit_weekday(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminWeekdayCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    try:
        weekday = check_weekday(callback_data.weekday)
        view = await admin_service.get_barber(
            actor_telegram_id=_actor(callback),
            barber_id=callback_data.barber_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return

    await state.clear()
    await state.update_data({BARBER_ID: view.barber.id, WEEKDAY: weekday})
    await state.set_state(AdminFlow.working_hours)
    await callback.answer()
    await render(
        callback,
        texts.WORKING_HOURS_PROMPT.format(weekday=texts.weekday_name(weekday)),
        keyboards.prompt_keyboard(admin_cb.AdminScheduleCB(barber_id=view.barber.id)),
    )


async def save_working_hours(
    message: Message, state: FSMContext, admin_service: AdminService
) -> None:
    data = await state.get_data()
    barber_id = fsm.read_int(data, BARBER_ID)
    weekday = fsm.read_int(data, WEEKDAY)
    if barber_id is None or weekday is None:
        await state.clear()
        await message.answer(
            texts.SESSION_EXPIRED, reply_markup=keyboards.panel_keyboard()
        )
        return
    text = _message_text(message)
    if text is None:
        await message.answer(texts.TEXT_ONLY)
        return

    try:
        hours = parse_working_hours(text)
    except AdminValidationError as error:
        await message.answer(str(error))
        return

    actor = _actor(message)
    try:
        if hours is None:
            await admin_service.clear_working_hours(
                actor_telegram_id=actor,
                barber_id=barber_id,
                weekday=weekday,
            )
            note = texts.NOTE_SAVED
        else:
            start_time, end_time = hours
            await admin_service.set_working_hours(
                actor_telegram_id=actor,
                barber_id=barber_id,
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
            )
            note = texts.NOTE_SAVED
        view = await admin_service.get_barber(
            actor_telegram_id=actor, barber_id=barber_id
        )
    except AdminError as error:
        # Конфликт с будущими записями: причина показывается целиком,
        # администратор остаётся в расписании этого мастера.
        await state.set_state(None)
        try:
            view = await admin_service.get_barber(
                actor_telegram_id=actor, barber_id=barber_id
            )
        except AdminError:
            await message.answer(
                f"{error}\n\n{texts.PANEL_TEXT}",
                reply_markup=keyboards.panel_keyboard(),
            )
            return
        text_view, keyboard = _schedule_view(view)
        await _send(message, f"{error}\n\n{text_view}", keyboard)
        return

    await state.set_state(None)
    text_view, keyboard = _schedule_view(view, note)
    await _send(message, text_view, keyboard)


async def show_time_off(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminTimeOffCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.set_state(None)
    try:
        result = await admin_service.list_time_off(
            actor_telegram_id=_actor(callback),
            barber_id=callback_data.barber_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer()
    await render(callback, *_time_off_view(result))


async def start_add_time_off(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminTimeOffAddCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    try:
        view = await admin_service.get_barber(
            actor_telegram_id=_actor(callback),
            barber_id=callback_data.barber_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await state.clear()
    await state.update_data({BARBER_ID: view.barber.id})
    await state.set_state(AdminFlow.time_off_add)
    await callback.answer()
    await render(
        callback,
        texts.TIME_OFF_PROMPT,
        keyboards.prompt_keyboard(admin_cb.AdminTimeOffCB(barber_id=view.barber.id)),
    )


async def save_time_off(
    message: Message, state: FSMContext, admin_service: AdminService
) -> None:
    data = await state.get_data()
    barber_id = fsm.read_int(data, BARBER_ID)
    if barber_id is None:
        await state.clear()
        await message.answer(
            texts.SESSION_EXPIRED, reply_markup=keyboards.panel_keyboard()
        )
        return
    text = _message_text(message)
    if text is None:
        await message.answer(texts.TEXT_ONLY)
        return

    try:
        starts_at, ends_at = parse_period(text)
    except AdminValidationError as error:
        await message.answer(str(error))
        return

    actor = _actor(message)
    try:
        await admin_service.add_time_off(
            actor_telegram_id=actor,
            barber_id=barber_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        result = await admin_service.list_time_off(
            actor_telegram_id=actor, barber_id=barber_id
        )
    except AdminError as error:
        await state.set_state(None)
        try:
            result = await admin_service.list_time_off(
                actor_telegram_id=actor, barber_id=barber_id
            )
        except AdminError:
            await message.answer(
                f"{error}\n\n{texts.PANEL_TEXT}",
                reply_markup=keyboards.panel_keyboard(),
            )
            return
        text_view, keyboard = _time_off_view(result)
        await _send(message, f"{error}\n\n{text_view}", keyboard)
        return

    await state.set_state(None)
    text_view, keyboard = _time_off_view(result, texts.NOTE_TIME_OFF_ADDED)
    await _send(message, text_view, keyboard)


async def remove_time_off(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminTimeOffRemoveCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.set_state(None)
    actor = _actor(callback)
    try:
        await admin_service.remove_time_off(
            actor_telegram_id=actor,
            barber_id=callback_data.barber_id,
            time_off_id=callback_data.time_off_id,
        )
        result = await admin_service.list_time_off(
            actor_telegram_id=actor, barber_id=callback_data.barber_id
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer(texts.NOTE_TIME_OFF_REMOVED)
    await render(callback, *_time_off_view(result))


# --------------------------------------------------------------------------- #
# Записи клиентов
# --------------------------------------------------------------------------- #


def _filters(data: dict[str, Any]) -> tuple[date | None, int | None, str | None]:
    return (
        _read_day(data),
        fsm.read_int(data, FILTER_BARBER),
        _read_text(data, FILTER_BARBER_NAME),
    )


async def _load_bookings(
    admin_service: AdminService,
    *,
    actor: int,
    data: dict[str, Any],
    page: int,
) -> BookingsPage:
    on_date, barber_id, _ = _filters(data)
    return await admin_service.list_bookings(
        actor_telegram_id=actor,
        on_date=on_date,
        barber_id=barber_id,
        page=page,
    )


async def show_bookings(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminBookingsCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    """Список записей всех клиентов; фильтры берутся из данных FSM."""
    await state.set_state(None)
    data = await state.get_data()
    try:
        result = await _load_bookings(
            admin_service,
            actor=_actor(callback),
            data=data,
            page=callback_data.page,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    on_date, _, barber_name = _filters(data)
    await callback.answer()
    await render(
        callback, *_bookings_view(result, on_date=on_date, barber_name=barber_name)
    )


async def show_booking(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminBookingCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.set_state(None)
    try:
        booking = await admin_service.get_booking(
            actor_telegram_id=_actor(callback),
            booking_id=callback_data.booking_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer()
    await _render_booking(callback, booking)


async def _render_booking(callback: CallbackQuery, booking: Booking) -> None:
    await render(
        callback,
        texts.booking_card_text(booking),
        keyboards.booking_card_keyboard(
            booking, cancellable=booking.status == BookingStatus.CONFIRMED
        ),
    )


async def ask_cancel_booking(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminBookingCancelCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    await state.set_state(None)
    try:
        booking = await admin_service.get_booking(
            actor_telegram_id=_actor(callback),
            booking_id=callback_data.booking_id,
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    if booking.status != BookingStatus.CONFIRMED:
        reason = (
            texts.BOOKING_ALREADY_CANCELLED
            if booking.status == BookingStatus.CANCELLED
            else texts.BOOKING_COMPLETED
        )
        await callback.answer(reason, show_alert=True)
        await _render_booking(callback, booking)
        return
    await callback.answer()
    await render(
        callback,
        texts.cancel_prompt_text(booking),
        keyboards.booking_cancel_confirm_keyboard(booking.id),
    )


async def confirm_cancel_booking(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminBookingCancelConfirmCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    """Отменить запись после подтверждения; повторная отмена даёт ошибку."""
    await state.set_state(None)
    try:
        cancelled = await admin_service.cancel_booking(
            actor_telegram_id=_actor(callback),
            booking_id=callback_data.booking_id,
        )
    except AdminError as error:
        await callback.answer(str(error), show_alert=True)
        try:
            booking = await admin_service.get_booking(
                actor_telegram_id=_actor(callback),
                booking_id=callback_data.booking_id,
            )
        except AdminError:
            await _fail(callback, state, error)
            return
        await _render_booking(callback, booking)
        return
    await callback.answer(texts.NOTE_BOOKING_CANCELLED)
    await render(
        callback,
        texts.cancelled_text(cancelled),
        keyboards.booking_card_keyboard(cancelled, cancellable=False),
    )


async def start_filter_date(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.bookings_date_filter)
    await callback.answer()
    await render(
        callback,
        texts.BOOKINGS_DATE_PROMPT,
        keyboards.prompt_keyboard(admin_cb.AdminBookingsCB()),
    )


async def save_filter_date(
    message: Message, state: FSMContext, admin_service: AdminService
) -> None:
    text = _message_text(message)
    if text is None:
        await message.answer(texts.TEXT_ONLY)
        return
    try:
        day = parse_day(text)
    except AdminValidationError as error:
        await message.answer(str(error))
        return

    await state.update_data({FILTER_DAY: day.isoformat()})
    await state.set_state(None)
    data = await state.get_data()
    try:
        result = await _load_bookings(
            admin_service, actor=_actor(message), data=data, page=0
        )
    except AdminError as error:
        await state.clear()
        await message.answer(
            f"{error}\n\n{texts.PANEL_TEXT}",
            reply_markup=keyboards.panel_keyboard(),
        )
        return
    on_date, _, barber_name = _filters(data)
    text_view, keyboard = _bookings_view(
        result, on_date=on_date, barber_name=barber_name
    )
    await _send(message, text_view, keyboard)


async def start_filter_barber(
    callback: CallbackQuery, state: FSMContext, admin_service: AdminService
) -> None:
    data = await state.get_data()
    try:
        barbers = await admin_service.list_all_barbers(
            actor_telegram_id=_actor(callback)
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await state.set_state(None)
    await callback.answer()
    await render(
        callback,
        texts.FILTER_BARBER_PROMPT,
        keyboards.bookings_barber_filter_keyboard(
            barbers, current_barber_id=fsm.read_int(data, FILTER_BARBER)
        ),
    )


async def set_filter_barber(
    callback: CallbackQuery,
    callback_data: admin_cb.AdminFilterBarberSetCB,
    state: FSMContext,
    admin_service: AdminService,
) -> None:
    if callback_data.barber_id == 0:
        await state.update_data({FILTER_BARBER: None, FILTER_BARBER_NAME: None})
    else:
        try:
            view = await admin_service.get_barber(
                actor_telegram_id=_actor(callback),
                barber_id=callback_data.barber_id,
            )
        except AdminError as error:
            await _fail(callback, state, error)
            return
        await state.update_data(
            {FILTER_BARBER: view.barber.id, FILTER_BARBER_NAME: view.barber.name}
        )

    await state.set_state(None)
    data = await state.get_data()
    try:
        result = await _load_bookings(
            admin_service, actor=_actor(callback), data=data, page=0
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    on_date, _, barber_name = _filters(data)
    await callback.answer()
    await render(
        callback, *_bookings_view(result, on_date=on_date, barber_name=barber_name)
    )


async def reset_filters(
    callback: CallbackQuery, state: FSMContext, admin_service: AdminService
) -> None:
    await state.update_data(
        {FILTER_DAY: None, FILTER_BARBER: None, FILTER_BARBER_NAME: None}
    )
    await state.set_state(None)
    data = await state.get_data()
    try:
        result = await _load_bookings(
            admin_service, actor=_actor(callback), data=data, page=0
        )
    except AdminError as error:
        await _fail(callback, state, error)
        return
    await callback.answer(texts.NOTE_FILTERS_RESET)
    await render(callback, *_bookings_view(result, on_date=None, barber_name=None))


# --------------------------------------------------------------------------- #
# Роутер
# --------------------------------------------------------------------------- #


def build_router(admin_ids: frozenset[int] = frozenset()) -> Router:
    """Роутер админ-панели; при пустом списке ID все действия запрещены."""
    router = Router(name="admin")
    guard = AdminOnlyMiddleware(admin_ids)
    router.callback_query.middleware(guard)
    router.message.middleware(guard)

    router.callback_query.register(open_panel, admin_cb.AdminPanelCB.filter())

    router.callback_query.register(show_services, admin_cb.AdminServicesCB.filter())
    router.callback_query.register(show_service, admin_cb.AdminServiceCB.filter())
    router.callback_query.register(
        toggle_service, admin_cb.AdminServiceToggleCB.filter()
    )
    router.callback_query.register(
        start_edit_service, admin_cb.AdminServiceEditCB.filter()
    )
    router.callback_query.register(
        start_add_service, admin_cb.AdminServiceAddCB.filter()
    )

    router.callback_query.register(show_barbers, admin_cb.AdminBarbersCB.filter())
    router.callback_query.register(show_barber, admin_cb.AdminBarberCB.filter())
    router.callback_query.register(toggle_barber, admin_cb.AdminBarberToggleCB.filter())
    router.callback_query.register(start_add_barber, admin_cb.AdminBarberAddCB.filter())
    router.callback_query.register(show_schedule, admin_cb.AdminScheduleCB.filter())
    router.callback_query.register(start_edit_weekday, admin_cb.AdminWeekdayCB.filter())
    router.callback_query.register(show_time_off, admin_cb.AdminTimeOffCB.filter())
    router.callback_query.register(
        start_add_time_off, admin_cb.AdminTimeOffAddCB.filter()
    )
    router.callback_query.register(
        remove_time_off, admin_cb.AdminTimeOffRemoveCB.filter()
    )

    router.callback_query.register(show_bookings, admin_cb.AdminBookingsCB.filter())
    router.callback_query.register(show_booking, admin_cb.AdminBookingCB.filter())
    router.callback_query.register(
        ask_cancel_booking, admin_cb.AdminBookingCancelCB.filter()
    )
    router.callback_query.register(
        confirm_cancel_booking, admin_cb.AdminBookingCancelConfirmCB.filter()
    )
    router.callback_query.register(
        start_filter_date, admin_cb.AdminFilterDateCB.filter()
    )
    router.callback_query.register(
        start_filter_barber, admin_cb.AdminFilterBarberCB.filter()
    )
    router.callback_query.register(
        set_filter_barber, admin_cb.AdminFilterBarberSetCB.filter()
    )
    router.callback_query.register(reset_filters, admin_cb.AdminFilterResetCB.filter())

    router.message.register(add_service_name, StateFilter(AdminFlow.service_add_name))
    router.message.register(add_service_price, StateFilter(AdminFlow.service_add_price))
    router.message.register(
        add_service_duration, StateFilter(AdminFlow.service_add_duration)
    )
    router.message.register(
        save_service_value, StateFilter(AdminFlow.service_edit_value)
    )
    router.message.register(add_barber_name, StateFilter(AdminFlow.barber_add_name))
    router.message.register(save_working_hours, StateFilter(AdminFlow.working_hours))
    router.message.register(save_time_off, StateFilter(AdminFlow.time_off_add))
    router.message.register(
        save_filter_date, StateFilter(AdminFlow.bookings_date_filter)
    )
    return router


__all__ = ["AdminOnlyMiddleware", "build_router"]
