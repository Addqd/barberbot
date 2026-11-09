"""Проверка Psycopg Async + SQLAlchemy на реальной тестовой PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from barberbot.db_settings import database_names, database_url, get_settings


@pytest.mark.asyncio
async def test_async_engine_can_open_connection() -> None:
    """Проверить подключение исключительно к *_test, без изменения данных."""
    settings = get_settings()
    expected_database = database_names(settings)[1]
    url = database_url(settings, target="test")
    assert url.database == expected_database

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT current_database()"))
            assert result.scalar_one() == expected_database
    finally:
        await engine.dispose()
