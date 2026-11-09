"""Конфигурация приложения.

Значения читаются из переменных окружения и из файла ``.env`` в корне проекта.
Секреты хранятся в ``SecretStr`` и никогда не выводятся целиком.
"""

from __future__ import annotations

from pathlib import Path

from aiogram.utils.token import TokenValidationError, validate_token
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


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
        "и должен иметь вид <id>:<ключ>."
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
