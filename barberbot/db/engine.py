"""Асинхронный движок и фабрика сессий SQLAlchemy поверх Psycopg 3.

Один ``AsyncEngine`` создаётся на процесс и переиспользуется: движок владеет
пулом соединений. Параметры подключения берутся из существующей конфигурации
``barberbot.db_settings`` — учётные данные не дублируются в коде.

На Windows 10 psycopg async требует ``SelectorEventLoop``; это настраивается
в точке входа приложения и в тестовых фикстурах.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from barberbot.db_settings import database_url, get_settings


@dataclass(frozen=True, slots=True)
class Database:
    """Пара «движок + фабрика сессий» для одной целевой базы."""

    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    async def dispose(self) -> None:
        """Закрыть пул соединений."""
        await self.engine.dispose()


def create_database(*, target: Literal["main", "test"] | None = None) -> Database:
    """Создать движок для основной или тестовой базы.

    ``target="test"`` использовать в тестах; ``None`` — значение по умолчанию
    из ``BARBERBOT_DB_TARGET`` (для приложения — основная база).
    """
    url = database_url(get_settings(), target=target)
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
    )
    # expire_on_commit=False: загруженные атрибуты остаются доступны после
    # commit, без неявного ввода-вывода в async-коде.
    return Database(
        engine=engine, sessions=async_sessionmaker(engine, expire_on_commit=False)
    )


__all__ = ["Database", "create_database"]
