from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.provider_ops import classify_http
from app.services.provider_resolve import resolve_channel

LINKEDIN_OBJECTIVES = {
    "pipeline": "LEAD_GENERATION",
    "lead": "LEAD_GENERATION",
    "traffic": "WEBSITE_VISIT",
    "website": "WEBSITE_VISIT",
    "awareness": "BRAND_AWARENESS",
    "engagement": "ENGAGEMENT",
}

META_OBJECTIVES = {
    "pipeline": "OUTCOME_LEADS",
    "lead": "OUTCOME_LEADS",
    "traffic": "OUTCOME_TRAFFIC",
    "website": "OUTCOME_TRAFFIC",
    "awareness": "OUTCOME_AWARENESS",
    "engagement": "OUTCOME_ENGAGEMENT",
}

STATUS_MAP = {
    "ACTIVE": "ACTIVE",
    "ENABLED": "ACTIVE",
    "PAUSED": "PAUSED",
    "DRAFT": "CREATED",
    "PENDING": "PENDING",
    "IN_PROCESS": "PENDING",
    "IN_REVIEW": "PENDING",
    "PROPOSED": "PENDING",
    "REJECTED": "REJECTED",
    "DISAPPROVED": "REJECTED",
    "WITH_ISSUES": "REJECTED",
    "ARCHIVED": "COMPLETED",
    "COMPLETED": "COMPLETED",
    "DELETED": "FAILED",
    "FAILED": "FAILED",
    "ERROR": "FAILED",
    "CREATED": "CREATED",
}


def normalize_ad_status(raw: str) -> str:
    return STATUS_MAP.get((raw or "").strip().upper(), "PENDING" if raw else "")


@dataclass(frozen=True)
class AdsHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str


@dataclass(frozen=True)
class AdsCampaignResult:
    ok: bool
    provider: str
    is_mock: bool
    external_id: str = ""
    reason: str = ""
    status_code: int = 0
    failure_class: str = ""
    provider_status: str = ""


@dataclass(frozen=True)
class AdsSpend:
    amount: Decimal | None
    currency: str
    provider: str
    is_mock: bool
    reason: str


@dataclass(frozen=True)
class AdsMetrics:
    spend: Decimal | None
    impressions: int | None
    clicks: int | None
    conversions: int | None
    currency: str
    provider: str
    is_mock: bool
    reason: str = ""
    provider_status: str = ""


class AdsProvider(Protocol):
    def health(self) -> AdsHealth: ...

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult: ...

    def pause_campaign(self, *, external_id: str) -> AdsCampaignResult: ...

    def get_status(self, *, external_id: str) -> AdsCampaignResult: ...

    def get_spend(self, *, external_id: str) -> AdsSpend: ...

    def get_metrics(self, *, external_id: str) -> AdsMetrics: ...

    def create_ad_set(self, *, campaign_external_id: str, name: str, budget: Decimal) -> AdsCampaignResult: ...

    def create_creative(self, *, name: str, headline: str, body: str) -> AdsCampaignResult: ...

    def create_ad(self, *, ad_set_external_id: str, creative_external_id: str, name: str) -> AdsCampaignResult: ...

    def activate_campaign(self, *, external_id: str) -> AdsCampaignResult: ...

    def sync_audience(self, *, name: str, identifiers: list[str], lookalike: bool = False) -> AdsCampaignResult: ...


class MockAdsProvider:
    def __init__(self, channel: str) -> None:
        self._channel = channel

    def health(self) -> AdsHealth:
        return AdsHealth(
            provider=f"mock-{self._channel}",
            is_mock=True,
            connected=False,
            reason=f"No live {self._channel} ads mode. Spend is not invented.",
        )

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult:
        _ = (name, objective, budget)
        return AdsCampaignResult(
            ok=False,
            provider=f"mock-{self._channel}",
            is_mock=True,
            reason=f"No live {self._channel} ads provider. Campaign stays unlaunched. No fake CTR.",
            failure_class="CONFIGURATION",
        )

    def pause_campaign(self, *, external_id: str) -> AdsCampaignResult:
        _ = external_id
        return AdsCampaignResult(
            ok=False,
            provider=f"mock-{self._channel}",
            is_mock=True,
            reason="Labeled mock cannot pause a live campaign.",
            failure_class="CONFIGURATION",
        )

    def get_status(self, *, external_id: str) -> AdsCampaignResult:
        _ = external_id
        return AdsCampaignResult(ok=False, provider=f"mock-{self._channel}", is_mock=True, reason="Mock has no campaign status.")

    def get_spend(self, *, external_id: str) -> AdsSpend:
        _ = external_id
        return AdsSpend(
            amount=None,
            currency="INR",
            provider=f"mock-{self._channel}",
            is_mock=True,
            reason="Spend is unknown until a live ads provider returns a ledger.",
        )

    def get_metrics(self, *, external_id: str) -> AdsMetrics:
        _ = external_id
        return AdsMetrics(
            spend=None,
            impressions=None,
            clicks=None,
            conversions=None,
            currency="INR",
            provider=f"mock-{self._channel}",
            is_mock=True,
            reason="Metrics are unknown until a live ads provider returns them.",
        )

    def create_ad_set(self, *, campaign_external_id: str, name: str, budget: Decimal) -> AdsCampaignResult:
        _ = (campaign_external_id, name, budget)
        return AdsCampaignResult(ok=False, provider=f"mock-{self._channel}", is_mock=True, reason="Labeled mock cannot create an ad set.", failure_class="CONFIGURATION")

    def create_creative(self, *, name: str, headline: str, body: str) -> AdsCampaignResult:
        _ = (name, headline, body)
        return AdsCampaignResult(ok=False, provider=f"mock-{self._channel}", is_mock=True, reason="Labeled mock cannot publish a creative.", failure_class="CONFIGURATION")

    def create_ad(self, *, ad_set_external_id: str, creative_external_id: str, name: str) -> AdsCampaignResult:
        _ = (ad_set_external_id, creative_external_id, name)
        return AdsCampaignResult(ok=False, provider=f"mock-{self._channel}", is_mock=True, reason="Labeled mock cannot create an ad.", failure_class="CONFIGURATION")

    def activate_campaign(self, *, external_id: str) -> AdsCampaignResult:
        _ = external_id
        return AdsCampaignResult(ok=False, provider=f"mock-{self._channel}", is_mock=True, reason="Labeled mock cannot activate a campaign.", failure_class="CONFIGURATION")

    def sync_audience(self, *, name: str, identifiers: list[str], lookalike: bool = False) -> AdsCampaignResult:
        _ = (name, identifiers, lookalike)
        return AdsCampaignResult(ok=False, provider=f"mock-{self._channel}", is_mock=True, reason="Labeled mock cannot sync an audience.", failure_class="CONFIGURATION")


class NotConfiguredAdsProvider(MockAdsProvider):
    def health(self) -> AdsHealth:
        return AdsHealth(
            provider=f"{self._channel}-ads",
            is_mock=False,
            connected=False,
            reason=f"{self._channel} ads mode is live but credentials are missing.",
        )

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult:
        _ = (name, objective, budget)
        return AdsCampaignResult(
            ok=False,
            provider=f"{self._channel}-ads",
            is_mock=False,
            reason=f"{self._channel} ads is not configured. Campaign was not launched.",
            failure_class="CONFIGURATION",
        )

    def create_ad_set(self, *, campaign_external_id: str, name: str, budget: Decimal) -> AdsCampaignResult:
        _ = (campaign_external_id, name, budget)
        return AdsCampaignResult(ok=False, provider=f"{self._channel}-ads", is_mock=False, reason=f"{self._channel} ads is not configured.", failure_class="CONFIGURATION")

    def create_creative(self, *, name: str, headline: str, body: str) -> AdsCampaignResult:
        _ = (name, headline, body)
        return AdsCampaignResult(ok=False, provider=f"{self._channel}-ads", is_mock=False, reason=f"{self._channel} ads is not configured.", failure_class="CONFIGURATION")

    def create_ad(self, *, ad_set_external_id: str, creative_external_id: str, name: str) -> AdsCampaignResult:
        _ = (ad_set_external_id, creative_external_id, name)
        return AdsCampaignResult(ok=False, provider=f"{self._channel}-ads", is_mock=False, reason=f"{self._channel} ads is not configured.", failure_class="CONFIGURATION")

    def activate_campaign(self, *, external_id: str) -> AdsCampaignResult:
        _ = external_id
        return AdsCampaignResult(ok=False, provider=f"{self._channel}-ads", is_mock=False, reason=f"{self._channel} ads is not configured.", failure_class="CONFIGURATION")

    def sync_audience(self, *, name: str, identifiers: list[str], lookalike: bool = False) -> AdsCampaignResult:
        _ = (name, identifiers, lookalike)
        return AdsCampaignResult(ok=False, provider=f"{self._channel}-ads", is_mock=False, reason=f"{self._channel} ads is not configured.", failure_class="CONFIGURATION")


def _decimal(value: object) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


class LinkedInAdsProvider:
    def __init__(self, *, token: str, ad_account_id: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._account = ad_account_id
        self._client = client

    def health(self) -> AdsHealth:
        return AdsHealth(provider="linkedin-ads", is_mock=False, connected=True, reason="LinkedIn Marketing credentials are set.")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Linkedin-Version": "202411",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        mapped = LINKEDIN_OBJECTIVES.get(objective.strip().lower(), "WEBSITE_VISIT")
        try:
            response = client.post(
                f"https://api.linkedin.com/rest/adAccounts/{self._account}/adCampaigns",
                headers=self._headers(),
                json={
                    "name": name,
                    "status": "ACTIVE",
                    "type": "SPONSORED_UPDATES",
                    "objectiveType": mapped,
                    "dailyBudget": {"amount": str(budget), "currencyCode": "USD"},
                    "unitCost": {"amount": "0", "currencyCode": "USD"},
                    "locale": {"country": "US", "language": "en"},
                    "offsiteDeliveryEnabled": False,
                },
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="linkedin-ads",
                    is_mock=False,
                    reason=f"LinkedIn Marketing API refused launch ({response.status_code}). No invented spend.",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            external_id = str(data.get("id") or response.headers.get("x-restli-id") or "")
            return AdsCampaignResult(
                ok=bool(external_id),
                provider="linkedin-ads",
                is_mock=False,
                external_id=external_id,
                provider_status="ACTIVE",
                reason="" if external_id else "LinkedIn returned no campaign id.",
            )
        except httpx.TimeoutException:
            return AdsCampaignResult(
                ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn timeout. No invented spend.", failure_class="TRANSIENT"
            )
        except httpx.HTTPError:
            return AdsCampaignResult(
                ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn network error. No invented spend.", failure_class="TRANSIENT"
            )
        finally:
            if owns:
                client.close()

    def pause_campaign(self, *, external_id: str) -> AdsCampaignResult:
        if not external_id:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="No provider campaign id.", failure_class="PERMANENT")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.linkedin.com/rest/adCampaigns/{external_id}",
                headers={**self._headers(), "X-RestLi-Method": "PARTIAL_UPDATE"},
                json={"patch": {"$set": {"status": "PAUSED"}}},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="linkedin-ads",
                    is_mock=False,
                    reason=f"LinkedIn pause refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            return AdsCampaignResult(ok=True, provider="linkedin-ads", is_mock=False, external_id=external_id, provider_status="PAUSED")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def get_status(self, *, external_id: str) -> AdsCampaignResult:
        metrics = self.get_metrics(external_id=external_id)
        return AdsCampaignResult(
            ok=not metrics.reason.startswith("LinkedIn"),
            provider="linkedin-ads",
            is_mock=False,
            external_id=external_id,
            reason=metrics.reason,
            provider_status=metrics.provider_status,
        )

    def get_spend(self, *, external_id: str) -> AdsSpend:
        metrics = self.get_metrics(external_id=external_id)
        return AdsSpend(amount=metrics.spend, currency=metrics.currency, provider=metrics.provider, is_mock=False, reason=metrics.reason)

    def get_metrics(self, *, external_id: str) -> AdsMetrics:
        empty = AdsMetrics(spend=None, impressions=None, clicks=None, conversions=None, currency="USD", provider="linkedin-ads", is_mock=False)
        if not external_id:
            return AdsMetrics(**{**empty.__dict__, "reason": "No provider campaign id."})
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            campaign = client.get(f"https://api.linkedin.com/rest/adCampaigns/{external_id}", headers=self._headers())
            if campaign.status_code >= 400:
                return AdsMetrics(**{**empty.__dict__, "reason": "LinkedIn campaign read refused."})
            status = normalize_ad_status(str((campaign.json() or {}).get("status") or ""))
            analytics = client.get(
                "https://api.linkedin.com/rest/adAnalytics",
                headers=self._headers(),
                params={
                    "q": "analytics",
                    "pivot": "CAMPAIGN",
                    "timeGranularity": "ALL",
                    "campaigns": f"List(urn:li:sponsoredCampaign:{external_id})",
                    "fields": "impressions,clicks,costInLocalCurrency,externalWebsiteConversions",
                },
            )
            if analytics.status_code >= 400:
                return AdsMetrics(**{**empty.__dict__, "reason": "LinkedIn analytics were not returned.", "provider_status": status})
            rows = analytics.json() if analytics.content else {}
            elements = rows.get("elements") if isinstance(rows, dict) else rows
            first = elements[0] if isinstance(elements, list) and elements else {}
            if not isinstance(first, dict):
                return AdsMetrics(**{**empty.__dict__, "provider_status": status, "reason": "LinkedIn analytics empty."})
            return AdsMetrics(
                spend=_decimal(first.get("costInLocalCurrency") or first.get("costInUsd")),
                impressions=_int(first.get("impressions")),
                clicks=_int(first.get("clicks")),
                conversions=_int(first.get("externalWebsiteConversions") or first.get("conversions")),
                currency="USD",
                provider="linkedin-ads",
                is_mock=False,
                provider_status=status,
            )
        except httpx.HTTPError:
            return AdsMetrics(**{**empty.__dict__, "reason": "LinkedIn network error."})
        finally:
            if owns:
                client.close()

    def create_ad_set(self, *, campaign_external_id: str, name: str, budget: Decimal) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.linkedin.com/rest/adAccounts/{self._account}/adCampaignGroups",
                headers=self._headers(),
                json={"name": name, "status": "ACTIVE", "totalBudget": {"amount": str(budget), "currencyCode": "USD"}},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="linkedin-ads",
                    is_mock=False,
                    reason=f"LinkedIn ad set refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            external_id = str(data.get("id") or response.headers.get("x-restli-id") or "")
            return AdsCampaignResult(ok=bool(external_id), provider="linkedin-ads", is_mock=False, external_id=external_id, provider_status="ACTIVE")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def create_creative(self, *, name: str, headline: str, body: str) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.linkedin.com/rest/adAccounts/{self._account}/creatives",
                headers=self._headers(),
                json={"name": name, "status": "DRAFT", "content": {"headline": headline, "commentary": body}},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="linkedin-ads",
                    is_mock=False,
                    reason=f"LinkedIn creative refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            external_id = str(data.get("id") or response.headers.get("x-restli-id") or "")
            return AdsCampaignResult(ok=bool(external_id), provider="linkedin-ads", is_mock=False, external_id=external_id, provider_status="DRAFT")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def create_ad(self, *, ad_set_external_id: str, creative_external_id: str, name: str) -> AdsCampaignResult:
        _ = ad_set_external_id
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.linkedin.com/rest/adAccounts/{self._account}/ads",
                headers=self._headers(),
                json={"name": name, "status": "ACTIVE", "creative": creative_external_id},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="linkedin-ads",
                    is_mock=False,
                    reason=f"LinkedIn ad refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            external_id = str(data.get("id") or response.headers.get("x-restli-id") or "")
            return AdsCampaignResult(ok=bool(external_id), provider="linkedin-ads", is_mock=False, external_id=external_id, provider_status="ACTIVE")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def activate_campaign(self, *, external_id: str) -> AdsCampaignResult:
        if not external_id:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="No provider campaign id.", failure_class="PERMANENT")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.linkedin.com/rest/adCampaigns/{external_id}",
                headers={**self._headers(), "X-RestLi-Method": "PARTIAL_UPDATE"},
                json={"patch": {"$set": {"status": "ACTIVE"}}},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="linkedin-ads",
                    is_mock=False,
                    reason=f"LinkedIn activate refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            return AdsCampaignResult(ok=True, provider="linkedin-ads", is_mock=False, external_id=external_id, provider_status="ACTIVE")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def sync_audience(self, *, name: str, identifiers: list[str], lookalike: bool = False) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.linkedin.com/rest/adAccounts/{self._account}/dmpSegments",
                headers=self._headers(),
                json={"name": name, "account": f"urn:li:sponsoredAccount:{self._account}", "type": "LOOKALIKE" if lookalike else "USER_LIST", "destinations": identifiers[:10000]},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="linkedin-ads",
                    is_mock=False,
                    reason=f"LinkedIn audience refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            external_id = str(data.get("id") or response.headers.get("x-restli-id") or "")
            return AdsCampaignResult(ok=bool(external_id), provider="linkedin-ads", is_mock=False, external_id=external_id, provider_status="PENDING")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()


class MetaAdsProvider:
    def __init__(self, *, token: str, ad_account_id: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._account = ad_account_id.removeprefix("act_")
        self._client = client

    def health(self) -> AdsHealth:
        return AdsHealth(provider="meta-ads", is_mock=False, connected=True, reason="Meta Marketing credentials are set.")

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        mapped = META_OBJECTIVES.get(objective.strip().lower(), "OUTCOME_TRAFFIC")
        cents = int(budget * 100)
        try:
            response = client.post(
                f"https://graph.facebook.com/v21.0/act_{self._account}/campaigns",
                params={"access_token": self._token},
                data={
                    "name": name,
                    "objective": mapped,
                    "status": "PAUSED",
                    "special_ad_categories": "[]",
                    "daily_budget": str(max(cents, 100)),
                },
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="meta-ads",
                    is_mock=False,
                    reason=f"Meta Marketing API refused launch ({response.status_code}). No invented spend.",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            data = response.json() if response.content else {}
            external_id = str(data.get("id") or "")
            return AdsCampaignResult(
                ok=bool(external_id),
                provider="meta-ads",
                is_mock=False,
                external_id=external_id,
                provider_status="PAUSED",
                reason="" if external_id else "Meta returned no campaign id.",
            )
        except httpx.HTTPError:
            return AdsCampaignResult(
                ok=False, provider="meta-ads", is_mock=False, reason="Meta network error. No invented spend.", failure_class="TRANSIENT"
            )
        finally:
            if owns:
                client.close()

    def pause_campaign(self, *, external_id: str) -> AdsCampaignResult:
        if not external_id:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="No provider campaign id.", failure_class="PERMANENT")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://graph.facebook.com/v21.0/{external_id}",
                params={"access_token": self._token},
                data={"status": "PAUSED"},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="meta-ads",
                    is_mock=False,
                    reason=f"Meta pause refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            return AdsCampaignResult(ok=True, provider="meta-ads", is_mock=False, external_id=external_id, provider_status="PAUSED")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="Meta network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def get_status(self, *, external_id: str) -> AdsCampaignResult:
        metrics = self.get_metrics(external_id=external_id)
        return AdsCampaignResult(
            ok=True,
            provider="meta-ads",
            is_mock=False,
            external_id=external_id,
            reason=metrics.reason,
            provider_status=metrics.provider_status,
        )

    def get_spend(self, *, external_id: str) -> AdsSpend:
        metrics = self.get_metrics(external_id=external_id)
        return AdsSpend(amount=metrics.spend, currency=metrics.currency, provider="meta-ads", is_mock=False, reason=metrics.reason)

    def get_metrics(self, *, external_id: str) -> AdsMetrics:
        empty = AdsMetrics(spend=None, impressions=None, clicks=None, conversions=None, currency="USD", provider="meta-ads", is_mock=False)
        if not external_id:
            return AdsMetrics(**{**empty.__dict__, "reason": "No provider campaign id."})
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            campaign = client.get(
                f"https://graph.facebook.com/v21.0/{external_id}",
                params={"access_token": self._token, "fields": "status,effective_status"},
            )
            status = ""
            if campaign.status_code < 400:
                body = campaign.json() or {}
                status = normalize_ad_status(str(body.get("effective_status") or body.get("status") or ""))
            insights = client.get(
                f"https://graph.facebook.com/v21.0/{external_id}/insights",
                params={"access_token": self._token, "fields": "spend,impressions,clicks,actions"},
            )
            if insights.status_code >= 400:
                return AdsMetrics(**{**empty.__dict__, "provider_status": status, "reason": "Meta insights were not returned."})
            rows = (insights.json() or {}).get("data") or []
            first = rows[0] if rows else {}
            conversions = None
            actions = first.get("actions") if isinstance(first, dict) else None
            if isinstance(actions, list):
                for action in actions:
                    if isinstance(action, dict) and action.get("action_type") in {"offsite_conversion", "purchase", "lead"}:
                        conversions = _int(action.get("value"))
                        if conversions is not None:
                            break
            return AdsMetrics(
                spend=_decimal(first.get("spend") if isinstance(first, dict) else None),
                impressions=_int(first.get("impressions") if isinstance(first, dict) else None),
                clicks=_int(first.get("clicks") if isinstance(first, dict) else None),
                conversions=conversions,
                currency="USD",
                provider="meta-ads",
                is_mock=False,
                provider_status=status,
            )
        except httpx.HTTPError:
            return AdsMetrics(**{**empty.__dict__, "reason": "Meta network error."})
        finally:
            if owns:
                client.close()

    def create_ad_set(self, *, campaign_external_id: str, name: str, budget: Decimal) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        cents = int(budget * 100)
        try:
            response = client.post(
                f"https://graph.facebook.com/v21.0/act_{self._account}/adsets",
                params={"access_token": self._token},
                data={
                    "name": name,
                    "campaign_id": campaign_external_id,
                    "daily_budget": str(max(cents, 100)),
                    "billing_event": "IMPRESSIONS",
                    "optimization_goal": "REACH",
                    "status": "PAUSED",
                    "targeting": '{"geo_locations":{"countries":["IN"]}}',
                },
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="meta-ads",
                    is_mock=False,
                    reason=f"Meta ad set refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            external_id = str((response.json() or {}).get("id") or "")
            return AdsCampaignResult(ok=bool(external_id), provider="meta-ads", is_mock=False, external_id=external_id, provider_status="PAUSED")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="Meta network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def create_creative(self, *, name: str, headline: str, body: str) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://graph.facebook.com/v21.0/act_{self._account}/adcreatives",
                params={"access_token": self._token},
                data={"name": name, "title": headline, "body": body, "object_story_spec": "{}"},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="meta-ads",
                    is_mock=False,
                    reason=f"Meta creative refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            external_id = str((response.json() or {}).get("id") or "")
            return AdsCampaignResult(ok=bool(external_id), provider="meta-ads", is_mock=False, external_id=external_id, provider_status="DRAFT")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="Meta network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def create_ad(self, *, ad_set_external_id: str, creative_external_id: str, name: str) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://graph.facebook.com/v21.0/act_{self._account}/ads",
                params={"access_token": self._token},
                data={"name": name, "adset_id": ad_set_external_id, "creative": f'{{"creative_id":"{creative_external_id}"}}', "status": "PAUSED"},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="meta-ads",
                    is_mock=False,
                    reason=f"Meta ad refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            external_id = str((response.json() or {}).get("id") or "")
            return AdsCampaignResult(ok=bool(external_id), provider="meta-ads", is_mock=False, external_id=external_id, provider_status="PAUSED")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="Meta network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def activate_campaign(self, *, external_id: str) -> AdsCampaignResult:
        if not external_id:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="No provider campaign id.", failure_class="PERMANENT")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://graph.facebook.com/v21.0/{external_id}",
                params={"access_token": self._token},
                data={"status": "ACTIVE"},
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="meta-ads",
                    is_mock=False,
                    reason=f"Meta activate refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            return AdsCampaignResult(ok=True, provider="meta-ads", is_mock=False, external_id=external_id, provider_status="ACTIVE")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="Meta network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()

    def sync_audience(self, *, name: str, identifiers: list[str], lookalike: bool = False) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            payload = {
                "name": name,
                "subtype": "LOOKALIKE" if lookalike else "CUSTOM",
                "customer_file_source": "USER_PROVIDED_ONLY",
            }
            response = client.post(
                f"https://graph.facebook.com/v21.0/act_{self._account}/customaudiences",
                params={"access_token": self._token},
                data=payload,
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="meta-ads",
                    is_mock=False,
                    reason=f"Meta audience refused ({response.status_code}).",
                    status_code=response.status_code,
                    failure_class=classify_http(response.status_code),
                )
            external_id = str((response.json() or {}).get("id") or "")
            if external_id and identifiers:
                client.post(
                    f"https://graph.facebook.com/v21.0/{external_id}/users",
                    params={"access_token": self._token},
                    json={"payload": {"schema": ["EMAIL"], "data": [[item] for item in identifiers[:10000]]}},
                )
            return AdsCampaignResult(ok=bool(external_id), provider="meta-ads", is_mock=False, external_id=external_id, provider_status="PENDING")
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="Meta network error.", failure_class="TRANSIENT")
        finally:
            if owns:
                client.close()


def _ads_from_resolved(channel: str, resolved) -> AdsProvider:
    if resolved.mode == "MOCK":
        return MockAdsProvider(channel if channel != "meta" else "instagram")
    if resolved.mode != "LIVE":
        return NotConfiguredAdsProvider(channel)
    token = resolved.secrets.get("access_token") or ""
    account_id = resolved.secrets.get("account_id") or ""
    if not token or not account_id:
        return NotConfiguredAdsProvider(channel)
    if channel == "linkedin":
        return LinkedInAdsProvider(token=token, ad_account_id=account_id)
    return MetaAdsProvider(token=token, ad_account_id=account_id)


def get_ads_provider(channel: str, db: Session | None = None, tenant_id: UUID | None = None) -> AdsProvider:
    settings = get_settings()
    normalized = channel.strip().lower()
    key = "linkedin" if normalized == "linkedin" else "meta"
    if normalized not in {"linkedin", "instagram", "meta", "facebook"}:
        return MockAdsProvider(normalized or "ads")
    if db is not None and tenant_id is not None:
        return _ads_from_resolved(key, resolve_channel(db, tenant_id, key))
    if key == "linkedin":
        mode = (settings.linkedin_ads_mode or "mock").strip().lower()
        if mode == "live":
            if settings.linkedin_ads_configured:
                return LinkedInAdsProvider(token=settings.linkedin_access_token, ad_account_id=settings.linkedin_ad_account_id)
            return NotConfiguredAdsProvider("linkedin")
        return MockAdsProvider("linkedin")
    mode = (settings.meta_ads_mode or "mock").strip().lower()
    if mode == "live":
        if settings.meta_ads_configured:
            return MetaAdsProvider(token=settings.meta_access_token, ad_account_id=settings.meta_ad_account_id)
        return NotConfiguredAdsProvider("meta")
    return MockAdsProvider("instagram")
