from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class CompanyProfile:
    name: str
    industry: str
    domain: str
    hq_country: str
    employee_count: int | None
    summary: str
    provider: str
    is_mock: bool


@dataclass(frozen=True)
class ContactHint:
    first_name: str
    last_name: str
    title: str
    seniority: str
    provider: str
    is_mock: bool


@dataclass(frozen=True)
class IntentTopic:
    topic: str
    intensity: int
    evidence: str
    provider: str
    is_mock: bool


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    occurred_at: datetime
    provider: str
    is_mock: bool


@dataclass(frozen=True)
class TechnologyFootprint:
    technology: str
    category: str
    evidence: str
    provider: str
    is_mock: bool


class CompanyDataProvider(Protocol):
    def lookup(self, *, name: str, domain: str, industry: str) -> CompanyProfile: ...


class ContactDataProvider(Protocol):
    def hints(self, *, company_name: str, industry: str) -> list[ContactHint]: ...


class IntentDataProvider(Protocol):
    def topics(self, *, company_name: str, industry: str) -> list[IntentTopic]: ...


class NewsProvider(Protocol):
    def headlines(self, *, company_name: str, industry: str) -> list[NewsItem]: ...


class TechnologyDataProvider(Protocol):
    def stack(self, *, company_name: str, industry: str) -> list[TechnologyFootprint]: ...


class MockCompanyDataProvider:
    def lookup(self, *, name: str, domain: str, industry: str) -> CompanyProfile:
        return CompanyProfile(
            name=name,
            industry=industry,
            domain=domain,
            hq_country="",
            employee_count=None,
            summary=f"Mock firmographic card for {name} in {industry or 'an unclassified'} market. Not a live data vendor.",
            provider="mock-company",
            is_mock=True,
        )


class MockContactDataProvider:
    def hints(self, *, company_name: str, industry: str) -> list[ContactHint]:
        return [
            ContactHint(
                first_name="Alex",
                last_name="Review",
                title="Head of Transformation",
                seniority="executive",
                provider="mock-contact",
                is_mock=True,
            )
        ]


class MockIntentDataProvider:
    def topics(self, *, company_name: str, industry: str) -> list[IntentTopic]:
        topic = "AI governance" if industry in {"bfsi", "government", "healthcare"} else "AI copilot"
        return [
            IntentTopic(
                topic=topic,
                intensity=62 if industry else 40,
                evidence=f"Mock surge on {topic} research around {company_name}.",
                provider="mock-intent",
                is_mock=True,
            )
        ]


class MockNewsProvider:
    def headlines(self, *, company_name: str, industry: str) -> list[NewsItem]:
        return [
            NewsItem(
                title=f"{company_name} opens an AI review cycle",
                summary=f"Mock news item for {industry or 'general'} buyers. Not scraped from the public web.",
                occurred_at=datetime.now(UTC),
                provider="mock-news",
                is_mock=True,
            )
        ]


class MockTechnologyDataProvider:
    def stack(self, *, company_name: str, industry: str) -> list[TechnologyFootprint]:
        return [
            TechnologyFootprint(
                technology="Snowflake" if industry == "bfsi" else "Kubernetes",
                category="data" if industry == "bfsi" else "platform",
                evidence=f"Mock technology footprint for {company_name}.",
                provider="mock-tech",
                is_mock=True,
            )
        ]


def get_company_provider() -> CompanyDataProvider:
    return MockCompanyDataProvider()


def get_contact_provider() -> ContactDataProvider:
    return MockContactDataProvider()


def get_intent_provider() -> IntentDataProvider:
    return MockIntentDataProvider()


def get_news_provider() -> NewsProvider:
    return MockNewsProvider()


def get_technology_provider() -> TechnologyDataProvider:
    return MockTechnologyDataProvider()
