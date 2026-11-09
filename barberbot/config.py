"""Конфигурация приложения.

Значения читаются из переменных окружения и из файла ``.env`` в корне проекта.
Секреты хранятся в ``SecretStr`` и никогда не выводятся целиком.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from aiogram.utils.token import TokenValidationError, validate_token
from pydantic import BeforeValidator, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

#: Верхняя граница ``BIGINT`` PostgreSQL для Telegram ID.
MAX_TELEGRAM_ID = 2**63 - 1


class _AdminIdError(ValueError):
    """Некорректный формат списка администраторов (значение не выводится)."""


def parse_admin_telegram_ids(value: Any) -> frozenset[int]:
    """Разобрать ``ADMIN_TELEGRAM_IDS``: положительные ID через запятую.

    Пустая строка или отсутствие значения означают, что администраторов нет
    (**fail closed**). Любой некорректный элемент отклоняет всю конфигурацию:
    частично угаданный список администраторов недопустим. Текст ошибки не
    содержит исходное значение.
    """
    if value is None:
        return frozenset()
    if isinstance(value, frozenset | set | list | tuple):
        items: list[Any] = list(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return frozenset()
        items = raw.split(",")
    else:
        raise _AdminIdError("ADMIN_TELEGRAM_IDS должен быть списком ID через запятую")

    telegram_ids: set[int] = set()
    for item in items:
        if isinstance(item, str):
            text = item.strip()

            if not text or not text.isascii() or not text.isdigit():
                raise _AdminIdError(
                    "ADMIN_TELEGRAM_IDS: ожидаются целые положительные ID через запятую"
                )
            number = int(text)
        elif isinstance(item, int) and not isinstance(item, bool):
            number = item
        else:
            raise _AdminIdError("ADMIN_TELEGRAM_IDS: ожидаются целые положительные ID")

        if number <= 0 or number > MAX_TELEGRAM_ID:
            raise _AdminIdError(
                "ADMIN_TELEGRAM_IDS: ID должен быть положительным числом"
            )
        telegram_ids.add(number)
    return frozenset(telegram_ids)


#: Тип поля: строка из ``.env`` не декодируется как JSON, а разбирается выше.
AdminTelegramIds = Annotated[
    frozenset[int], NoDecode, BeforeValidator(parse_admin_telegram_ids)
]


class ConfigurationError(RuntimeError):
    """Конфигурация отсутствует или некорректна.

    Сообщение ошибки содержит только имена переменных: значения секретов
    в него не попадают.
    """


class Settings(BaseSettings):
    """Настройки приложения.

    ``extra="ignore"`` обязателен: в ``.env`` уже присутствуют ``POSTGRES_*``,
    а на этом этапе бот не работает с базой данных.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    bot_token: SecretStr = Field(description="Токен Telegram-бота из BotFather")
    admin_telegram_ids: AdminTelegramIds = Field(
        default_factory=frozenset,
        description="Telegram ID администраторов через запятую",
    )

    @field_validator("bot_token")
    @classmethod
    def _validate_bot_token(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value().strip()
        if not token:
            raise ValueError("BOT_TOKEN не задан или пуст")
        try:
            validate_token(token)
        except TokenValidationError:
            raise ValueError(
                "BOT_TOKEN имеет неверный формат, ожидается <id>:<ключ>"
            ) from None
        return SecretStr(token)


def _describe_error(error: ValidationError) -> str:
    """Собрать безопасное описание ошибки: только имена переменных."""
    fields = sorted(
        {
            str(location[0]).upper()
            for details in error.errors(include_input=False, include_url=False)
            if (location := details.get("loc"))
        }
    )
    reason = ", ".join(fields) if fields else "переменные окружения"
    return (
        f"Некорректная конфигурация: {reason}. "
        "Проверьте .env: BOT_TOKEN обязателен, не должен быть пустым "
        "и должен иметь вид <id>:<ключ>; ADMIN_TELEGRAM_IDS — необязательный "
        "список положительных Telegram ID через запятую."
    )


def load_settings(env_file: str | Path | None = ENV_FILE) -> Settings:
    """Загрузить настройки, превратив ошибки валидации в ``ConfigurationError``.

    Исходный ``ValidationError`` намеренно не связывается как причина
    (``from None``), чтобы значения переменных не попадали в traceback.
    """
    try:
        # pydantic-settings добавляет аргумент _env_file динамически;
        # его сигнатуру mypy понимает только с mypy-плагином pydantic.
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as error:
        raise ConfigurationError(_describe_error(error)) from None
