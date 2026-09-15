from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.provider_ops import classify_http
from app.services.provider_resolve import resolve_channel


@dataclass(frozen=True)
class EnrichmentHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str


@dataclass(frozen=True)
class EnrichmentResult:
    ok: bool
    provider: str
    is_mock: bool
    email: str = ""
    verified: bool = False
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company_name: str = ""
    linkedin_url: str = ""
    reason: str = ""
    failure_class: str = ""


class ContactEnrichmentProvider(Protocol):
    def health(self) -> EnrichmentHealth: ...

    def find_email(self, *, first_name: str, last_name: str, domain: str, company_name: str = "") -> EnrichmentResult: ...

    def verify_email(self, *, email: str) -> EnrichmentResult: ...


class MockEnrichmentProvider:
    def health(self) -> EnrichmentHealth:
        return EnrichmentHealth(provider="mock-enrichment", is_mock=True, connected=False, reason="Enrichment is mock. No email is invented.")

    def find_email(self, *, first_name: str, last_name: str, domain: str, company_name: str = "") -> EnrichmentResult:
        _ = (first_name, last_name, domain, company_name)
        return EnrichmentResult(ok=False, provider="mock-enrichment", is_mock=True, reason="Labeled mock does not invent emails.", failure_class="CONFIGURATION")

    def verify_email(self, *, email: str) -> EnrichmentResult:
        return EnrichmentResult(ok=False, provider="mock-enrichment", is_mock=True, email=email, reason="Labeled mock does not verify emails.")


class NotConfiguredEnrichmentProvider:
    def health(self) -> EnrichmentHealth:
        return EnrichmentHealth(provider="enrichment", is_mock=False, connected=False, reason="Enrichment is live but credentials are missing.")

    def find_email(self, *, first_name: str, last_name: str, domain: str, company_name: str = "") -> EnrichmentResult:
        _ = (first_name, last_name, domain, company_name)
        return EnrichmentResult(ok=False, provider="enrichment", is_mock=False, reason="Enrichment is not configured.", failure_class="CONFIGURATION")

    def verify_email(self, *, email: str) -> EnrichmentResult:
        return EnrichmentResult(ok=False, provider="enrichment", is_mock=False, email=email, reason="Enrichment is not configured.")


class HttpEnrichmentProvider:
    def __init__(self, *, api_key: str, base_url: str = "", client: httpx.Client | None = None) -> None:
        self._key = api_key
        self._base = (base_url or "https://api.hunter.io/v2").rstrip("/")
        self._client = client

    def health(self) -> EnrichmentHealth:
        return EnrichmentHealth(provider="enrichment", is_mock=False, connected=True, reason="Enrichment credentials are set.")

    def find_email(self, *, first_name: str, last_name: str, domain: str, company_name: str = "") -> EnrichmentResult:
        _ = company_name
        owns = self._client is None
        client = self._client or httpx.Client(timeout=20.0)
        try:
            response = client.get(
                f"{self._base}/email-finder",
                params={"api_key": self._key, "first_name": first_name, "last_name": last_name, "domain": domain},
            )
            if response.status_code >= 400:
                return EnrichmentResult(
                    ok=False,
                    provider="enrichment",
                    is_mock=False,
                    reason=f"Finder refused ({response.status_code}).",
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            payload = data.get("data") if isinstance(data, dict) else {}
            if not isinstance(payload, dict):
                payload = {}
            email = str(payload.get("email") or "")
            return EnrichmentResult(
                ok=bool(email),
                provider="enrichment",
                is_mock=False,
                email=email,
                first_name=first_name,
                last_name=last_name,
                title=str(payload.get("position") or ""),
                company_name=str(payload.get("company") or company_name),
                reason="" if email else "Finder returned no email.",
            )
        except httpx.HTTPError:
            return EnrichmentResult(ok=False, provider="enrichment", is_mock=False, reason="Enrichment network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def verify_email(self, *, email: str) -> EnrichmentResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=20.0)
        try:
            response = client.get(f"{self._base}/email-verifier", params={"api_key": self._key, "email": email})
            if response.status_code >= 400:
                return EnrichmentResult(ok=False, provider="enrichment", is_mock=False, email=email, reason="Verifier refused.", failure_class=classify_http(response.status_code))
            data = response.json() if response.content else {}
            payload = data.get("data") if isinstance(data, dict) else {}
            if not isinstance(payload, dict):
                payload = {}
            status = str(payload.get("status") or "").lower()
            verified = status in {"valid", "deliverable"}
            return EnrichmentResult(ok=True, provider="enrichment", is_mock=False, email=email, verified=verified, reason=status)
        except httpx.HTTPError:
            return EnrichmentResult(ok=False, provider="enrichment", is_mock=False, email=email, reason="Enrichment network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()


def get_enrichment_provider(db: Session | None = None, tenant_id: UUID | None = None) -> ContactEnrichmentProvider:
    settings = get_settings()
    if db is not None and tenant_id is not None:
        resolved = resolve_channel(db, tenant_id, "enrichment")
        if resolved.mode == "LIVE" and resolved.secrets.get("access_token"):
            return HttpEnrichmentProvider(
                api_key=resolved.secrets["access_token"],
                base_url=resolved.secrets.get("base_url") or settings.enrichment_api_base,
            )
        if resolved.mode == "MOCK":
            return MockEnrichmentProvider()
        return NotConfiguredEnrichmentProvider()
    mode = (settings.enrichment_provider or "mock").strip().lower()
    if mode in {"live", "hunter", "enrichment"}:
        if settings.enrichment_configured:
            return HttpEnrichmentProvider(api_key=settings.enrichment_api_key, base_url=settings.enrichment_api_base)
        return NotConfiguredEnrichmentProvider()
    return MockEnrichmentProvider()
