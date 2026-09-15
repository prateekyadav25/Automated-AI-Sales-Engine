from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.provider_ops import classify_http
from app.services.provider_resolve import resolve_channel


def normalize_actor_id(actor_id: str) -> str:
    return actor_id.strip().replace("/", "~")


def _text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                nested = first.get("email") or first.get("value") or first.get("address") or first.get("id")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return ""


@dataclass(frozen=True)
class DiscoveredLead:
    first_name: str
    last_name: str
    email: str
    title: str
    company_name: str
    linkedin_url: str
    raw_keys: tuple[str, ...] = field(default_factory=tuple)
    provider_ref: str = ""
    confidence: int = 0
    source_url: str = ""


@dataclass(frozen=True)
class DiscoveryQuery:
    industries: str = ""
    geographies: str = ""
    search_query: str = ""
    profile_urls: tuple[str, ...] = ()
    max_items: int = 10
    process_token: str = ""
    job_titles: tuple[str, ...] = ()
    seniorities: tuple[str, ...] = ()
    target_companies: tuple[str, ...] = ()
    keywords: str = ""
    min_employees: int | None = None
    max_employees: int | None = None
    industry_ids: tuple[str, ...] = ()
    seniority_ids: tuple[str, ...] = ()
    company_headcount: tuple[str, ...] = ()

    @property
    def has_icp(self) -> bool:
        return bool(
            self.industries.strip()
            or self.geographies.strip()
            or self.search_query.strip()
            or self.profile_urls
            or self.job_titles
            or self.target_companies
            or self.keywords.strip()
        )


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: list[DiscoveredLead]
    provider: str
    is_mock: bool
    connected: bool
    reason: str = ""
    failure_class: str = ""
    status_code: int = 0


class LeadDiscoveryProvider(Protocol):
    def health(self) -> dict[str, Any]: ...

    def discover(self, query: DiscoveryQuery) -> DiscoveryResult: ...


class MockLeadDiscoveryProvider:
    def health(self) -> dict[str, Any]:
        return {
            "provider": "mock-discovery",
            "is_mock": True,
            "connected": False,
            "reason": "DISCOVERY_PROVIDER is mock. Discovery will not invent people.",
        }

    def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        if not query.has_icp:
            return DiscoveryResult(
                candidates=[],
                provider="mock-discovery",
                is_mock=True,
                connected=False,
                reason="No ICP or profile URLs. Labeled mock returns no people.",
            )
        return DiscoveryResult(
            candidates=[],
            provider="mock-discovery",
            is_mock=True,
            connected=False,
            reason="Labeled mock. No live vendor. No invented prospects.",
        )


class NotConfiguredDiscoveryProvider:
    def health(self) -> dict[str, Any]:
        return {
            "provider": "apify",
            "is_mock": False,
            "connected": False,
            "reason": "DISCOVERY_PROVIDER is apify but APIFY_API_TOKEN or APIFY_ACTOR_ID is missing.",
        }

    def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        _ = query
        return DiscoveryResult(
            candidates=[],
            provider="apify",
            is_mock=False,
            connected=False,
            reason="Apify is not configured. No invented people.",
            failure_class="CONFIGURATION",
        )


class ApifyLeadDiscoveryProvider:
    def __init__(
        self,
        *,
        token: str,
        actor_id: str,
        max_items: int,
        process_token: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self._token = token
        self._actor_id = normalize_actor_id(actor_id)
        self._max_items = max(1, min(max_items, 50))
        self._process_token = process_token
        self._client = client

    def health(self) -> dict[str, Any]:
        return {
            "provider": "apify",
            "is_mock": False,
            "connected": True,
            "actor_id": self._actor_id.replace("~", "/"),
            "reason": "Apify token and actor are configured. People are persisted only from dataset items.",
        }

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=90.0)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _actor_input(self, query: DiscoveryQuery) -> dict[str, Any]:
        max_items = min(query.max_items or self._max_items, self._max_items)
        actor = self._actor_id.lower()
        payload: dict[str, Any] = {}
        if "profile-search" in actor:
            search = query.search_query or ", ".join(part for part in (query.keywords, query.industries, query.geographies) if part)
            payload = {
                "searchQuery": search,
                "maxItems": max_items,
                "profileScraperMode": "Short",
            }
            geos = [item.strip() for item in query.geographies.split(",") if item.strip()]
            if geos:
                payload["locations"] = geos
            if query.job_titles:
                payload["currentJobTitles"] = list(query.job_titles)[:20]
            if query.seniority_ids:
                payload["seniorityLevelIds"] = list(query.seniority_ids)
            if query.industry_ids:
                payload["industryIds"] = list(query.industry_ids)
            if query.company_headcount:
                payload["companyHeadcount"] = list(query.company_headcount)
            if query.target_companies:
                payload["currentCompanies"] = list(query.target_companies)
        else:
            urls = [url.strip() for url in query.profile_urls if url.strip()]
            payload = {
                "profileScraperMode": "Profile details no email ($4 per 1k)",
                "queries": urls,
            }
        if query.process_token or self._process_token:
            payload["token"] = query.process_token or self._process_token
        return payload

    def _failed(self, *, reason: str, status_code: int = 0, timeout: bool = False) -> DiscoveryResult:
        return DiscoveryResult(
            candidates=[],
            provider="apify",
            is_mock=False,
            connected=False,
            reason=reason,
            failure_class=classify_http(status_code, timeout=timeout) or "TRANSIENT",
            status_code=status_code,
        )

    def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        actor = self._actor_id.lower()
        urls = [url.strip() for url in query.profile_urls if url.strip()]
        if "profile-search" not in actor and not urls:
            return DiscoveryResult(
                candidates=[],
                provider="apify",
                is_mock=False,
                connected=True,
                reason=(
                    "Configured actor scrapes LinkedIn profile URLs only. "
                    "Pass profile URLs or set APIFY_ACTOR_ID to a search actor such as harvestapi/linkedin-profile-search."
                ),
                failure_class="CONFIGURATION",
            )
        owns_client = self._client is None
        client = self._http()
        try:
            start = client.post(
                f"https://api.apify.com/v2/acts/{self._actor_id}/runs",
                headers=self._headers(),
                json=self._actor_input(query),
                params={"waitForFinish": 60},
            )
            if start.status_code >= 400:
                return self._failed(
                    reason=f"Apify run refused ({start.status_code}). Falling back without inventing people.",
                    status_code=start.status_code,
                )
            body = start.json().get("data") or {}
            dataset_id = body.get("defaultDatasetId")
            status = body.get("status")
            if status not in {"SUCCEEDED", "READY"} or not dataset_id:
                wait = client.get(
                    f"https://api.apify.com/v2/actor-runs/{body.get('id')}",
                    headers=self._headers(),
                    params={"waitForFinish": 60},
                )
                if wait.status_code >= 400:
                    return self._failed(reason="Apify wait failed. No invented people.", status_code=wait.status_code)
                waited = wait.json().get("data") or {}
                dataset_id = waited.get("defaultDatasetId")
                status = waited.get("status")
            if status != "SUCCEEDED" or not dataset_id:
                return self._failed(reason=f"Apify run ended {status or 'unknown'}. Dataset empty.")
            items = client.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                headers=self._headers(),
                params={"limit": self._max_items},
            )
            if items.status_code >= 400:
                return self._failed(reason="Apify dataset read failed.", status_code=items.status_code)
            rows = items.json()
            if not isinstance(rows, list):
                return DiscoveryResult(
                    candidates=[],
                    provider="apify",
                    is_mock=False,
                    connected=True,
                    reason="Apify dataset was not a list.",
                )
            return DiscoveryResult(
                candidates=map_dataset_items(rows)[: self._max_items],
                provider="apify",
                is_mock=False,
                connected=True,
                reason="",
            )
        except httpx.TimeoutException:
            return self._failed(reason="Apify timeout. No invented people.", timeout=True)
        except httpx.HTTPError:
            return self._failed(reason="Apify network error. No invented people.", timeout=True)
        finally:
            if owns_client:
                client.close()


def map_dataset_items(rows: list[Any]) -> list[DiscoveredLead]:
    mapped: list[DiscoveredLead] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        first = _text(row, "firstName", "first_name", "firstname")
        last = _text(row, "lastName", "last_name", "lastname")
        if not first and not last:
            full = _text(row, "fullName", "name", "full_name")
            parts = full.split(None, 1)
            if parts:
                first = parts[0]
                last = parts[1] if len(parts) > 1 else ""
        email = _text(row, "email", "emails", "workEmail")
        title = _text(row, "title", "jobTitle", "headline", "occupation")
        company = _text(row, "companyName", "company", "company_name", "currentCompany")
        if not company and isinstance(row.get("currentPositions"), list) and row["currentPositions"]:
            position = row["currentPositions"][0]
            if isinstance(position, dict):
                company = _text(position, "companyName", "company")
                title = title or _text(position, "title")
        linkedin = _text(row, "linkedinUrl", "linkedin_url", "profileUrl", "url", "profile_url", "linkedinProfileUrl")
        provider_ref = _text(row, "id", "profileId", "linkedinId", "publicIdentifier", "urn")
        if not first or not last:
            continue
        mapped.append(
            DiscoveredLead(
                first_name=first[:80],
                last_name=last[:80],
                email=email[:255],
                title=title[:120],
                company_name=company[:200],
                linkedin_url=linkedin[:255],
                raw_keys=tuple(sorted(row.keys())),
                provider_ref=provider_ref[:200],
                confidence=70 if email or linkedin else 40,
                source_url=linkedin[:255],
            )
        )
    return mapped


def get_lead_discovery_provider(db: Session | None = None, tenant_id: UUID | None = None) -> LeadDiscoveryProvider:
    settings = get_settings()
    if db is not None and tenant_id is not None:
        resolved = resolve_channel(db, tenant_id, "discovery")
        if resolved.mode == "LIVE":
            token = resolved.secrets.get("access_token") or ""
            actor_id = resolved.secrets.get("actor_id") or settings.apify_actor_id
            if token and actor_id:
                return ApifyLeadDiscoveryProvider(
                    token=token,
                    actor_id=actor_id,
                    max_items=settings.apify_max_items,
                    process_token=resolved.secrets.get("process_token") or settings.apify_linkedin_process_token,
                )
            return NotConfiguredDiscoveryProvider()
        if resolved.mode == "MOCK":
            return MockLeadDiscoveryProvider()
        return NotConfiguredDiscoveryProvider()
    mode = (settings.discovery_provider or "mock").strip().lower()
    if mode == "apify":
        if settings.apify_configured:
            return ApifyLeadDiscoveryProvider(
                token=settings.resolved_apify_token,
                actor_id=settings.apify_actor_id,
                max_items=settings.apify_max_items,
                process_token=settings.apify_linkedin_process_token,
            )
        return NotConfiguredDiscoveryProvider()
    return MockLeadDiscoveryProvider()
