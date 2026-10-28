"""One product context for organic copy and the inbound acknowledgement.

Facts come from the seller profile, the selected catalogue row, and the
operating plan's frozen snapshot. Nothing here invents a second SKU, a
combined price, or a benefit that was not stored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.content import SellerProfile
from app.models.crm import Lead
from app.models.lifecycle import Product
from app.models.operating_plan import CreativeVersion, OperatingPlan

CONTEXT_VERSION = "product-context-v1"
BRAND_INSTRUCTIONS = (
    "Use only the stored facts in this context.",
    "Do not invent customers, awards, discounts, or buyer research.",
    "Do not mention another product's price or a combined offer.",
    "Do not use the internal SKU as the customer-facing product name.",
)
_SELLS_THE = re.compile(r"sells the ([^.]+)\.", re.IGNORECASE)
_HEADCOUNT = (
    "under 200 employees",
    "50 to 200 employees",
    "200 to 1,000 employees",
    "200 to 1000 employees",
)


@dataclass(frozen=True)
class ProductContext:
    company_name: str
    customer_facing_name: str
    sku: str
    audience: str
    headcount_tier: str
    description: str
    benefits: tuple[str, ...]
    supporting_facts: tuple[str, ...]
    price_amount: str
    currency: str
    pricing_basis: str
    brand_instructions: tuple[str, ...]
    sources: dict
    missing: tuple[str, ...]

    def offer_label(self) -> str:
        """The tier and price, kept apart from the customer-facing product name."""
        catalogue = str(self.sources.get("catalogue_name") or "").strip()
        parts: list[str] = []
        if catalogue and catalogue.casefold() != self.customer_facing_name.casefold():
            parts.append(catalogue)
        if self.headcount_tier and self.headcount_tier.casefold() not in " ".join(parts).casefold():
            parts.append(self.headcount_tier)
        price = self.price_line().rstrip(".")
        if price:
            parts.append(price)
        return " · ".join(parts)

    def price_line(self) -> str:
        if "price" in self.missing or not self.price_amount or not self.currency:
            return ""
        label = "Setup price" if self.pricing_basis == "one_time" else "Monthly price" if self.pricing_basis == "subscription" else "Price"
        tier = f" for companies {self.headcount_tier}" if self.headcount_tier else ""
        return f"{label}: {self.currency} {self.price_amount}{tier}."

    def as_dict(self) -> dict:
        payload = {
            "version": CONTEXT_VERSION,
            "company_name": self.company_name,
            "customer_facing_name": self.customer_facing_name,
            "sku": self.sku,
            "audience": self.audience,
            "headcount_tier": self.headcount_tier,
            "description": self.description,
            "benefits": list(self.benefits),
            "supporting_facts": list(self.supporting_facts),
            "price_amount": self.price_amount,
            "currency": self.currency,
            "pricing_basis": self.pricing_basis,
            "price_line": self.price_line(),
            "brand_instructions": list(self.brand_instructions),
            "sources": self.sources,
            "missing": list(self.missing),
        }
        return payload


def is_tier_label(name: str, sku: str = "") -> bool:
    text = name.strip().casefold()
    if not text:
        return True
    if sku and text == sku.strip().casefold():
        return True
    if text.startswith("one-time setup"):
        return True
    return "employees" in text and ("under " in text or " to " in text)


def customer_facing_from_profile(profile: SellerProfile | None) -> str:
    summary = profile.summary if profile is not None else ""
    match = _SELLS_THE.search(summary or "")
    if match is None:
        return ""
    name = match.group(1).strip()
    if not name or is_tier_label(name):
        return ""
    return name


def context_from_mapping(data: dict) -> ProductContext:
    benefits = data.get("benefits") if isinstance(data.get("benefits"), list) else []
    facts = data.get("supporting_facts") if isinstance(data.get("supporting_facts"), list) else []
    instructions = data.get("brand_instructions") if isinstance(data.get("brand_instructions"), list) else list(BRAND_INSTRUCTIONS)
    missing = data.get("missing") if isinstance(data.get("missing"), list) else []
    sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
    return ProductContext(
        company_name=str(data.get("company_name") or "").strip(),
        customer_facing_name=str(data.get("customer_facing_name") or "").strip(),
        sku=str(data.get("sku") or "").strip(),
        audience=str(data.get("audience") or "").strip(),
        headcount_tier=str(data.get("headcount_tier") or "").strip(),
        description=str(data.get("description") or "").strip(),
        benefits=tuple(str(item).strip() for item in benefits if str(item).strip()),
        supporting_facts=tuple(str(item).strip() for item in facts if str(item).strip()),
        price_amount=str(data.get("price_amount") or "").strip(),
        currency=str(data.get("currency") or "").strip(),
        pricing_basis=str(data.get("pricing_basis") or "").strip(),
        brand_instructions=tuple(str(item).strip() for item in instructions if str(item).strip()),
        sources=sources,
        missing=tuple(str(item) for item in missing),
    )


def empty_product_context() -> ProductContext:
    return _assemble(profile=None, product=None, snapshot={}, audience="", plan_id="")


def context_for_catalog(profile: SellerProfile | None, product: Product, audience: str = "") -> ProductContext:
    return _assemble(
        profile=profile,
        product=product,
        snapshot={},
        audience=audience or (profile.audience.strip() if profile is not None else ""),
        plan_id="",
    )


def build_product_context(
    db: Session,
    tenant_id: UUID,
    *,
    plan: OperatingPlan | None = None,
    product: Product | None = None,
    snapshot: dict | None = None,
) -> ProductContext:
    frozen = snapshot if snapshot is not None else _load(plan.context_snapshot) if plan is not None else {}
    selected = product
    if selected is None and plan is not None and plan.product_id is not None:
        row = db.get(Product, plan.product_id)
        if row is not None and row.tenant_id == tenant_id and row.deleted_at is None:
            selected = row
    profile = db.scalar(
        select(SellerProfile).where(SellerProfile.tenant_id == tenant_id, SellerProfile.deleted_at.is_(None))
    )
    audience = ""
    if plan is not None:
        audience = str(frozen.get("customer_audience") or frozen.get("audience") or plan.audience or "").strip()
    return _assemble(
        profile=profile,
        product=selected,
        snapshot=frozen,
        audience=audience,
        plan_id=str(plan.id) if plan is not None else "",
    )


def context_for_lead(db: Session, tenant_id: UUID, lead: Lead) -> ProductContext:
    if lead.creative_version_id is not None:
        version = db.get(CreativeVersion, lead.creative_version_id)
        if version is not None and version.tenant_id == tenant_id and version.deleted_at is None and version.context_json.strip():
            try:
                loaded = json.loads(version.context_json)
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict) and loaded.get("version") == CONTEXT_VERSION:
                return context_from_mapping(loaded)
    plan = None
    if lead.operating_plan_id is not None:
        candidate = db.get(OperatingPlan, lead.operating_plan_id)
        if candidate is not None and candidate.tenant_id == tenant_id and candidate.deleted_at is None:
            plan = candidate
    if plan is None:
        return _assemble(profile=None, product=None, snapshot={}, audience="", plan_id="")
    return build_product_context(db, tenant_id, plan=plan)


def _assemble(
    *,
    profile: SellerProfile | None,
    product: Product | None,
    snapshot: dict,
    audience: str,
    plan_id: str,
) -> ProductContext:
    sku = str(snapshot.get("sku") or (product.sku if product is not None else "") or "").strip()
    catalogue_name = str(snapshot.get("catalogue_name") or (product.name if product is not None else "") or "").strip()
    explicit = str(snapshot.get("customer_facing_name") or "").strip()
    snapshot_name = str(snapshot.get("name") or "").strip()
    if explicit and not is_tier_label(explicit, sku):
        facing = explicit
    elif snapshot_name and not is_tier_label(snapshot_name, sku):
        facing = snapshot_name
    elif catalogue_name and not is_tier_label(catalogue_name, sku):
        facing = catalogue_name
    else:
        facing = customer_facing_from_profile(profile)

    description = str(snapshot.get("description") or (product.description if product is not None else "") or "").strip()
    company = profile.company_name.strip() if profile is not None and profile.company_name else ""
    basis = str(snapshot.get("kind") or (product.kind if product is not None else "") or "").strip()
    currency = str(snapshot.get("currency") or (product.currency if product is not None else "") or "").strip()
    amount = _amount(snapshot.get("list_price") if snapshot.get("list_price") not in {None, ""} else (product.list_price if product is not None else None))
    headcount = _headcount(description, catalogue_name, str(snapshot.get("audience") or ""), audience)
    benefits = _strings(snapshot.get("benefits"))
    facts: list[str] = []
    seller = str(snapshot.get("seller_summary") or "").strip()
    if not seller and profile is not None:
        seller = profile.summary.strip()
    if seller and seller != description:
        facts.append(seller)
    proof = profile.proof.strip() if profile is not None and profile.proof else ""
    if proof and proof not in facts and proof != description:
        facts.append(proof)

    missing: list[str] = []
    if not company:
        missing.append("company_name")
    if not facing:
        missing.append("customer_facing_name")
    if not description:
        missing.append("description")
    if not benefits:
        missing.append("benefits")
    if not facts:
        missing.append("supporting_facts")
    if not amount or not currency:
        missing.append("price")
    if not basis:
        missing.append("pricing_basis")
    if not headcount:
        missing.append("headcount_tier")
    if not audience:
        missing.append("audience")

    sources = {
        "version": CONTEXT_VERSION,
        "product_id": str(snapshot.get("product_id") or (product.id if product is not None else "") or ""),
        "plan_id": plan_id,
        "sku": sku,
        "catalogue_name": catalogue_name,
    }
    return ProductContext(
        company_name=company,
        customer_facing_name=facing,
        sku=sku,
        audience=audience,
        headcount_tier=headcount,
        description=description,
        benefits=tuple(benefits),
        supporting_facts=tuple(facts),
        price_amount=amount,
        currency=currency,
        pricing_basis=basis,
        brand_instructions=BRAND_INSTRUCTIONS,
        sources=sources,
        missing=tuple(missing),
    )


def _load(raw: str) -> dict:
    try:
        loaded = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _amount(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ""
    if number <= 0:
        return ""
    if number == number.to_integral():
        return f"{int(number):,}"
    return f"{number.quantize(Decimal('0.01')):,.2f}"


def _headcount(*parts: str) -> str:
    blob = " ".join(part for part in parts if part).casefold()
    for phrase in _HEADCOUNT:
        if phrase.casefold() in blob:
            return phrase
    return ""
