"""Тесты точки входа: коды возврата при сбоях без вывода секретов."""

from __future__ import annotations

import logging

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMe

from barberbot import __main__ as entrypoint
from barberbot.config import ConfigurationError

CONFIG_MESSAGE = "Некорректная конфигурация: BOT_TOKEN."


@pytest.fixture(autouse=True)
def _silence_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entrypoint, "setup_logging", lambda: None)


def test_main_returns_error_code_when_config_is_invalid(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _fail(env_file: object = None) -> None:
        raise ConfigurationError(CONFIG_MESSAGE)

    monkeypatch.setattr(entrypoint, "load_settings", _fail)

    with caplog.at_level(logging.ERROR, logger="barberbot.__main__"):
        exit_code = entrypoint.main()

    assert exit_code == 1
    assert "BOT_TOKEN" in caplog.text


def test_main_returns_error_code_when_telegram_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _fail(settings: object) -> None:
        raise TelegramNetworkError(method=GetMe(), message="network is down")

    monkeypatch.setattr(entrypoint, "load_settings", lambda: object())
    monkeypatch.setattr(entrypoint, "run_bot", _fail)

    with caplog.at_level(logging.ERROR, logger="barberbot.__main__"):
        exit_code = entrypoint.main()

    assert exit_code == 1
    assert "Telegram API" in caplog.text
