"""Доменные ошибки административной панели.

Сообщения предназначены администратору: понятный русский текст без SQL,
имён таблиц, DSN и прочих внутренних подробностей.
"""

from __future__ import annotations


class AdminError(Exception):
    """Базовая ошибка административных операций."""


class AdminAccessDenied(AdminError):
    """Пользователь не входит в список администраторов."""


class AdminValidationError(AdminError):
    """Некорректные входные данные административной операции."""


class AdminNotFound(AdminError):
    """Объект не найден (удалён или изменён параллельно)."""


class AdminConflict(AdminError):
    """Изменение конфликтует с существующими будущими записями."""


class AdminBookingState(AdminError):
    """Запись находится в состоянии, запрещающем действие."""


class AdminDatabaseUnavailable(AdminError):
    """Временная ошибка базы данных; подробности не раскрываются."""


__all__ = [
    "AdminAccessDenied",
    "AdminBookingState",
    "AdminConflict",
    "AdminDatabaseUnavailable",
    "AdminError",
    "AdminNotFound",
    "AdminValidationError",
]
