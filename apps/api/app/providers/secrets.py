"""Secret lookup. Development uses the environment. Production must not commit secrets."""

from __future__ import annotations

import os
from typing import Protocol

from app.core.config import get_settings

SECRET_CLASSES = {
    "DATABASE_URL": "database",
    "DATABASE_ADMIN_URL": "database",
    "SECRET_KEY": "jwt",
    "TOKEN_ENCRYPTION_KEY": "encryption",
    "GOOGLE_CLIENT_SECRET": "oauth",
    "INTEGRATIONS_WEBHOOK_SECRET": "oauth",
    "APIFY_API_TOKEN": "provider",
    "APIFY_TOKEN": "provider",
    "LINKEDIN_ACCESS_TOKEN": "provider",
    "META_ACCESS_TOKEN": "provider",
    "TWILIO_AUTH_TOKEN": "provider",
    "VAPI_API_KEY": "provider",
    "VAPI_WEBHOOK_SECRET": "provider",
    "OPENAI_API_KEY": "provider",
    "S3_SECRET_KEY": "storage",
    "METRICS_TOKEN": "ops",
}


class SecretProvider(Protocol):
    def get(self, name: str) -> str | None: ...


class EnvironmentSecretProvider:
    def get(self, name: str) -> str | None:
        value = os.environ.get(name)
        if value:
            return value
        settings = get_settings()
        attr = name.lower()
        raw = getattr(settings, attr, None)
        if raw is None or raw == "":
            return None
        return str(raw)


def get_secret_provider() -> SecretProvider:
    return EnvironmentSecretProvider()
