from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class UsageSnapshot:
    adoption: int
    usage: int
    provider: str
    is_mock: bool
    evidence: str


class ProductUsageProvider(Protocol):
    def snapshot(self, *, account_name: str) -> UsageSnapshot: ...


class MockProductUsageProvider:
    def snapshot(self, *, account_name: str) -> UsageSnapshot:
        seed = sum(ord(char) for char in account_name) % 21
        return UsageSnapshot(
            adoption=40 + seed,
            usage=35 + seed,
            provider="mock-usage",
            is_mock=True,
            evidence=f"Mock usage card for {account_name}. Not a product-analytics feed.",
        )


def get_usage_provider() -> ProductUsageProvider:
    return MockProductUsageProvider()
