"""Авторизация администратора: меню, guard и подделанные callback.

Тесты не обращаются к базе данных: проверяется граница доступа. Обращения к
сервису в запрещённых сценариях фиксируются строгой заглушкой, которая падает
при любой попытке вызвать административную операцию.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Message

from barberbot.admin import callbacks as admin_cb
from barberbot.admin import texts as admin_texts
from barberbot.admin.service import AdminService
from barberbot.app import build_dispatcher
from barberbot.handlers.admin import AdminOnlyMiddleware
from barberbot.messages import PRIVATE_CHAT_ONLY, STALE_CALLBACK

from .conftest import (
    FakeSession,
    build_update,
    callback_answers,
    callback_payload,
    edited_messages,
    message_payload,
    sent_messages,
)
from .fakes import FakeAdminService, FakeBookingService

ADMIN_ID = 700000001
OTHER_ID = 700000002


class StrictAdminService:
    """Заглушка сервиса: любое административное действие считается утечкой."""

    def __init__(self, admin_ids: frozenset[int]) -> None:
        self.admin_ids = frozenset(admin_ids)

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"Административный сервис не должен вызываться: {name}")


@pytest.fixture
def admin_dispatcher(booking_service_stub: FakeBookingService) -> Dispatcher:
    return build_dispatcher(  # type: ignore[arg-type]
        booking_service_stub,
        FakeAdminService(frozenset({ADMIN_ID})),  # type: ignore[arg-type]
    )


@pytest.fixture
def strict_dispatcher(booking_service_stub: FakeBookingService) -> Dispatcher:
    return build_dispatcher(  # type: ignore[arg-type]
        booking_service_stub,
        StrictAdminService(frozenset({ADMIN_ID})),  # type: ignore[arg-type]
    )


async def start(
    dispatcher: Dispatcher, bot: Bot, *, user_id: int, chat_type: str = "private"
) -> None:
    update = build_update(
        bot,
        {
            "update_id": 1,
            "message": message_payload("/start", user_id=user_id, chat_type=chat_type),
        },
    )
    await dispatcher.feed_update(bot, update)


async def press(
    dispatcher: Dispatcher,
    bot: Bot,
    data: str,
    *,
    user_id: int,
    chat_type: str = "private",
) -> None:
    update = build_update(
        bot,
        {
            "update_id": 2,
            "callback_query": callback_payload(
                data, user_id=user_id, chat_type=chat_type
            ),
        },
    )
    await dispatcher.feed_update(bot, update)


def menu_buttons(session: FakeSession) -> list[str]:
    message = sent_messages(session)[-1]
    assert message.reply_markup is not None
    return [
        button.text for row in message.reply_markup.inline_keyboard for button in row
    ]


def alert_text(session: FakeSession) -> str | None:
    answers = callback_answers(session)
    assert answers, "callback не подтверждён"
    return answers[-1].text


@pytest.mark.asyncio
async def test_admin_sees_admin_panel_button(
    admin_dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await start(admin_dispatcher, bot, user_id=ADMIN_ID)

    buttons = menu_buttons(fake_session)
    assert buttons[-1] == "⚙️ Админ-панель"
    keyboard = sent_messages(fake_session)[-1].reply_markup
    assert keyboard is not None
    data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert data[-1] == admin_cb.AdminPanelCB().pack()


@pytest.mark.asyncio
async def test_regular_user_menu_has_no_admin_button(
    admin_dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await start(admin_dispatcher, bot, user_id=OTHER_ID)

    assert menu_buttons(fake_session) == [
        "✂️ Записаться",
        "💈 Услуги и цены",
        "📅 Мои записи",
    ]


@pytest.mark.asyncio
async def test_admin_opens_panel(
    admin_dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await press(admin_dispatcher, bot, admin_cb.AdminPanelCB().pack(), user_id=ADMIN_ID)

    edited = edited_messages(fake_session)
    assert len(edited) == 1
    assert edited[0].text == admin_texts.PANEL_TEXT
    keyboard = edited[0].reply_markup
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert labels[:3] == ["💈 Услуги", "👤 Барберы", "📅 Записи клиентов"]


@pytest.mark.asyncio
async def test_regular_user_cannot_open_panel(
    strict_dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await press(
        strict_dispatcher, bot, admin_cb.AdminPanelCB().pack(), user_id=OTHER_ID
    )

    assert alert_text(fake_session) == admin_texts.ACCESS_DENIED
    assert callback_answers(fake_session)[-1].show_alert is True
    assert edited_messages(fake_session) == []


FORGED_CALLBACKS = [
    admin_cb.AdminPanelCB().pack(),
    admin_cb.AdminServicesCB(page=0).pack(),
    admin_cb.AdminServiceCB(service_id=1).pack(),
    admin_cb.AdminServiceToggleCB(service_id=1).pack(),
    admin_cb.AdminServiceEditCB(service_id=1, field="price").pack(),
    admin_cb.AdminServiceAddCB().pack(),
    admin_cb.AdminBarbersCB(page=0).pack(),
    admin_cb.AdminBarberCB(barber_id=1).pack(),
    admin_cb.AdminBarberToggleCB(barber_id=1).pack(),
    admin_cb.AdminBarberAddCB().pack(),
    admin_cb.AdminScheduleCB(barber_id=1).pack(),
    admin_cb.AdminWeekdayCB(barber_id=1, weekday=0).pack(),
    admin_cb.AdminTimeOffCB(barber_id=1).pack(),
    admin_cb.AdminTimeOffCB(barber_id=1, page=1).pack(),
    admin_cb.AdminTimeOffAddCB(barber_id=1).pack(),
    admin_cb.AdminTimeOffRemoveCB(barber_id=1, time_off_id=1).pack(),
    admin_cb.AdminTimeOffRemoveCB(barber_id=1, time_off_id=1, page=1).pack(),
    admin_cb.AdminBookingsCB(page=0).pack(),
    admin_cb.AdminBookingCB(booking_id=1).pack(),
    admin_cb.AdminBookingCancelCB(booking_id=1).pack(),
    admin_cb.AdminBookingCancelConfirmCB(booking_id=1).pack(),
    admin_cb.AdminFilterDateCB().pack(),
    admin_cb.AdminFilterBarberCB().pack(),
    admin_cb.AdminFilterBarberSetCB(barber_id=1).pack(),
    admin_cb.AdminFilterResetCB().pack(),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("packed", FORGED_CALLBACKS, ids=FORGED_CALLBACKS)
async def test_forged_admin_callback_is_denied(
    strict_dispatcher: Dispatcher,
    bot: Bot,
    fake_session: FakeSession,
    packed: str,
) -> None:
    await press(strict_dispatcher, bot, packed, user_id=OTHER_ID)

    assert alert_text(fake_session) == admin_texts.ACCESS_DENIED
    assert edited_messages(fake_session) == []
    assert sent_messages(fake_session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "packed",
    [
        "adm_panel:1:2",
        "adm_services",
        "adm_service:x",
        "adm_service_edit:1:size",
        # Старый формат без страницы: у пагинируемого раздела полей больше.
        "adm_timeoff:1",
        "adm_timeoff_remove:1:1",
    ],
    ids=[
        "extra-field",
        "missing-field",
        "bad-type",
        "bad-field",
        "timeoff",
        "timeoff-remove",
    ],
)
async def test_malformed_admin_callback_goes_to_fallback(
    strict_dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession, packed: str
) -> None:
    await press(strict_dispatcher, bot, packed, user_id=ADMIN_ID)

    assert alert_text(fake_session) == STALE_CALLBACK


@pytest.mark.asyncio
async def test_invalid_weekday_in_callback_is_rejected_safely(
    strict_dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await press(strict_dispatcher, bot, "adm_weekday:1:9", user_id=ADMIN_ID)

    assert alert_text(fake_session) == admin_texts.NOT_FOUND


@pytest.mark.asyncio
async def test_empty_admin_list_denies_admin_callback(
    dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    # dispatcher собран без AdminService: администраторов нет (fail closed).
    await press(dispatcher, bot, admin_cb.AdminPanelCB().pack(), user_id=ADMIN_ID)

    assert alert_text(fake_session) == admin_texts.ACCESS_DENIED
    assert edited_messages(fake_session) == []


@pytest.mark.asyncio
async def test_admin_callback_from_group_is_rejected(
    strict_dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await press(
        strict_dispatcher,
        bot,
        admin_cb.AdminPanelCB().pack(),
        user_id=ADMIN_ID,
        chat_type="group",
    )

    assert alert_text(fake_session) == PRIVATE_CHAT_ONLY
    assert edited_messages(fake_session) == []


@pytest.mark.asyncio
async def test_admin_start_in_group_is_ignored(
    strict_dispatcher: Dispatcher, bot: Bot, fake_session: FakeSession
) -> None:
    await start(strict_dispatcher, bot, user_id=ADMIN_ID, chat_type="supergroup")

    assert fake_session.requests == []


@pytest.mark.asyncio
async def test_middleware_denies_event_without_user(
    bot: Bot, fake_session: FakeSession
) -> None:
    middleware = AdminOnlyMiddleware(frozenset({ADMIN_ID}))
    called = False

    async def handler(event: object, data: dict[str, object]) -> None:
        nonlocal called
        called = True

    message = Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": ADMIN_ID, "type": "private"},
            "text": "без отправителя",
        },
        context={"bot": bot},
    )

    result = await middleware(handler, message, {})

    assert result is None
    assert called is False
    assert [sent.text for sent in sent_messages(fake_session)] == [
        admin_texts.ACCESS_DENIED
    ]


@pytest.mark.asyncio
async def test_middleware_passes_admin_through(bot: Bot) -> None:
    middleware = AdminOnlyMiddleware(frozenset({ADMIN_ID}))
    seen: list[int] = []

    async def handler(event: object, data: dict[str, object]) -> str:
        assert isinstance(event, Message)
        assert event.from_user is not None
        seen.append(event.from_user.id)
        return "ok"

    message = Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": ADMIN_ID, "type": "private"},
            "from": {"id": ADMIN_ID, "is_bot": False, "first_name": "Админ"},
            "text": "действие",
        },
        context={"bot": bot},
    )

    result = await middleware(handler, message, {})

    assert result == "ok"
    assert seen == [ADMIN_ID]


@pytest.mark.asyncio
async def test_admin_service_is_built_with_configured_ids() -> None:
    service = AdminService(
        object(),  # type: ignore[arg-type]
        admin_ids=frozenset({ADMIN_ID}),
    )

    assert service.admin_ids == frozenset({ADMIN_ID})
    assert service.is_admin(ADMIN_ID) is True
    assert service.is_admin(OTHER_ID) is False
