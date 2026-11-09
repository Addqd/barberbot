"""Общие фикстуры тестов: бот без сети, dispatcher и фейковая сессия Telegram."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator, Iterable
from datetime import UTC, datetime, time, timedelta
from secrets import randbelow
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import Chat, Message, Update
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from barberbot.app import build_dispatcher
from barberbot.booking.service import BookingService
from barberbot.booking.slots import MOSCOW
from barberbot.db import Database, create_database
from barberbot.db.models import (
    Barber,
    BarberTimeOff,
    BarberWorkingHours,
    Booking,
    BookingStatus,
    Service,
    User,
)
from barberbot.db_settings import database_names, get_settings

from .fakes import FakeBookingService

TEST_BOT_TOKEN = "123456789:TEST-token-value-for-unit-tests-only"
TEST_CHAT_ID = 42
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

#: Фиксированное «сейчас» интеграционных тестов: понедельник, 08:00 по Москве.
FIXED_NOW = datetime(2030, 1, 7, 8, 0, tzinfo=MOSCOW)

#: Фиксированный понедельник для тестов слотов.
FIXED_MONDAY = FIXED_NOW.date()


def pytest_asyncio_loop_factories(config, item):
    """Use Psycopg-compatible event loops in pytest-asyncio 1.4+."""
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


class FakeSession(BaseSession):
    """Сессия Bot API, которая записывает запросы вместо сети."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.closed = False
        self._last_message_id = 100

    async def close(self) -> None:
        self.closed = True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:
        yield b""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, SendMessage):
            self._last_message_id += 1
            return Message(
                message_id=self._last_message_id,
                date=datetime.now(UTC),
                chat=Chat(id=TEST_CHAT_ID, type="private"),
                text=method.text,
            )
        if isinstance(method, EditMessageText):
            chat_id = (
                method.chat_id if isinstance(method.chat_id, int) else TEST_CHAT_ID
            )
            return Message(
                message_id=method.message_id or self._last_message_id,
                date=datetime.now(UTC),
                chat=Chat(id=chat_id, type="private"),
                text=method.text,
                reply_markup=method.reply_markup,
            )
        raise AssertionError(f"Неожиданный запрос к Bot API: {type(method).__name__}")


def build_update(bot: Bot, payload: dict[str, Any]) -> Update:
    """Собрать Update так же, как это делает aiogram при получении из Telegram.

    Контекст ``bot`` обязателен: без него ``message.answer`` и ``callback.answer``
    не смогут отправить запрос.
    """
    return Update.model_validate(payload, context={"bot": bot})


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def bot(fake_session: FakeSession) -> Bot:
    return Bot(token=TEST_BOT_TOKEN, session=fake_session)


@pytest.fixture
def dispatcher(booking_service_stub: FakeBookingService) -> Dispatcher:
    return build_dispatcher(booking_service_stub)  # type: ignore[arg-type]


@pytest.fixture
def booking_service_stub() -> FakeBookingService:
    return FakeBookingService()


def message_payload(
    text: str,
    *,
    user_id: int = TEST_CHAT_ID,
    message_id: int = 1,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "date": NOW,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Тест"},
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(text)}],
    }


def callback_payload(
    data: str,
    *,
    user_id: int = TEST_CHAT_ID,
    message_id: int = 2,
) -> dict[str, Any]:
    return {
        "id": "callback-1",
        "from": {"id": user_id, "is_bot": False, "first_name": "Тест"},
        "chat_instance": "chat-instance",
        "data": data,
        "message": message_payload(
            "Сообщение бота", user_id=user_id, message_id=message_id
        ),
    }


def callback_answers(session: FakeSession) -> list[AnswerCallbackQuery]:
    return [
        request
        for request in session.requests
        if isinstance(request, AnswerCallbackQuery)
    ]


def sent_messages(session: FakeSession) -> list[SendMessage]:
    return [request for request in session.requests if isinstance(request, SendMessage)]


def edited_messages(session: FakeSession) -> list[EditMessageText]:
    return [
        request for request in session.requests if isinstance(request, EditMessageText)
    ]


def last_text(session: FakeSession) -> str:
    """Текст последнего показанного пользователю сообщения."""
    for request in reversed(session.requests):
        if isinstance(request, EditMessageText):
            return request.text
        if isinstance(request, SendMessage):
            return request.text
    raise AssertionError("Бот не отправил ни одного сообщения")


# --------------------------------------------------------------------------- #
# Интеграционные фикстуры: реальная PostgreSQL, только база *_test
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def database() -> AsyncGenerator[Database]:
    """Асинхронный движок к тестовой БД с проверкой фактического имени базы."""
    settings = get_settings()
    expected = database_names(settings)[1]
    target = create_database(target="test")
    if target.engine.url.database != expected:
        await target.dispose()
        pytest.fail("Тестовый движок настроен не на ту базу данных")
    try:
        async with target.engine.connect() as connection:
            actual = (
                await connection.execute(text("SELECT current_database()"))
            ).scalar_one()
        if actual != expected or not actual.endswith("_test"):
            pytest.fail(f"Отказ выполнять тесты на базе {actual!r}")
        yield target
    finally:
        await target.dispose()


@pytest_asyncio.fixture
async def sessions(
    database: Database,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    yield database.sessions


class DataFactory:
    """Создаёт уникальные тестовые строки и удаляет только их."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._telegram_ids: list[int] = []
        self._barbers: list[int] = []
        self._services: list[int] = []
        self._sequence = 0

    def unique(self, prefix: str) -> str:
        self._sequence += 1
        return f"__test_{prefix}_{uuid4().hex[:10]}_{self._sequence}"

    def telegram_id(self) -> int:
        """Уникальный Telegram ID, отслеживаемый для очистки."""
        telegram_id = -(10**15 + randbelow(10**12))
        self._telegram_ids.append(telegram_id)
        return telegram_id

    async def user(
        self, *, telegram_id: int | None = None, display_name: str | None = None
    ) -> User:
        telegram_id = self.telegram_id() if telegram_id is None else telegram_id
        async with self._sessions() as session, session.begin():
            user = User(telegram_id=telegram_id, display_name=display_name)
            session.add(user)
            await session.flush()
        return user

    async def service(
        self,
        *,
        price: int = 500,
        duration: int = 60,
        is_active: bool = True,
    ) -> Service:
        async with self._sessions() as session, session.begin():
            service = Service(
                name=self.unique("service"),
                price_rub=price,
                duration_minutes=duration,
                is_active=is_active,
            )
            session.add(service)
            await session.flush()
        self._services.append(service.id)
        return service

    async def barber(
        self,
        *,
        is_active: bool = True,
        weekdays: Iterable[int] = range(5),
        start: time = time(9, 0),
        end: time = time(17, 0),
    ) -> Barber:
        async with self._sessions() as session, session.begin():
            barber = Barber(name=self.unique("barber"), is_active=is_active)
            session.add(barber)
            await session.flush()
            for weekday in weekdays:
                session.add(
                    BarberWorkingHours(
                        barber_id=barber.id,
                        weekday=weekday,
                        start_time=start,
                        end_time=end,
                    )
                )
        self._barbers.append(barber.id)
        return barber

    async def time_off(
        self,
        *,
        barber_id: int,
        starts_at: datetime,
        ends_at: datetime,
        reason: str | None = None,
    ) -> BarberTimeOff:
        async with self._sessions() as session, session.begin():
            row = BarberTimeOff(
                barber_id=barber_id,
                starts_at=starts_at,
                ends_at=ends_at,
                reason=reason,
            )
            session.add(row)
            await session.flush()
        return row

    async def booking(
        self,
        *,
        user_id: int,
        barber_id: int,
        service_id: int,
        starts_at: datetime,
        duration: int = 60,
        price: int = 500,
        status: BookingStatus = BookingStatus.CONFIRMED,
    ) -> Booking:
        async with self._sessions() as session, session.begin():
            booking = Booking(
                user_id=user_id,
                barber_id=barber_id,
                service_id=service_id,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=duration),
                price_rub_at_booking=price,
                duration_minutes_at_booking=duration,
                status=status,
            )
            session.add(booking)
            await session.flush()
        return booking

    async def cleanup(self) -> None:
        async with self._sessions() as session, session.begin():
            if self._telegram_ids:
                users_of_test = (
                    select(User.id)
                    .where(User.telegram_id.in_(self._telegram_ids))
                    .scalar_subquery()
                )
                await session.execute(
                    delete(Booking).where(Booking.user_id.in_(users_of_test))
                )
            if self._barbers:
                await session.execute(
                    delete(Booking).where(Booking.barber_id.in_(self._barbers))
                )
            if self._services:
                await session.execute(
                    delete(Booking).where(Booking.service_id.in_(self._services))
                )
            if self._barbers:
                await session.execute(
                    delete(Barber).where(Barber.id.in_(self._barbers))
                )
            if self._services:
                await session.execute(
                    delete(Service).where(Service.id.in_(self._services))
                )
            if self._telegram_ids:
                await session.execute(
                    delete(User).where(User.telegram_id.in_(self._telegram_ids))
                )


@pytest_asyncio.fixture
async def factory(
    sessions: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[DataFactory]:
    data = DataFactory(sessions)
    try:
        yield data
    finally:
        await data.cleanup()


@pytest_asyncio.fixture
async def booking_service(
    sessions: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[BookingService]:
    yield BookingService(sessions, clock=lambda: FIXED_NOW)


@pytest_asyncio.fixture
async def live_dispatcher(
    booking_service: BookingService,
) -> AsyncGenerator[Dispatcher]:
    """Dispatcher с настоящим BookingService (тестовая PostgreSQL)."""
    yield build_dispatcher(booking_service)
