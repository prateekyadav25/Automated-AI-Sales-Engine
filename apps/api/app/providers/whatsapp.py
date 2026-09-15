from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings


@dataclass
class WhatsAppSendResult:
    ok: bool
    provider: str
    is_mock: bool
    external_id: str = ""
    status: str = "NOT_CONFIGURED"
    error: str = ""


class WhatsAppProvider(Protocol):
    provider_key: str

    def send_template(self, *, to: str, template_id: str, language: str, variables: dict) -> WhatsAppSendResult: ...


class NotConfiguredWhatsAppProvider:
    provider_key = "whatsapp"

    def send_template(self, *, to: str, template_id: str, language: str, variables: dict) -> WhatsAppSendResult:
        _ = to, template_id, language, variables
        return WhatsAppSendResult(
            ok=False,
            provider="whatsapp",
            is_mock=False,
            status="NOT_CONFIGURED",
            error="WhatsApp credentials are not configured",
        )


class MockWhatsAppProvider:
    provider_key = "mock-whatsapp"

    def send_template(self, *, to: str, template_id: str, language: str, variables: dict) -> WhatsAppSendResult:
        _ = language, variables
        return WhatsAppSendResult(
            ok=True,
            provider="mock-whatsapp",
            is_mock=True,
            external_id=f"mock-wa:{to}:{template_id}",
            status="MOCK",
        )


def get_whatsapp_provider() -> WhatsAppProvider:
    settings = get_settings()
    if (getattr(settings, "whatsapp_provider", "") or "").lower() == "mock":
        return MockWhatsAppProvider()
    return NotConfiguredWhatsAppProvider()
