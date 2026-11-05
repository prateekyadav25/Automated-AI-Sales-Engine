"""Creative production: captions from approved facts, branded assets, quality gates, review.

The model is mock or scripted. Images are rendered with Pillow. Reels use the
local FFmpeg binary and are skipped with a reason when it is absent.
"""

import json
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.ai.providers import CompletionResult, LLMProvider
from app.db.session import get_session
from app.models.ai import AIApproval, ModelUsage
from app.models.growth import BrandFact, GrowthCalendarItem
from app.services.content_calendar import solid_png
from app.services.growth import accounts as account_service
from app.services.growth import brand as brand_service
from app.services.growth import creative as creative_service
from app.services.growth import governance, planner
from app.services.growth.assets import asset_bytes, creative_assets
from app.services.growth.quality import caption_problems, check_caption, check_image
from app.services.growth.render import RenderUnavailable, jpeg_bytes
from app.services.growth.video import VideoUnavailable, check_reel, tools
from tests.growth_support import approved_brand, approved_strategy, form, user


class ScriptedModel(LLMProvider):
    def __init__(self, caption: str) -> None:
        self.caption = caption
        self.calls = 0

    def complete(self, prompt: str, *, system: str, model: str | None = None, reasoning: bool = False) -> CompletionResult:
        _ = (system, model, reasoning)
        self.calls += 1
        facts = json.loads(prompt)["facts"]
        body = json.dumps({"caption": self.caption, "hashtags": ["ColdChain", "bad tag!"], "fact_ids": [facts[0]["id"], "not-a-fact"]})
        return CompletionResult(text=f"```json\n{body}\n```", provider="fixture-llm", model="fixture-model-1", input_tokens=120, output_tokens=60, latency_ms=5, is_mock=False, estimated_cost=0.0)


def _setup(db, *, formats=None, auto_schedule=False, review_terms=None, extra_facts=None):
    admin = user(db)
    facts = approved_brand(db, admin.tenant_id, admin)
    for key, (category, statement) in (extra_facts or {}).items():
        result = brand_service.add_operator_fact(db, tenant_id=admin.tenant_id, actor_id=admin.id, category=category, statement=statement, source_url="https://northwind.example/", evidence=statement, approve=True)
        facts[key] = db.get(BrandFact, UUID(result["fact"]["id"]))
    account = account_service.create_fixture_account(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform="instagram", name="Northwind IG")
    strategy = approved_strategy(db, admin.tenant_id, admin, facts, [account], form(db, admin.tenant_id, admin), formats=formats, auto_schedule=auto_schedule, review_terms=review_terms)
    planner.plan_rolling_calendar(db, tenant_id=admin.tenant_id, actor_id=admin.id)
    items = list(db.scalars(select(GrowthCalendarItem).where(GrowthCalendarItem.tenant_id == admin.tenant_id, GrowthCalendarItem.account_id == account.id).order_by(GrowthCalendarItem.planned_for)).all())
    return admin, facts, account, strategy, items


def test_image_creative_uses_only_approved_facts_and_passes_quality(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin, facts, account, _strategy, items = _setup(db)
        item = next(row for row in items if row.format == "image")
        view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        assert view["generation"] == "deterministic"
        brief_facts = [fact["statement"] for fact in planner.loads(item.brief_json, {})["facts"]]
        assert brief_facts[0] in view["caption"]
        assert "/api/v1/public/r/" in view["caption"] and view["link_url"] in view["caption"]
        assert view["claims"]["unsupported"] == []
        assert view["status"] == "draft" and view["quality_state"] == "passed", view["review_reasons"]
        assets = view["assets"]
        assert len(assets) == 1 and assets[0]["mime"] == "image/jpeg"
        assert (assets[0]["width"], assets[0]["height"]) == (1080, 1350)
        assert assets[0]["commercial"] is True and assets[0]["provenance"] == "rendered"
        assert assets[0]["public_media_ready"] is False
        stored = asset_bytes(creative_assets(db, admin.tenant_id, UUID(view["id"]))[0])
        with Image.open(BytesIO(stored)) as image:
            assert image.format == "JPEG" and image.size == (1080, 1350)
        db.refresh(item)
        assert item.status == "creative_ready"
        again = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        assert again["id"] == view["id"]
        approved = creative_service.review_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, creative_id=UUID(view["id"]), decision="approve", note="")
        assert approved["status"] == "approved"
        scheduled = creative_service.schedule_item(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        assert scheduled["authorization"] == "approval"
        request = db.scalar(select(AIApproval).where(AIApproval.tenant_id == admin.tenant_id, AIApproval.id == UUID(scheduled["approval_id"])))
        assert request.action_type == "social.growth_publish" and request.status == "pending"
        assert json.loads(request.payload_json)["content_hash"] == approved["content_hash"]
        other = user(db, "admin@northline.demo")
        with pytest.raises(HTTPException) as hidden:
            creative_service.owned_creative(db, other.tenant_id, UUID(view["id"]))
        assert hidden.value.status_code == 404
    finally:
        db.rollback()
        db.close()


def test_carousel_slides_are_checked_together(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin, _facts, _account, _strategy, items = _setup(db, formats={"instagram": {"carousel": 2}})
        item = items[0]
        view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        slides = [asset for asset in view["assets"] if asset["role"] == "slide"]
        assert 3 <= len(slides) <= 5
        assert [slide["position"] for slide in slides] == list(range(len(slides)))
        assert all((slide["width"], slide["height"]) == (1080, 1350) and slide["quality_state"] == "passed" for slide in slides)
        carousel = view["quality"]["assets"][0]
        assert carousel["state"] == "passed" and carousel["checks"][0]["name"] == "slide_count"
        assert view["quality_state"] == "passed"
    finally:
        db.rollback()
        db.close()


def test_reel_is_a_validated_vertical_mp4(client: TestClient) -> None:
    _ = client
    try:
        tools()
    except VideoUnavailable as exc:
        pytest.skip(f"FFmpeg is not installed here: {exc}")
    db = get_session()
    try:
        admin, _facts, _account, _strategy, items = _setup(db, formats={"instagram": {"reel": 1}})
        view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=items[0].id)
        reel = next(asset for asset in view["assets"] if asset["role"] == "reel")
        cover = next(asset for asset in view["assets"] if asset["role"] == "cover")
        assert reel["mime"] == "video/mp4" and (reel["width"], reel["height"]) == (1080, 1920)
        assert reel["quality_state"] == "passed" and 3000 <= reel["duration_ms"] <= 90000
        assert {check["name"] for check in reel["quality"]["checks"] if check["ok"]} >= {"video_codec", "pixel_format", "dimensions_9_16", "faststart", "audio_codec"}
        assert (cover["width"], cover["height"]) == (1080, 1920)
        stored = asset_bytes(next(asset for asset in creative_assets(db, admin.tenant_id, UUID(view["id"])) if asset.role == "reel"))
        assert check_reel(stored, max_seconds=90)["state"] == "passed"
        assert view["quality_state"] == "passed"
    finally:
        db.rollback()
        db.close()


def test_unsupported_claims_and_sensitive_terms_go_to_a_person(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin, _facts, _account, _strategy, items = _setup(db)
        item = next(row for row in items if row.format == "image")
        model = ScriptedModel("Northwind is the #1 carrier in India with 300% faster delivery. Ask for a route quote.")
        view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id, llm=model)
        assert model.calls == 1
        assert view["generation"] == "model" and view["model_id"] == "fixture-model-1"
        assert view["hashtags"] == ["ColdChain", "BadTag"]
        assert "not-a-fact" not in view["fact_ids"]
        assert {"#1", "300%"} <= set(view["claims"]["unsupported"])
        assert view["status"] == "needs_review"
        assert any("Unsupported claim" in reason for reason in view["review_reasons"])
        assert db.scalar(select(ModelUsage).where(ModelUsage.tenant_id == admin.tenant_id, ModelUsage.agent == "social_growth_copywriter")) is not None
        creative_id = UUID(view["id"])
        with pytest.raises(HTTPException) as needs_note:
            creative_service.review_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, creative_id=creative_id, decision="approve", note="ok")
        assert needs_note.value.status_code == 422
        rejected = creative_service.review_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, creative_id=creative_id, decision="reject", note="No source for the ranking.")
        assert rejected["status"] == "rejected"
        db.refresh(item)
        assert item.status == "planned"
        revised = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id, force=True)
        assert revised["version"] == 2 and revised["generation"] == "deterministic"
        edited = creative_service.revise_caption(db, tenant_id=admin.tenant_id, actor_id=admin.id, creative_id=UUID(revised["id"]), caption="The best freight partner in Pune. Ask for a route quote.", hashtags=["ColdChain"])
        assert edited["version"] == 3 and edited["generation"] == "operator"
        assert "best" in edited["claims"]["sensitive"] and edited["status"] == "needs_review"
        assert len(edited["assets"]) == len(revised["assets"])
    finally:
        db.rollback()
        db.close()


def test_quality_gates_refuse_placeholders_fixtures_and_missing_fonts(client: TestClient, monkeypatch) -> None:
    _ = client
    placeholder = jpeg_bytes(Image.open(BytesIO(solid_png(1080, 1350))))
    report = check_image(placeholder, platform="instagram", expected=(1080, 1350), provenance="rendered", layout=None)
    assert report["state"] == "failed"
    assert next(check for check in report["checks"] if check["name"] == "not_placeholder")["ok"] is False
    fixture = check_image(placeholder, platform="instagram", expected=(1080, 1350), provenance="fixture", layout=None)
    assert next(check for check in fixture["checks"] if check["name"] == "provenance")["ok"] is False
    png = check_image(solid_png(1080, 1350), platform="instagram", expected=(1080, 1350), provenance="rendered", layout=None)
    assert next(check for check in png["checks"] if check["name"] == "format")["ok"] is False

    def no_fonts():
        raise RenderUnavailable("NOT_CONFIGURED. No TrueType font was found.")

    monkeypatch.setattr("app.services.growth.creative.resolve_fonts", no_fonts)
    db = get_session()
    try:
        admin, _facts, _account, _strategy, items = _setup(db)
        item = next(row for row in items if row.format == "image")
        view = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=item.id)
        assert view["assets"] == []
        assert view["quality_state"] == "not_configured" and view["status"] == "needs_review"
        assert any("NOT_CONFIGURED" in reason for reason in view["review_reasons"])
        with pytest.raises(HTTPException) as refused:
            creative_service.review_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, creative_id=UUID(view["id"]), decision="approve", note="Looks fine to me.")
        assert refused.value.status_code == 409
    finally:
        db.rollback()
        db.close()


def test_placeholder_check_ignores_link_tokens_and_longer_words() -> None:
    link = "http://localhost:8000/api/v1/public/r/aXxXb-todo_Q1"
    clean = check_caption(f"Ask Mastodon readers for a route quote. Link: {link}", [], platform="instagram")
    assert clean["state"] == "passed"
    assert caption_problems("TODO: add the offer.") == ["todo"]
    assert caption_problems("Lorem  ipsum dolor") == ["lorem ipsum"]
    assert caption_problems("Call XXX today") == ["xxx"]
    assert caption_problems("Book at https://example.com/{{slug}}") == ["{{", "}}"]
    assert caption_problems("[Insert offer] here") == ["[insert"]


def test_policy_approval_needs_auto_schedule_a_grant_and_no_review_reason(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin, _facts, account, _strategy, items = _setup(db, auto_schedule=True, extra_facts={"promise": ("claim", "On-time delivery guarantee on every route.")})
        first = next(row for row in items if row.format == "image")
        without_grant = creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=first.id)
        assert without_grant["status"] in {"draft", "needs_review"}
        governance.create_grant(db, tenant_id=admin.tenant_id, actor_id=admin.id, platform=account.platform, volume_cap=2, days=7)
        results = [creative_service.produce_creative(db, tenant_id=admin.tenant_id, actor_id=admin.id, item_id=row.id) for row in items[1:6] if row.format == "image"]
        auto = [view for view in results if view["status"] == "approved"]
        held = [view for view in results if view["status"] == "needs_review"]
        for view in auto:
            assert "Approved by policy" in view["review_note"]
            assert db.get(GrowthCalendarItem, UUID(view["item_id"])).status == "scheduled"
        for view in held:
            assert view["claims"]["sensitive"] or view["review_reasons"]
        assert auto, [view["review_reasons"] for view in results]
    finally:
        db.rollback()
        db.close()
