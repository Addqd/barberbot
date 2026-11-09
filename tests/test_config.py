"""Тесты загрузки и валидации конфигурации."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from barberbot.config import ConfigurationError, Settings, load_settings

TEST_TOKEN = "123456789:AAHtest-token-value-for-unit-tests-only"
POSTGRES_ENV = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5433",
    "POSTGRES_DB": "barberbot",
    "POSTGRES_USER": "barberbot",
    "POSTGRES_PASSWORD": "test-password-value",
}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолировать тесты от переменных окружения и от реального .env."""
    for name in ("BOT_TOKEN", *POSTGRES_ENV):
        monkeypatch.delenv(name, raising=False)


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)

    settings = load_settings(env_file=None)

    assert settings.bot_token.get_secret_value() == TEST_TOKEN


def test_settings_are_loaded_from_dotenv_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # tmp_path не используется: базовый каталог pytest во временной папке Windows
    # недоступен на этой машине (PermissionError), поэтому каталог создаётся явно.
    with tempfile.TemporaryDirectory() as directory:
        env_file = Path(directory) / ".env"
        env_file.write_text(f"BOT_TOKEN={TEST_TOKEN}\n", encoding="utf-8")

        settings = load_settings(env_file=env_file)

    assert settings.bot_token.get_secret_value() == TEST_TOKEN


def test_missing_bot_token_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError) as error:
        load_settings(env_file=None)

    message = str(error.value)
    assert "BOT_TOKEN" in message
    assert "input_value" not in message


@pytest.mark.parametrize(
    "empty_token", ["", "   ", "\t\n"], ids=["empty", "spaces", "whitespace"]
)
def test_empty_bot_token_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch, empty_token: str
) -> None:
    monkeypatch.setenv("BOT_TOKEN", empty_token)

    with pytest.raises(ConfigurationError) as error:
        load_settings(env_file=None)

    message = str(error.value)
    assert "BOT_TOKEN" in message
    if empty_token:
        assert empty_token not in message


def test_invalid_token_format_does_not_leak_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_value = "super-secret-token-value"
    monkeypatch.setenv("BOT_TOKEN", secret_value)

    with pytest.raises(ConfigurationError) as error:
        load_settings(env_file=None)

    assert secret_value not in str(error.value)


def test_postgres_variables_do_not_break_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)
    for name, value in POSTGRES_ENV.items():
        monkeypatch.setenv(name, value)

    settings = load_settings(env_file=None)

    assert settings.bot_token.get_secret_value() == TEST_TOKEN
    assert set(settings.model_dump()) == {"bot_token"}


def test_settings_do_not_expose_token_in_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)

    settings = Settings(_env_file=None)

    assert TEST_TOKEN not in repr(settings)
    assert TEST_TOKEN not in str(settings)


def test_token_is_stripped() -> None:
    settings = Settings(_env_file=None, bot_token=f"  {TEST_TOKEN}  ")

    assert settings.bot_token.get_secret_value() == TEST_TOKEN
