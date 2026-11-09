"""Интеграционные тесты админ-панели: Dispatcher + реальная PostgreSQL.

Обновления подаются в настоящий ``Dispatcher`` с настоящим ``AdminService``;
Telegram не вызывается (``FakeSession`` записывает методы Bot API). Работаем
только с тестовой базой ``barberbot_test`` через фикстуры ``sessions`` и
``factory``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from barberbot.admin import callbacks as admin_cb
from barberbot.admin import texts as admin_texts
from barberbot.admin.fsm import AdminFlow
from barberbot.admin.service import AdminService
from barberbot.app import build_dispatcher
from barberbot.booking.service import BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.db.models import Booking, BookingStatus, Service
from barberbot.messages import PRIVATE_CHAT_ONLY, STALE_CALLBACK

from .chat import Chat
from .conftest import (
    FakeSession,
    build_update,
    callback_answers,
    callback_payload,
    edited_messages,
    message_payload,
    sent_messages,
)
from .fakes import FakeBookingService

ADMIN_ID = 900000001
OTHER_ID = 900000002


class BrokenSessions:
    """Фабрика сессий, имитирующая недоступную PostgreSQL."""

    def __call__(self) -> None:
        raise OperationalError(
            "SELECT secret_column FROM secret_table", {}, Exception("boom")
        )


def at(hour: int, minute: int = 0, day: int = 7) -> datetime:
    return datetime(2030, 1, day, hour, minute, tzinfo=MOSCOW)


@pytest_asyncio.fixture
async def admin_service(sessions: Any) -> AdminService:
    return AdminService(sessions, admin_ids=frozenset({ADMIN_ID}), clock=lambda: at(8))


@pytest_asyncio.fixture
async def panel(
    booking_service: BookingService, admin_service: AdminService
) -> Dispatcher:
    return build_dispatcher(booking_service, admin_service)


@pytest_asyncio.fixture
async def admin_chat(panel: Dispatcher, bot: Bot, fake_session: FakeSession) -> Chat:
    return Chat(panel, bot, fake_session, user_id=ADMIN_ID)


def alert_text(session: FakeSession) -> str | None:
    answers = callback_answers(session)
    assert answers, "callback не подтверждён"
    return answers[-1].text


def last_keyboard(session: FakeSession) -> list[str]:
    """Callback-данные кнопок последнего показанного сообщения."""
    return [data for data in _last_keyboard_buttons(session) if data is not None]


def last_button_texts(session: FakeSession) -> list[str]:
    for request in reversed(session.requests):
        if getattr(request, "reply_markup", None) is None:
            continue
        return [
            button.text
            for row in request.reply_markup.inline_keyboard
            for button in row
        ]
    raise AssertionError("Бот не отправил сообщение с клавиатурой")


def _last_keyboard_buttons(session: FakeSession) -> list[str | None]:
    for request in reversed(session.requests):
        if getattr(request, "reply_markup", None) is None:
            continue
        return [
            button.callback_data
            for row in request.reply_markup.inline_keyboard
            for button in row
        ]
    raise AssertionError("Бот не отправил сообщение с клавиатурой")


async def add_time_off_rows(factory: Any, barber_id: int, count: int) -> list[Any]:
    """Создать ``count`` непересекающихся минутных периодов отсутствия."""
    return [
        await factory.time_off(
            barber_id=barber_id,
            starts_at=at(10, 0, day=8 + offset),
            ends_at=at(12, 0, day=8 + offset),
        )
        for offset in range(count)
    ]


async def page_of_service(admin_service: AdminService, service_id: int) -> int:
    first = await admin_service.list_services(actor_telegram_id=ADMIN_ID)
    for page in range(first.page.pages):
        result = await admin_service.list_services(
            actor_telegram_id=ADMIN_ID, page=page
        )
        if any(row.id == service_id for row in result.rows):
            return page
    raise AssertionError("Услуга не найдена ни на одной странице")


async def page_of_barber(admin_service: AdminService, barber_id: int) -> int:
    first = await admin_service.list_barbers(actor_telegram_id=ADMIN_ID)
    for page in range(first.page.pages):
        result = await admin_service.list_barbers(actor_telegram_id=ADMIN_ID, page=page)
        if any(row.id == barber_id for row in result.rows):
            return page
    raise AssertionError("Мастер не найден ни на одной странице")


async def booking_status(sessions: Any, booking_id: int) -> BookingStatus:
    async with sessions() as session:
        booking = await session.get(Booking, booking_id)
    assert booking is not None
    return booking.status


# --------------------------------------------------------------------------- #
# Меню и разделы
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_menu_leads_to_panel(
    admin_chat: Chat, fake_session: FakeSession
) -> None:
    await admin_chat.send("/start")

    assert admin_cb.AdminPanelCB().pack() in last_keyboard(fake_session)

    await admin_chat.press(admin_cb.AdminPanelCB().pack())

    assert admin_chat.text == admin_texts.PANEL_TEXT
    assert admin_cb.AdminServicesCB().pack() in last_keyboard(fake_session)


@pytest.mark.asyncio
async def test_services_section_shows_inactive_and_toggles(
    admin_chat: Chat, admin_service: AdminService, factory: Any, sessions: Any
) -> None:
    service = await factory.service(is_active=False)
    page = await page_of_service(admin_service, service.id)

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(admin_cb.AdminServicesCB(page=page).pack())
    assert any(service.name in label for label in last_button_texts(admin_chat.session))

    await admin_chat.press(admin_cb.AdminServiceCB(service_id=service.id).pack())
    assert "🔴 отключена" in admin_chat.text

    await admin_chat.press(admin_cb.AdminServiceToggleCB(service_id=service.id).pack())
    assert alert_text(admin_chat.session) == admin_texts.SERVICE_ENABLED_NOTE
    assert "✅ включена" in admin_chat.text

    async with sessions() as session:
        stored = await session.get(Service, service.id)
    assert stored is not None
    assert stored.is_active is True


@pytest.mark.asyncio
async def test_add_service_flow(admin_chat: Chat, factory: Any, sessions: Any) -> None:
    name = factory.unique("service")

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(admin_cb.AdminServiceAddCB().pack())
    assert admin_texts.ADD_SERVICE_NAME_PROMPT in admin_chat.text

    await admin_chat.type(name)
    assert admin_texts.ADD_SERVICE_PRICE_PROMPT in admin_chat.text

    # Некорректная цена не сбрасывает форму.
    await admin_chat.type("дорого")
    assert admin_texts.INVALID_PRICE in admin_chat.text
    await admin_chat.type("1200")
    assert admin_texts.ADD_SERVICE_DURATION_PROMPT in admin_chat.text
    await admin_chat.type("45")

    assert admin_texts.NOTE_SERVICE_CREATED in admin_chat.text
    assert name in admin_chat.text

    try:
        async with sessions() as session:
            created = await session.scalar(select(Service).where(Service.name == name))
        assert created is not None
        assert created.price_rub == 1200
        assert created.duration_minutes == 45
        assert created.is_active is True
    finally:
        async with sessions() as session, session.begin():
            await session.execute(delete(Service).where(Service.name == name))


@pytest.mark.asyncio
async def test_edit_service_price_flow(
    admin_chat: Chat, factory: Any, sessions: Any
) -> None:
    service = await factory.service(price=500)

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(
        admin_cb.AdminServiceEditCB(service_id=service.id, field="price").pack()
    )
    assert admin_chat.text == admin_texts.EDIT_SERVICE_PROMPTS["price"]

    await admin_chat.type("777")

    assert admin_texts.NOTE_SAVED in admin_chat.text
    async with sessions() as session:
        stored = await session.get(Service, service.id)
    assert stored is not None
    assert stored.price_rub == 777


@pytest.mark.asyncio
async def test_barber_schedule_conflict_is_explained(
    admin_chat: Chat,
    admin_service: AdminService,
    booking_service: BookingService,
    factory: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )
    page = await page_of_barber(admin_service, barber.id)

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(admin_cb.AdminBarbersCB(page=page).pack())
    await admin_chat.press(admin_cb.AdminBarberCB(barber_id=barber.id).pack())
    await admin_chat.press(admin_cb.AdminScheduleCB(barber_id=barber.id).pack())
    await admin_chat.press(
        admin_cb.AdminWeekdayCB(barber_id=barber.id, weekday=0).pack()
    )
    assert "рабочие часы дня «понедельник»" in admin_chat.text

    await admin_chat.type("10:00-17:00")

    assert "Изменение отклонено" in admin_chat.text
    assert f"запись №{booking.id}" in admin_chat.text

    view = await admin_service.get_barber(
        actor_telegram_id=ADMIN_ID, barber_id=barber.id
    )
    assert view.hours[0].start_time.hour == 9


@pytest.mark.asyncio
async def test_schedule_change_saves_hours(
    admin_chat: Chat, admin_service: AdminService, factory: Any
) -> None:
    barber = await factory.barber()
    page = await page_of_barber(admin_service, barber.id)

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(admin_cb.AdminBarbersCB(page=page).pack())
    await admin_chat.press(admin_cb.AdminScheduleCB(barber_id=barber.id).pack())
    await admin_chat.press(
        admin_cb.AdminWeekdayCB(barber_id=barber.id, weekday=1).pack()
    )
    await admin_chat.type("11:00-15:00")

    assert admin_texts.NOTE_SAVED in admin_chat.text
    view = await admin_service.get_barber(
        actor_telegram_id=ADMIN_ID, barber_id=barber.id
    )
    assert view.hours[1].start_time.hour == 11
    assert view.hours[1].end_time.hour == 15


@pytest.mark.asyncio
async def test_time_off_flow(
    admin_chat: Chat, admin_service: AdminService, factory: Any
) -> None:
    barber = await factory.barber()

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(admin_cb.AdminTimeOffCB(barber_id=barber.id).pack())
    await admin_chat.press(admin_cb.AdminTimeOffAddCB(barber_id=barber.id).pack())
    assert admin_chat.text == admin_texts.TIME_OFF_PROMPT

    await admin_chat.type("08.01.2030-09.01.2030")

    assert admin_texts.NOTE_TIME_OFF_ADDED in admin_chat.text
    assert "08.01.2030–09.01.2030" in admin_chat.text

    rows = await admin_service.list_time_off(
        actor_telegram_id=ADMIN_ID, barber_id=barber.id
    )
    time_off_id = rows.rows[0].id

    await admin_chat.press(
        admin_cb.AdminTimeOffRemoveCB(
            barber_id=barber.id, time_off_id=time_off_id
        ).pack()
    )
    assert alert_text(admin_chat.session) == admin_texts.NOTE_TIME_OFF_REMOVED
    rows = await admin_service.list_time_off(
        actor_telegram_id=ADMIN_ID, barber_id=barber.id
    )
    assert rows.rows == []


@pytest.mark.asyncio
async def test_time_off_pagination_next_and_previous(
    admin_chat: Chat, factory: Any
) -> None:
    barber = await factory.barber()
    rows = await add_time_off_rows(factory, barber.id, 7)
    first_page = admin_cb.AdminTimeOffCB(barber_id=barber.id, page=0).pack()
    second_page = admin_cb.AdminTimeOffCB(barber_id=barber.id, page=1).pack()

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(first_page)

    assert "Страница 1 из 2." in admin_chat.text
    assert admin_texts.time_off_period(rows[0]) in admin_chat.text
    assert admin_texts.time_off_period(rows[5]) not in admin_chat.text
    assert second_page in last_keyboard(admin_chat.session)
    # На первой странице нет кнопки «◀️»: предыдущей страницы не существует.
    assert admin_cb.AdminTimeOffCB(barber_id=barber.id, page=-1).pack() not in (
        last_keyboard(admin_chat.session)
    )

    await admin_chat.press(second_page)

    assert "Страница 2 из 2." in admin_chat.text
    assert admin_texts.time_off_period(rows[5]) in admin_chat.text
    assert admin_texts.time_off_period(rows[6]) in admin_chat.text
    assert admin_texts.time_off_period(rows[0]) not in admin_chat.text
    assert first_page in last_keyboard(admin_chat.session)
    # На последней странице нет кнопки «◀️»... то есть «▶️».
    assert admin_cb.AdminTimeOffCB(barber_id=barber.id, page=2).pack() not in (
        last_keyboard(admin_chat.session)
    )

    await admin_chat.press(first_page)

    assert "Страница 1 из 2." in admin_chat.text
    assert admin_texts.time_off_period(rows[0]) in admin_chat.text


@pytest.mark.asyncio
async def test_time_off_keyboard_remove_buttons_carry_current_page(
    admin_chat: Chat, factory: Any
) -> None:
    barber = await factory.barber()
    rows = await add_time_off_rows(factory, barber.id, 6)

    await admin_chat.press(admin_cb.AdminTimeOffCB(barber_id=barber.id, page=1).pack())

    assert "Страница 2 из 2." in admin_chat.text
    assert admin_cb.AdminTimeOffRemoveCB(
        barber_id=barber.id, time_off_id=rows[5].id, page=1
    ).pack() in last_keyboard(admin_chat.session)


@pytest.mark.asyncio
async def test_removing_last_row_of_last_page_shows_previous_page(
    admin_chat: Chat, admin_service: AdminService, factory: Any
) -> None:
    barber = await factory.barber()
    rows = await add_time_off_rows(factory, barber.id, 6)

    await admin_chat.press(admin_cb.AdminTimeOffCB(barber_id=barber.id, page=1).pack())
    assert "Страница 2 из 2." in admin_chat.text

    await admin_chat.press(
        admin_cb.AdminTimeOffRemoveCB(
            barber_id=barber.id, time_off_id=rows[5].id, page=1
        ).pack()
    )

    assert alert_text(admin_chat.session) == admin_texts.NOTE_TIME_OFF_REMOVED
    # Последняя страница опустела: показывается предыдущая (теперь единственная).
    assert "Страница 2 из 2." not in admin_chat.text
    assert all(admin_texts.time_off_period(row) in admin_chat.text for row in rows[:5])
    assert admin_texts.time_off_period(rows[5]) not in admin_chat.text
    page = await admin_service.list_time_off(
        actor_telegram_id=ADMIN_ID, barber_id=barber.id
    )
    assert (page.total, page.page.pages) == (5, 1)


@pytest.mark.asyncio
async def test_removing_last_period_shows_empty_state(
    admin_chat: Chat, factory: Any
) -> None:
    barber = await factory.barber()
    rows = await add_time_off_rows(factory, barber.id, 1)

    await admin_chat.press(admin_cb.AdminTimeOffCB(barber_id=barber.id).pack())
    await admin_chat.press(
        admin_cb.AdminTimeOffRemoveCB(
            barber_id=barber.id, time_off_id=rows[0].id
        ).pack()
    )

    assert "Периодов отсутствия нет." in admin_chat.text
    assert admin_texts.time_off_period(rows[0]) not in admin_chat.text


@pytest.mark.asyncio
async def test_time_off_page_default_and_legacy_callback(
    admin_chat: Chat, factory: Any
) -> None:
    barber = await factory.barber()
    await add_time_off_rows(factory, barber.id, 1)

    # Кнопки без явной страницы продолжают открывать первую страницу.
    await admin_chat.press(admin_cb.AdminTimeOffCB(barber_id=barber.id).pack())
    assert admin_chat.text.startswith("🚫 Отсутствия")

    admin_chat.reset()
    # Старый callback без поля page не ломает бота: его разбирает fallback.
    await admin_chat.press(f"adm_timeoff:{barber.id}")

    assert alert_text(admin_chat.session) == STALE_CALLBACK
    assert edited_messages(admin_chat.session) == []


@pytest.mark.asyncio
async def test_regular_user_cannot_open_time_off_page(
    panel: Dispatcher, bot: Bot, fake_session: FakeSession, factory: Any
) -> None:
    barber = await factory.barber()
    await add_time_off_rows(factory, barber.id, 6)
    chat = Chat(panel, bot, fake_session, user_id=OTHER_ID)

    await chat.press(admin_cb.AdminTimeOffCB(barber_id=barber.id, page=1).pack())

    assert alert_text(fake_session) == admin_texts.ACCESS_DENIED
    assert edited_messages(fake_session) == []


# --------------------------------------------------------------------------- #
# Записи клиентов
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_cancels_booking_with_confirmation(
    admin_chat: Chat,
    booking_service: BookingService,
    factory: Any,
    sessions: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
        display_name="Клиент Тест",
    )

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(admin_cb.AdminFilterBarberSetCB(barber_id=barber.id).pack())
    assert f"мастер — {barber.name}" in admin_chat.text

    await admin_chat.press(admin_cb.AdminBookingCB(booking_id=booking.id).pack())
    assert f"Запись №{booking.id}" in admin_chat.text
    assert "Клиент Тест" in admin_chat.text

    await admin_chat.press(admin_cb.AdminBookingCancelCB(booking_id=booking.id).pack())
    assert "Отменить запись клиента" in admin_chat.text

    await admin_chat.press(
        admin_cb.AdminBookingCancelConfirmCB(booking_id=booking.id).pack()
    )
    assert admin_texts.NOTE_BOOKING_CANCELLED == alert_text(admin_chat.session)
    assert "Запись отменена" in admin_chat.text
    assert await booking_status(sessions, booking.id) == BookingStatus.CANCELLED


@pytest.mark.asyncio
async def test_repeated_cancel_from_stale_button_is_safe(
    admin_chat: Chat,
    booking_service: BookingService,
    factory: Any,
    sessions: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    booking = await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )
    confirm = admin_cb.AdminBookingCancelConfirmCB(booking_id=booking.id).pack()

    await admin_chat.press(confirm)
    assert await booking_status(sessions, booking.id) == BookingStatus.CANCELLED

    await admin_chat.press(confirm)

    assert alert_text(admin_chat.session) == admin_texts.BOOKING_ALREADY_CANCELLED
    assert await booking_status(sessions, booking.id) == BookingStatus.CANCELLED


@pytest.mark.asyncio
async def test_bookings_date_filter_and_reset(
    admin_chat: Chat,
    booking_service: BookingService,
    factory: Any,
) -> None:
    barber = await factory.barber()
    service = await factory.service()
    await booking_service.create_booking(
        telegram_id=factory.telegram_id(),
        barber_id=barber.id,
        service_id=service.id,
        starts_at=at(9),
    )

    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(admin_cb.AdminFilterDateCB().pack())
    assert admin_chat.text == admin_texts.BOOKINGS_DATE_PROMPT

    await admin_chat.type("07.01.2030")
    assert "дата — 07.01.2030" in admin_chat.text

    await admin_chat.press(admin_cb.AdminFilterResetCB().pack())
    assert alert_text(admin_chat.session) == admin_texts.NOTE_FILTERS_RESET
    assert "Фильтры: не заданы." in admin_chat.text


@pytest.mark.asyncio
async def test_invalid_date_keeps_filter_step(admin_chat: Chat) -> None:
    await admin_chat.press(admin_cb.AdminPanelCB().pack())
    await admin_chat.press(admin_cb.AdminFilterDateCB().pack())

    await admin_chat.type("вчера")

    assert admin_chat.text == admin_texts.INVALID_DATE
    assert await admin_chat.state() == AdminFlow.bookings_date_filter.state


# --------------------------------------------------------------------------- #
# Потеря FSM, доступ и группы
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_lost_fsm_data_is_reported(
    admin_chat: Chat, panel: Dispatcher, bot: Bot
) -> None:
    context = panel.fsm.get_context(bot=bot, chat_id=ADMIN_ID, user_id=ADMIN_ID)
    await context.set_state(AdminFlow.service_edit_value)

    await admin_chat.type("Стрижка")

    assert admin_texts.SESSION_EXPIRED in admin_chat.text
    assert admin_cb.AdminServicesCB().pack() in last_keyboard(admin_chat.session)
    assert await admin_chat.state() is None


@pytest.mark.asyncio
async def test_regular_user_cannot_use_panel_against_real_database(
    panel: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    factory: Any,
    admin_service: AdminService,
) -> None:
    service = await factory.service(is_active=False)
    chat = Chat(panel, bot, fake_session, user_id=OTHER_ID)

    await chat.send("/start")
    assert admin_cb.AdminPanelCB().pack() not in last_keyboard(fake_session)

    await chat.press(admin_cb.AdminServicesCB(page=0).pack())

    assert alert_text(fake_session) == admin_texts.ACCESS_DENIED
    assert edited_messages(fake_session) == []

    unchanged = await admin_service.get_service(
        actor_telegram_id=ADMIN_ID, service_id=service.id
    )
    assert unchanged.is_active is False


@pytest.mark.asyncio
async def test_admin_callback_from_group_is_blocked(
    panel: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    update = build_update(
        bot,
        {
            "update_id": 5,
            "callback_query": callback_payload(
                admin_cb.AdminPanelCB().pack(),
                user_id=ADMIN_ID,
                chat_type="supergroup",
            ),
        },
    )

    await panel.feed_update(bot, update)

    assert alert_text(fake_session) == PRIVATE_CHAT_ONLY
    assert edited_messages(fake_session) == []


@pytest.mark.asyncio
async def test_database_error_in_panel_hides_internals(
    bot: Bot, fake_session: FakeSession
) -> None:
    broken = AdminService(
        BrokenSessions(),  # type: ignore[arg-type]
        admin_ids=frozenset({ADMIN_ID}),
        clock=lambda: at(8),
    )
    dispatcher = build_dispatcher(FakeBookingService(), broken)  # type: ignore[arg-type]
    chat = Chat(dispatcher, bot, fake_session, user_id=ADMIN_ID)

    await chat.press(admin_cb.AdminServicesCB(page=0).pack())

    assert alert_text(fake_session) == admin_texts.DATABASE_ERROR
    assert admin_texts.DATABASE_ERROR in chat.text
    assert "SELECT" not in chat.text
    assert "secret" not in chat.text


@pytest.mark.asyncio
async def test_admin_message_in_group_is_ignored(
    panel: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    update = build_update(
        bot,
        {
            "update_id": 6,
            "message": message_payload("/start", user_id=ADMIN_ID, chat_type="group"),
        },
    )

    await panel.feed_update(bot, update)

    assert fake_session.requests == []
    assert sent_messages(fake_session) == []
