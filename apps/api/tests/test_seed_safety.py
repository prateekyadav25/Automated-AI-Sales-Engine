import pytest

from app.core.config import get_settings
from app.seed import seed


def test_seed_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SEED_DEMO", "true")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="forbidden in production"):
        seed()
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()


def test_seed_refuses_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SEED_DEMO", "false")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="SEED_DEMO is disabled"):
        seed()
    monkeypatch.setenv("SEED_DEMO", "true")
    get_settings.cache_clear()
