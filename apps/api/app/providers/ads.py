from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx

from app.core.config import get_settings


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


@dataclass(frozen=True)
class AdsSpend:
    amount: Decimal | None
    currency: str
    provider: str
    is_mock: bool
    reason: str


class AdsProvider(Protocol):
    def health(self) -> AdsHealth: ...

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult: ...

    def get_spend(self, *, external_id: str) -> AdsSpend: ...


class MockAdsProvider:
    def __init__(self, channel: str) -> None:
        self._channel = channel

    def health(self) -> AdsHealth:
        return AdsHealth(
            provider=f"mock-{self._channel}",
            is_mock=True,
            connected=False,
            reason=f"No {self._channel} ads credentials. Spend is not invented.",
        )

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult:
        _ = (name, objective, budget)
        return AdsCampaignResult(
            ok=False,
            provider=f"mock-{self._channel}",
            is_mock=True,
            reason=f"No live {self._channel} ads provider. Campaign stays unlaunched. No fake CTR.",
        )

    def get_spend(self, *, external_id: str) -> AdsSpend:
        _ = external_id
        return AdsSpend(
            amount=None,
            currency="INR",
            provider=f"mock-{self._channel}",
            is_mock=True,
            reason="Spend is unknown until a live ads provider returns a ledger.",
        )


class LinkedInAdsProvider:
    def __init__(self, *, token: str, ad_account_id: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._account = ad_account_id
        self._client = client

    def health(self) -> AdsHealth:
        return AdsHealth(provider="linkedin-ads", is_mock=False, connected=True, reason="LinkedIn Marketing credentials are set.")

    def create_campaign(self, *, name: str, objective: str, budget: Decimal) -> AdsCampaignResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://api.linkedin.com/rest/adAccounts/{self._account}/adCampaigns",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Linkedin-Version": "202411",
                    "X-Restli-Protocol-Version": "2.0.0",
                    "Content-Type": "application/json",
                },
                json={
                    "name": name,
                    "status": "ACTIVE",
                    "type": "SPONSORED_UPDATES",
                    "objectiveType": "WEBSITE_VISIT",
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
                )
            data = response.json() if response.content else {}
            external_id = str(data.get("id") or response.headers.get("x-restli-id") or "")
            return AdsCampaignResult(ok=True, provider="linkedin-ads", is_mock=False, external_id=external_id)
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="linkedin-ads", is_mock=False, reason="LinkedIn network error. No invented spend.")
        finally:
            if owns:
                client.close()

    def get_spend(self, *, external_id: str) -> AdsSpend:
        if not external_id:
            return AdsSpend(amount=None, currency="USD", provider="linkedin-ads", is_mock=False, reason="No provider campaign id.")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.get(
                f"https://api.linkedin.com/rest/adCampaigns/{external_id}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Linkedin-Version": "202411",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
            )
            if response.status_code >= 400:
                return AdsSpend(amount=None, currency="USD", provider="linkedin-ads", is_mock=False, reason="LinkedIn spend read refused.")
            return AdsSpend(amount=None, currency="USD", provider="linkedin-ads", is_mock=False, reason="Campaign exists. Cost analytics were not returned.")
        except httpx.HTTPError:
            return AdsSpend(amount=None, currency="USD", provider="linkedin-ads", is_mock=False, reason="LinkedIn network error.")
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
        _ = (objective, budget)
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"https://graph.facebook.com/v21.0/act_{self._account}/campaigns",
                params={"access_token": self._token},
                data={
                    "name": name,
                    "objective": "OUTCOME_TRAFFIC",
                    "status": "PAUSED",
                    "special_ad_categories": "[]",
                },
            )
            if response.status_code >= 400:
                return AdsCampaignResult(
                    ok=False,
                    provider="meta-ads",
                    is_mock=False,
                    reason=f"Meta Marketing API refused launch ({response.status_code}). No invented spend.",
                )
            data = response.json() if response.content else {}
            return AdsCampaignResult(ok=True, provider="meta-ads", is_mock=False, external_id=str(data.get("id") or ""))
        except httpx.HTTPError:
            return AdsCampaignResult(ok=False, provider="meta-ads", is_mock=False, reason="Meta network error. No invented spend.")
        finally:
            if owns:
                client.close()

    def get_spend(self, *, external_id: str) -> AdsSpend:
        if not external_id:
            return AdsSpend(amount=None, currency="USD", provider="meta-ads", is_mock=False, reason="No provider campaign id.")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.get(
                f"https://graph.facebook.com/v21.0/{external_id}/insights",
                params={"access_token": self._token, "fields": "spend"},
            )
            if response.status_code >= 400:
                return AdsSpend(amount=None, currency="USD", provider="meta-ads", is_mock=False, reason="Meta spend read refused.")
            rows = (response.json() or {}).get("data") or []
            if not rows or rows[0].get("spend") in {None, ""}:
                return AdsSpend(amount=None, currency="USD", provider="meta-ads", is_mock=False, reason="Meta returned no spend yet.")
            return AdsSpend(
                amount=Decimal(str(rows[0]["spend"])),
                currency="USD",
                provider="meta-ads",
                is_mock=False,
                reason="",
            )
        except (httpx.HTTPError, ValueError):
            return AdsSpend(amount=None, currency="USD", provider="meta-ads", is_mock=False, reason="Meta spend could not be parsed.")
        finally:
            if owns:
                client.close()


def get_ads_provider(channel: str) -> AdsProvider:
    settings = get_settings()
    normalized = channel.strip().lower()
    if normalized == "linkedin":
        if settings.linkedin_ads_configured:
            return LinkedInAdsProvider(token=settings.linkedin_access_token, ad_account_id=settings.linkedin_ad_account_id)
        return MockAdsProvider("linkedin")
    if normalized in {"instagram", "meta", "facebook"}:
        if settings.meta_ads_configured:
            return MetaAdsProvider(token=settings.meta_access_token, ad_account_id=settings.meta_ad_account_id)
        return MockAdsProvider("instagram")
    return MockAdsProvider(normalized or "ads")
