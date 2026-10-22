"""Tests for the Day 1 application bootstrap and health endpoints."""

import importlib

import pytest
from pydantic import ValidationError

from app.config import get_settings


def test_health_returns_exact_status(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_service_metadata(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"service": "PatchPilot", "version": "0.1.0"}


def test_app_import_does_not_require_env_file(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    module = importlib.import_module("app.main")

    assert module.app.title == "PatchPilot"


def test_invalid_numeric_setting_fails_when_requested(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValidationError, match="greater than 0"):
        get_settings()

    get_settings.cache_clear()
