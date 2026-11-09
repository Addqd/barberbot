"""Базовый класс декларативных ORM-моделей.

Схема базы данных принадлежит Alembic; ``metadata`` используется только для
описания моделей и сравнения со схемой в тестах.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Общий ``MetaData`` всех ORM-моделей BarberBot."""
