"""Тесты конфигурации администраторов: ``ADMIN_TELEGRAM_IDS``."""

from __future__ import annotations

import pytest

from barberbot.config import (
    ConfigurationError,
    Settings,
    load_settings,
    parse_admin_telegram_ids,
)

TEST_TOKEN = "123456789:AAHtest-token-value-for-unit-tests-only"
ADMIN_ID = 123456789

_ENV_NAMES = (
    "BOT_TOKEN",
    "ADMIN_TELEGRAM_IDS",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолировать тесты от переменных окружения и от реального .env."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("123456789", frozenset({123456789})),
        ("1,2,3", frozenset({1, 2, 3})),
        (" 1 , 2 ,3 ", frozenset({1, 2, 3})),
        ("7,7,7", frozenset({7})),
        ("", frozenset()),
        ("   ", frozenset()),
    ],
    ids=["single", "many", "spaces", "duplicates", "empty", "blank"],
)
def test_valid_admin_ids_are_parsed(raw: str, expected: frozenset[int]) -> None:
    assert parse_admin_telegram_ids(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "0",
        "-5",
        "abc",
        "1,two",
        "1,,2",
        "1,",
        ",1",
        "1.5",
        "١٢٣",
        "12345678901234567890",
        "[123,456]",
    ],
    ids=[
        "zero",
        "negative",
        "text",
        "mixed",
        "empty-item",
        "trailing-comma",
        "leading-comma",
        "float",
        "unicode-digits",
        "too-large",
        "json-list",
    ],
)
def test_invalid_admin_ids_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_admin_telegram_ids(raw)


def test_boolean_and_float_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        parse_admin_telegram_ids([True])
    with pytest.raises(ValueError):
        parse_admin_telegram_ids([1.5])


def test_settings_without_admin_ids_have_no_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)

    settings = load_settings(env_file=None)

    assert settings.admin_telegram_ids == frozenset()
    assert settings.admin_telegram_ids == frozenset()


def test_multiple_admin_ids_are_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "100000001, 100000002")

    settings = load_settings(env_file=None)

    assert settings.admin_telegram_ids == frozenset({100000001, 100000002})


def test_single_admin_id_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", str(ADMIN_ID))

    settings = Settings(_env_file=None)

    assert settings.admin_telegram_ids == frozenset({ADMIN_ID})


@pytest.mark.parametrize(
    "raw",
    ["not-a-list", "1,,2", "0", "-3", "1,"],
    ids=["text", "empty-item", "zero", "negative", "trailing-comma"],
)
def test_invalid_admin_ids_raise_configuration_error(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", raw)

    with pytest.raises(ConfigurationError) as error:
        load_settings(env_file=None)

    message = str(error.value)
    assert "ADMIN_TELEGRAM_IDS" in message
    assert raw not in message
    assert "input_value" not in message


def test_admin_ids_are_not_secrets_and_do_not_hide_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", str(ADMIN_ID))

    settings = Settings(_env_file=None)

    assert TEST_TOKEN not in repr(settings)
    assert settings.model_dump()["admin_telegram_ids"] == frozenset({ADMIN_ID})
