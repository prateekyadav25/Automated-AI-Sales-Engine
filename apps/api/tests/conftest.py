import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("SEED_DEMO", "true")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_engine, reset_engine
from app.main import app
from app.seed import seed


@pytest.fixture(scope="session")
def client() -> TestClient:
    reset_engine()
    get_settings.cache_clear()
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    seed()
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str = "admin@agrayian.demo") -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "Agrarian!Demo1"})
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
