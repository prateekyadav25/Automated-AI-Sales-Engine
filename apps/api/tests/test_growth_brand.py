"""Brand intelligence from a scripted website. No network, no model."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.growth import BrandFact, BrandProfile, BrandSource
from app.services.growth import brand as brand_service
from app.services.growth.brand_extract import extract_page, keyphrases, robots_disallows, voice_profile
from tests.conftest import login
from tests.growth_support import fake_site, logo_png, site_fetcher, user


def test_website_analysis_keeps_sources_and_invents_nothing(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        pages, requested = fake_site()
        result = brand_service.analyze_website(db, tenant_id=admin.tenant_id, actor_id=admin.id, website_url="https://northwind.example/", fetcher=site_fetcher(pages, requested, logo_png()))
        assert result["status"] == "analyzed", result["detail"]
        assert "https://northwind.example/private/admin" not in requested
        blocked = db.scalar(select(BrandSource).where(BrandSource.tenant_id == admin.tenant_id, BrandSource.url == "https://northwind.example/private/admin"))
        assert blocked is not None and blocked.status == "robots_disallowed"
        facts = db.scalars(select(BrandFact).where(BrandFact.tenant_id == admin.tenant_id, BrandFact.deleted_at.is_(None))).all()
        by_category: dict[str, list[BrandFact]] = {}
        for fact in facts:
            by_category.setdefault(fact.category, []).append(fact)
            assert fact.source_url.startswith("https://northwind.example/")
            assert fact.observed_at is not None
            assert fact.state in {"extracted", "needs_review"}
        assert any(fact.statement == "Northwind Freight" for fact in by_category["company_name"])
        assert any("refrigerated and dry trucks" in fact.statement for fact in by_category["description"])
        services = {fact.statement for fact in by_category["service"]}
        assert {"Refrigerated trucking", "Same-day dry freight"} <= services
        assert "Our services" not in services
        assert any("12 Station Road, Pune, IN" in fact.statement for fact in by_category["location"])
        contacts = {fact.value for fact in by_category["contact"]}
        assert {"hello@northwind.example", "+912055550100", "+91 20 5555 0100"} <= contacts
        assert any("instagram.com/northwindfreight" in fact.value for fact in by_category["social_profile"])
        claims = by_category["claim"]
        assert {fact.statement for fact in claims} >= {"Trusted by 120 manufacturers since 2014.", "We are the leading cold-chain carrier in Pune."}
        assert all(fact.state == "needs_review" for fact in claims)
        colors = {fact.value for fact in by_category["color"]}
        assert "#145aa0" in colors
        all_text = " ".join(pages.values())
        for fact in facts:
            if fact.category in {"company_name", "description", "service", "claim"}:
                assert fact.statement.rstrip(".") in all_text or fact.statement in all_text, fact.statement
        profile = db.scalar(select(BrandProfile).where(BrandProfile.tenant_id == admin.tenant_id))
        assert profile.company_name == "Northwind Freight"
        assert profile.logo_asset_id is not None
        view = brand_service.brand_view(db, admin.tenant_id)
        assert view["profile"]["palette"]
        assert view["profile"]["voice"]["sentences"] > 0
        assert brand_service.approved_facts(db, admin.tenant_id) == []
        leading = next(fact for fact in claims if "leading" in fact.statement)
        trusted = next(fact for fact in claims if "Trusted" in fact.statement)
        brand_service.review_facts(db, tenant_id=admin.tenant_id, actor_id=admin.id, fact_ids=[trusted.id], decision="approve", note="On the services page.")
        brand_service.review_facts(db, tenant_id=admin.tenant_id, actor_id=admin.id, fact_ids=[leading.id], decision="reject", note="No ranking source.")
        approved = brand_service.approved_facts(db, admin.tenant_id)
        assert [fact.id for fact in approved] == [trusted.id]
        again = brand_service.analyze_website(db, tenant_id=admin.tenant_id, actor_id=admin.id, website_url="https://northwind.example/", fetcher=site_fetcher(pages, [], logo_png()))
        assert again["status"] == "analyzed"
        db.refresh(trusted)
        db.refresh(leading)
        assert trusted.state == "approved" and leading.state == "rejected"
        other = user(db, "admin@northline.demo")
        assert brand_service.brand_view(db, other.tenant_id)["facts"] == []
        assert brand_service.review_facts(db, tenant_id=other.tenant_id, actor_id=other.id, fact_ids=[trusted.id], decision="reject")["updated"] == 0
    finally:
        db.rollback()
        db.close()


def test_unreadable_home_page_records_failure_without_facts(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db, "admin@northline.demo")
        result = brand_service.analyze_website(db, tenant_id=admin.tenant_id, actor_id=admin.id, website_url="https://down.example/", fetcher=site_fetcher({}, []))
        assert result["status"] == "failed"
        assert db.scalars(select(BrandFact).where(BrandFact.tenant_id == admin.tenant_id)).all() == []
        source = db.scalar(select(BrandSource).where(BrandSource.tenant_id == admin.tenant_id, BrandSource.url == "https://down.example/"))
        assert source is not None and source.status == "http_error"
    finally:
        db.rollback()
        db.close()


def test_private_addresses_are_refused_before_a_request() -> None:
    assert brand_service.fetch_public("http://127.0.0.1/").status == "blocked_private"
    assert brand_service.fetch_public("http://10.0.0.5/admin").status == "blocked_private"


def test_extraction_units() -> None:
    page = extract_page("https://example.test/services", "<h2>Plan audits</h2><p>Our plan audits cover 40 sites a year.</p><h2>Why choose us?</h2>")
    assert any(finding.category == "service" and finding.statement == "Plan audits" for finding in page.findings)
    assert not any(finding.statement == "Why choose us?" for finding in page.findings)
    assert any(finding.category == "claim" and "40 sites" in finding.statement for finding in page.findings)
    assert robots_disallows("User-agent: *\nDisallow: /private\nAllow: /private/public\n", "/private/x")
    assert not robots_disallows("User-agent: *\nDisallow: /private\nAllow: /private/public\n", "/private/public/page")
    assert not robots_disallows("", "/anything")
    phrases = keyphrases(["Cold chain freight. Cold chain trucks. Cold chain routes for pharma."])
    assert phrases and phrases[0][0] in {"cold chain", "cold", "chain"}
    assert voice_profile([])["sentences"] == 0


def test_brand_api_permissions(client: TestClient) -> None:
    reader = login(client, "readonly@agrayian.demo")
    assert client.get("/api/v1/social-growth/brand", headers=reader).status_code == 200
    assert client.post("/api/v1/social-growth/brand/analyze", json={"website_url": "https://northwind.example"}, headers=reader).status_code == 403
    assert client.post("/api/v1/social-growth/brand/facts/review", json={"fact_ids": ["00000000-0000-0000-0000-000000000000"], "decision": "approve"}, headers=reader).status_code == 403
    seller = login(client, "seller@agrayian.demo")
    assert client.get("/api/v1/social-growth/overview", headers=seller).status_code == 200
    assert client.post("/api/v1/social-growth/brand/facts/review", json={"fact_ids": ["00000000-0000-0000-0000-000000000000"], "decision": "approve"}, headers=seller).status_code == 403
