import logging

import pytest
from fastapi.testclient import TestClient

from servicekit import ServiceSettings, configure_logging
from servicekit.http import create_app


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = ServiceSettings()
    assert settings.port == 9001
    assert settings.log_level == "DEBUG"


def test_health_endpoint() -> None:
    app = create_app(ServiceSettings(service_name="demo"), version="1.2.3")
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "demo",
        "version": "1.2.3",
        "environment": "local",
    }


def test_configure_logging_sets_level() -> None:
    configure_logging("demo", "WARNING")
    assert logging.getLogger().level == logging.WARNING
