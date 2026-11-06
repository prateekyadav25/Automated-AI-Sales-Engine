import os

_postgres_test = os.environ.get("POSTGRES_RLS_ADMIN_URL", "").strip()
if _postgres_test:
    os.environ["DATABASE_URL"] = _postgres_test
    os.environ["DATABASE_ADMIN_URL"] = _postgres_test
else:
    os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("SEED_DEMO", "true")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, reset_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    reset_engine()
    get_settings.cache_clear()
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    seed()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force labeled mock providers without changing the workspace .env."""
    settings = get_settings()
    monkeypatch.setattr(settings, "email_provider", "mock")
    monkeypatch.setattr(settings, "calendar_provider", "mock")


def login(client: TestClient, email: str = "admin@agrayian.demo") -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "Agrarian!Demo1"})
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
