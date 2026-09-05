from fastapi.testclient import TestClient

from app.providers.lead_discovery import DiscoveredLead, DiscoveryResult, map_dataset_items
from tests.conftest import login


class FixtureDiscovery:
    def __init__(self, email: str = "priya.nair@fixture.example", first: str = "Priya", last: str = "Nair") -> None:
        self.email = email
        self.first = first
        self.last = last

    def health(self) -> dict:
        return {"provider": "fixture", "is_mock": True, "connected": False, "reason": "test fixture"}

    def discover(self, query) -> DiscoveryResult:
        _ = query
        person = DiscoveredLead(self.first, self.last, self.email, "CIO", "Fixture Bank", "https://linkedin.com/in/priya")
        return DiscoveryResult(
            candidates=[person, person],
            provider="fixture",
            is_mock=True,
            connected=False,
            reason="test fixture",
        )


def test_map_dataset_never_invents_missing_names() -> None:
    rows = map_dataset_items(
        [
            {"firstName": "Ada", "lastName": "Khan", "email": "ada@example.com", "title": "CTO", "companyName": "Harbor"},
            {"email": "nobody@example.com"},
        ]
    )
    assert len(rows) == 1
    assert rows[0].first_name == "Ada"
    assert rows[0].company_name == "Harbor"


def test_discover_persists_and_dedupes(client: TestClient, monkeypatch) -> None:
    fixture = FixtureDiscovery(email="priya.dedupe@fixture.example", first="Priya", last="Dedupe")
    monkeypatch.setattr("app.services.discovery.get_lead_discovery_provider", lambda: fixture)
    headers = login(client)
    first = client.post("/api/v1/discovery/run", headers=headers, json={})
    assert first.status_code == 200, first.text
    body = first.json()["data"]
    assert body["created"] == 1
    assert body["skipped"].get("duplicate_email") == 1
    second = client.post("/api/v1/discovery/run", headers=headers, json={})
    assert second.status_code == 200
    assert second.json()["data"]["created"] == 0
    assert second.json()["data"]["skipped"].get("duplicate_email") == 2
    leads = client.get("/api/v1/leads", headers=headers, params={"q": "Dedupe"}).json()["data"]
    assert any(row["source"] == "ai_discovery" and row["email"] == fixture.email for row in leads)
    assert all(not row["consent_email"] for row in leads if row["email"] == fixture.email)


def test_discover_skips_opt_out(client: TestClient, monkeypatch) -> None:
    headers = login(client)
    opted = client.post(
        "/api/v1/contacts",
        headers=headers,
        json={"first_name": "No", "last_name": "Hunt", "email": "no.hunt@fixture.example", "opt_out": True},
    )
    assert opted.status_code == 200

    class OptOutFixture(FixtureDiscovery):
        def discover(self, query) -> DiscoveryResult:
            _ = query
            return DiscoveryResult(
                candidates=[
                    DiscoveredLead("No", "Hunt", "no.hunt@fixture.example", "CISO", "Blocked Co", ""),
                ],
                provider="fixture",
                is_mock=True,
                connected=False,
                reason="test",
            )

    monkeypatch.setattr("app.services.discovery.get_lead_discovery_provider", lambda: OptOutFixture())
    run = client.post("/api/v1/discovery/run", headers=headers, json={})
    assert run.status_code == 200
    assert run.json()["data"]["created"] == 0
    assert run.json()["data"]["skipped"].get("opt_out") == 1


def test_human_add_and_discovery_source_guard(client: TestClient) -> None:
    headers = login(client)
    human = client.post(
        "/api/v1/leads",
        headers=headers,
        json={"first_name": "Offline", "last_name": "Find", "email": "offline.find@example.com", "company_name": "Paper Co"},
    )
    assert human.status_code == 200
    assert human.json()["data"]["source"] == "human"
    refused = client.post(
        "/api/v1/leads",
        headers=headers,
        json={
            "first_name": "Fake",
            "last_name": "Discover",
            "email": "fake.discover@example.com",
            "source": "ai_discovery",
        },
    )
    assert refused.status_code == 422


def test_import_sets_source_import(client: TestClient) -> None:
    headers = login(client)
    commit = client.post(
        "/api/v1/imports/commit",
        headers=headers,
        json={"entity": "leads", "rows": [{"first_name": "Csv", "last_name": "Row", "email": "csv.row@example.com"}]},
    )
    assert commit.status_code == 200
    leads = client.get("/api/v1/leads", headers=headers, params={"q": "Csv"}).json()["data"]
    assert any(row["source"] == "import" for row in leads)


def test_discovery_is_tenant_scoped(client: TestClient, monkeypatch) -> None:
    fixture = FixtureDiscovery(email="priya.scope@fixture.example", first="Priya", last="Scope")
    monkeypatch.setattr("app.services.discovery.get_lead_discovery_provider", lambda: fixture)
    agrayian = login(client, "admin@agrayian.demo")
    northline = login(client, "admin@northline.demo")
    created = client.post("/api/v1/discovery/run", headers=agrayian, json={})
    assert created.status_code == 200
    lead_id = created.json()["data"]["lead_ids"][0]
    leaked = client.get(f"/api/v1/leads/{lead_id}", headers=northline)
    assert leaked.status_code == 404
    other = client.get("/api/v1/leads", headers=northline, params={"q": "Scope"}).json()["data"]
    assert all(row["email"] != fixture.email for row in other)


def test_mock_discovery_without_people(client: TestClient) -> None:
    headers = login(client)
    health = client.get("/api/v1/discovery/health", headers=headers)
    assert health.status_code == 200
    run = client.post("/api/v1/discovery/run", headers=headers, json={})
    assert run.status_code == 200
    body = run.json()["data"]
    assert body["created"] == 0
    assert body["is_mock"] is True
