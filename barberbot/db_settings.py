"""PostgreSQL connection settings for Alembic and the seed utilities.

This module intentionally contains no ORM models and does not require BOT_TOKEN.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_VARIABLE = "BARBERBOT_DB_TARGET"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    postgres_host: str = Field(min_length=1)
    postgres_port: int = Field(ge=1, le=65535)
    postgres_db: str = Field(min_length=1, max_length=58)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr

    @field_validator("postgres_db")
    @classmethod
    def validate_database_name(cls, value: str) -> str:
        # Enables deriving a safe, deterministic '_test' database name.
        if not value.isascii() or not value.replace("_", "a").isalnum():
            raise ValueError("POSTGRES_DB must contain only ASCII letters, digits or _")
        if not (value[0].isalpha() or value[0] == "_"):
            raise ValueError("POSTGRES_DB must start with a letter or _")
        return value


def get_settings() -> DatabaseSettings:
    try:
        return DatabaseSettings()  # type: ignore[call-arg]
    except ValidationError:
        # Never display database password or the raw Pydantic ValidationError.
        raise RuntimeError(
            "Invalid PostgreSQL configuration; check POSTGRES_* in .env"
        ) from None


def database_names(settings: DatabaseSettings) -> tuple[str, str]:
    main_name = settings.postgres_db
    test_name = main_name + "_test"
    if main_name == test_name or len(test_name) > 63:
        raise RuntimeError("Invalid test database name")
    return main_name, test_name


def selected_target() -> Literal["main", "test"]:
    value = os.environ.get(TARGET_VARIABLE, "main")

    if value == "main":
        return "main"

    if value == "test":
        return "test"

    raise RuntimeError(f"{TARGET_VARIABLE} must be exactly 'main' or 'test'")


def database_url(
    settings: DatabaseSettings,
    *,
    target: Literal["main", "test"] | None = None,
    database: str | None = None,
) -> URL:
    if database is not None and target is not None:
        raise ValueError("Provide database or target, not both")
    main_name, test_name = database_names(settings)
    if database is None:
        selected = target if target is not None else selected_target()
        database = test_name if selected == "test" else main_name
    return URL.create(
        "postgresql+psycopg",
        username=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=database,
    )
