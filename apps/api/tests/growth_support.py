"""Shared fakes for the Social Growth tests. Nothing here reaches a network."""

from __future__ import annotations

import json
import re
from io import BytesIO
from uuid import UUID

import httpx
from PIL import Image, ImageDraw
from sqlalchemy import select

from app.models.funnel import PublicFormKey
from app.models.growth import BrandFact, GrowthAccount
from app.models.identity import FeatureFlag, Tenant, User
from app.models.operating_plan import DemoScope
from app.services.growth import accounts as account_service
from app.services.growth import brand as brand_service
from app.services.growth import strategy as strategy_service
from app.services.growth.brand import FetchResult
from app.services.public_forms import create_form_key


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.content = json.dumps(self._payload).encode()

    def json(self) -> dict:
        return self._payload


def ok(payload: dict) -> FakeResponse:
    return FakeResponse(200, payload)


def graph_error(code: int, message: str, status: int = 400, subcode: int | None = None) -> FakeResponse:
    error: dict = {"code": code, "message": message, "type": "OAuthException"}
    if subcode is not None:
        error["error_subcode"] = subcode
    return FakeResponse(status, {"error": error})


class FakeGraph:
    """httpx-shaped. Routes are (method, regex on the path after the version, handler).

    A handler is a list of responses consumed in order, a callable taking the
    request, or an exception class/instance to raise.
    """

    def __init__(self) -> None:
        self.routes: list[tuple[str, re.Pattern, object]] = []
        self.calls: list[dict] = []
        self.closed = False

    def on(self, method: str, pattern: str, handler) -> FakeGraph:
        self.routes.append((method.upper(), re.compile(pattern), handler))
        return self

    def count(self, method: str, pattern: str) -> int:
        regex = re.compile(pattern)
        return sum(1 for call in self.calls if call["method"] == method.upper() and regex.search(call["path"]))

    def _dispatch(self, method: str, url: str, **kwargs):
        path = re.sub(r"^https://[^/]+/(?:video-upload/)?v\d+\.\d+/", "", url)
        call = {"method": method, "url": url, "path": path, **kwargs}
        self.calls.append(call)
        for route_method, pattern, handler in self.routes:
            if route_method == method and pattern.search(path):
                if isinstance(handler, list):
                    if not handler:
                        raise AssertionError(f"No scripted response left for {method} {path}")
                    item = handler.pop(0) if len(handler) > 1 else handler[0]
                    if isinstance(item, Exception):
                        raise item
                    return item
                if isinstance(handler, Exception):
                    raise handler
                return handler(call)
        raise AssertionError(f"Unexpected Graph call {method} {path}")

    def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        return self._dispatch("GET", url, params=params or {}, headers=headers or {})

    def post(self, url: str, data: dict | None = None, files: dict | None = None, headers: dict | None = None, content: bytes | None = None, json: dict | None = None):
        return self._dispatch("POST", url, data=data or {}, files=files or {}, headers=headers or {}, content=content, json=json)

    def close(self) -> None:
        self.closed = True


def network_error() -> httpx.ConnectError:
    return httpx.ConnectError("scripted network failure")


def user(db, email: str = "admin@agrayian.demo") -> User:
    row = db.scalar(select(User).where(User.email == email))
    assert row is not None
    return row


def set_mode(db, tenant_id: UUID, mode: str) -> None:
    tenant = db.get(Tenant, tenant_id)
    tenant.operating_mode = mode
    db.flush()


def enable_growth(db, tenant_id: UUID, enabled: bool = True) -> None:
    row = db.scalar(select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id, FeatureFlag.key == "ENABLE_SOCIAL_GROWTH"))
    if row is None:
        row = FeatureFlag(tenant_id=tenant_id, key="ENABLE_SOCIAL_GROWTH", enabled=enabled, description="test")
        db.add(row)
    row.enabled = enabled
    db.flush()


def close_scopes(db, tenant_id: UUID) -> None:
    for row in db.scalars(select(DemoScope).where(DemoScope.tenant_id == tenant_id, DemoScope.status.in_(["prepared", "authorized"]))).all():
        row.status = "closed"
    db.flush()


def logo_png(color=(20, 90, 160)) -> bytes:
    image = Image.new("RGBA", (240, 120), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((10, 10, 230, 110), radius=20, fill=(*color, 255))
    draw.ellipse((150, 30, 210, 90), fill=(242, 181, 68, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


HOME = """<!doctype html><html><head><title>Northwind Freight | Pune freight</title>
<meta name="description" content="Northwind Freight runs refrigerated and dry trucks between Pune and Mumbai.">
<meta name="theme-color" content="#145aa0">
<meta property="og:site_name" content="Northwind Freight">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Northwind Freight",
"description":"Northwind Freight runs refrigerated and dry trucks between Pune and Mumbai.","logo":"https://northwind.example/logo.png",
"sameAs":["https://www.instagram.com/northwindfreight","https://www.facebook.com/northwindfreight"],"telephone":"+91 20 5555 0100",
"address":{"@type":"PostalAddress","streetAddress":"12 Station Road","addressLocality":"Pune","addressCountry":"IN"}}</script>
<style>.btn{background:#145aa0}.cta{color:#145aa0}.hero{background:#0b2f55}.hero2{border-color:#0b2f55}</style>
</head><body><header><img class="site-logo" src="/logo.png" alt="Northwind logo"></header>
<h1>Freight you can track</h1><p>We move goods for manufacturers in Pune and Mumbai. You see every load on a live map.</p>
<a href="/about">About</a> <a href="/services">Services</a> <a href="/contact">Contact</a> <a href="/private/admin">Staff</a>
<a href="https://www.linkedin.com/company/northwind-freight">LinkedIn</a></body></html>"""
SERVICES = """<html><head><title>Services</title></head><body><h1>Our services</h1>
<h2>Refrigerated trucking</h2><p>Temperature-controlled trucks for food and pharma loads.</p>
<h2>Same-day dry freight</h2><p>Dry freight between Pune and Mumbai on the same day.</p>
<p>Trusted by 120 manufacturers since 2014.</p><p>We are the leading cold-chain carrier in Pune.</p></body></html>"""
ABOUT = "<html><head><title>About</title></head><body><h1>About Northwind</h1><p>Northwind Freight was founded in Pune. Our drivers are trained for food safety. You get a named dispatcher for every account.</p></body></html>"
CONTACT = '<html><head><title>Contact</title></head><body><a href="mailto:hello@northwind.example">Email us</a> <a href="tel:+912055550100">Call</a></body></html>'
ROBOTS = "User-agent: *\nDisallow: /private\n"


def fake_site(base: str = "https://northwind.example") -> tuple[dict[str, str], list[str]]:
    pages = {
        f"{base}/": HOME,
        f"{base}/services": SERVICES,
        f"{base}/about": ABOUT,
        f"{base}/contact": CONTACT,
        f"{base}/robots.txt": ROBOTS,
    }
    return pages, []


def site_fetcher(pages: dict[str, str], requested: list[str], logo: bytes | None = None):
    def fetch(url: str, binary: bool = False) -> FetchResult:
        requested.append(url)
        if binary:
            if url.endswith("/logo.png") and logo is not None:
                return FetchResult(url, "fetched", 200, "image/png", data=logo, final_url=url)
            return FetchResult(url, "http_error", 404, final_url=url)
        if url in pages:
            content_type = "text/plain" if url.endswith("robots.txt") else "text/html"
            return FetchResult(url, "fetched", 200, content_type, text=pages[url], final_url=url)
        return FetchResult(url, "http_error", 404, final_url=url)

    return fetch


def approved_brand(db, tenant_id: UUID, actor: User) -> dict[str, BrandFact]:
    """Operator-recorded, approved facts with sources. Returns them by short name."""
    facts = {}
    rows = {
        "description": ("description", "Northwind Freight runs refrigerated and dry trucks between Pune and Mumbai.", "https://northwind.example/"),
        "cold": ("service", "Refrigerated trucking for food and pharma loads.", "https://northwind.example/services"),
        "dry": ("service", "Same-day dry freight between Pune and Mumbai.", "https://northwind.example/services"),
        "tracking": ("product", "Every load is visible on a live map.", "https://northwind.example/"),
        "claim": ("claim", "Trusted by 120 manufacturers since 2014.", "https://northwind.example/services"),
        "theme": ("theme", "cold chain", "https://northwind.example/services"),
        "color": ("color", "Brand colour #145aa0 is declared in the theme-color tag.", "https://northwind.example/"),
    }
    for key, (category, statement, source) in rows.items():
        result = brand_service.add_operator_fact(db, tenant_id=tenant_id, actor_id=actor.id, category=category, statement=statement, source_url=source, evidence=statement, approve=True)
        fact = db.get(BrandFact, UUID(result["fact"]["id"]))
        if category == "color":
            fact.value = "#145aa0"
        facts[key] = fact
    db.flush()
    return facts


def form(db, tenant_id: UUID, actor: User) -> PublicFormKey:
    row, _raw = create_form_key(db, tenant_id=tenant_id, actor_id=actor.id, name=f"growth-{tenant_id.hex[:6]}")
    db.flush()
    return row


def live_account(db, tenant_id: UUID, actor: User, platform: str, external_id: str, page_id: str = "") -> GrowthAccount:
    account = account_service.connect_account(
        db,
        tenant_id=tenant_id,
        actor_id=actor.id,
        platform=platform,
        external_id=external_id,
        access_token="fixture-page-token-0000",
        page_id=page_id or ("" if platform == "facebook" else "1000000001"),
        name=f"Northwind {platform}",
        timezone="Asia/Kolkata",
    )
    account.status = "connected"
    account.capabilities = json.dumps({"publish": True, "insights": True, "checked": True})
    db.flush()
    return account


def approved_strategy(db, tenant_id: UUID, actor: User, facts: dict[str, BrandFact], accounts: list[GrowthAccount], destination: PublicFormKey, *, formats: dict[str, dict[str, int]] | None = None, auto_schedule: bool = False, review_terms: list[str] | None = None):
    cadence = {}
    for account in accounts:
        cadence[str(account.id)] = {"formats": (formats or {}).get(account.platform) or ({"image": 2, "carousel": 1} if account.platform == "instagram" else {"image": 2})}
    payload = {
        "objective": "More enquiries from manufacturers in Pune.",
        "optimization_metric": "reach",
        "pillars": [
            {"key": "offer", "name": "What we move", "fact_ids": [str(facts["cold"].id), str(facts["dry"].id)]},
            {"key": "proof", "name": "Proof", "fact_ids": [str(facts["claim"].id), str(facts["tracking"].id)]},
        ],
        "audiences": ["Plant managers in Pune"],
        "cadence": cadence,
        "call_to_action": "Ask for a route quote",
        "destination_kind": "form",
        "destination_form_key_id": str(destination.id),
        "auto_create": True,
        "auto_schedule": auto_schedule,
        "horizon_days": 30,
    }
    if review_terms is not None:
        payload["review_terms"] = review_terms
    draft = strategy_service.save_strategy(db, tenant_id=tenant_id, actor_id=actor.id, payload=payload)
    return strategy_service.approve_strategy(db, tenant_id=tenant_id, actor_id=actor.id, strategy_id=draft.id)
