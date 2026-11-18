import pytest

from app.config import load_settings


def test_production_rejects_weak_auth_secret(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_SECRET", "too-short")

    with pytest.raises(RuntimeError, match="strong AUTH_SECRET"):
        load_settings()
