from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.acquisition import DedupeReview, InboundCapture
from app.models.crm import Account, Contact, Lead
from app.models.funnel import PaidAd
from app.models.growth import GrowthTrackingLink
from app.models.lifecycle import Campaign
from app.models.operating_plan import CreativeVersion, OperatingPlan
from app.services.assessment import FREE_MAIL_DOMAINS
from app.services.audit import emit_event
from app.services.growth.attribution import link_for_capture, strategy_plan_for_link
from app.services.scoring import score_lead


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _domain_from_email(email: str) -> str:
    if "@" not in email:
        return ""
    return email.split("@", 1)[1].lower()


def _as_uuid(value) -> UUID | None:
    if not value:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        return None


def _owned_campaign_id(db: Session, tenant_id: UUID, value) -> UUID | None:
    parsed = _as_uuid(value)
    if parsed is None:
        return None
    row = db.get(Campaign, parsed)
    if row is None or row.tenant_id != tenant_id or row.deleted_at is not None:
        return None
    return row.id


def _publication(db: Session, tenant_id: UUID, payload: dict) -> CreativeVersion | None:
    token = str(payload.get("publication") or "").strip()
    if not token or len(token) > 64:
        return None
    version = db.scalar(
        select(CreativeVersion).where(
            CreativeVersion.tenant_id == tenant_id,
            CreativeVersion.publication_token == token,
            CreativeVersion.deleted_at.is_(None),
        )
    )
    if version is None:
        return None
    plan = db.get(OperatingPlan, version.plan_id)
    if plan is None or plan.tenant_id != tenant_id or plan.deleted_at is not None:
        return None
    return version


def _apply_capture_publication(capture: InboundCapture, version: CreativeVersion | None) -> None:
    if version is None:
        return
    capture.creative_version_id = version.id
    capture.operating_plan_id = version.plan_id
    capture.social_post_id = version.social_post_id


def _paid_ad(db: Session, tenant_id: UUID, payload: dict) -> PaidAd | None:
    token = str(payload.get("ad") or "").strip()
    if not token or len(token) > 64:
        return None
    return db.scalar(
        select(PaidAd).where(
            PaidAd.tenant_id == tenant_id,
            PaidAd.tracking_token == token,
            PaidAd.deleted_at.is_(None),
        )
    )


def _resolved_attribution(
    db: Session,
    tenant_id: UUID,
    payload: dict,
) -> tuple[CreativeVersion | None, UUID | None, str]:
    """Browser campaign and ad ids are ignored. A tracking token must belong to this tenant."""
    supplied_ad = str(payload.get("ad") or "").strip()
    if supplied_ad:
        paid = _paid_ad(db, tenant_id, payload)
        if paid is None:
            return None, None, ""
        version = db.get(CreativeVersion, paid.creative_version_id) if paid.creative_version_id else None
        if version is None or version.tenant_id != tenant_id or version.deleted_at is not None:
            version = None
        return version, paid.campaign_id, paid.external_id or ""
    version = _publication(db, tenant_id, payload)
    campaign_id = None
    if version is not None:
        plan = db.get(OperatingPlan, version.plan_id)
        if plan is not None and plan.tenant_id == tenant_id:
            campaign_id = _owned_campaign_id(db, tenant_id, plan.campaign_id)
    return version, campaign_id, ""


def _growth_link(db: Session, tenant_id: UUID, payload: dict) -> GrowthTrackingLink | None:
    """A growth token is resolved for this tenant only. An unknown or foreign token attributes nothing."""
    token = str(payload.get("growth") or "").strip()
    return link_for_capture(db, tenant_id, token) if token else None


def _apply_growth_first_touch(db: Session, lead: Lead, link: GrowthTrackingLink | None) -> None:
    if link is None or lead.growth_link_id is not None or lead.creative_version_id is not None or lead.campaign_id is not None:
        return
    lead.growth_link_id = link.id
    if lead.operating_plan_id is None:
        lead.operating_plan_id = strategy_plan_for_link(db, link)
    if not (lead.channel or "").strip() or lead.channel == "website":
        lead.channel = link.utm_source or lead.channel


def _apply_first_touch(lead: Lead, version: CreativeVersion | None, campaign_id: UUID | None) -> None:
    if version is not None and lead.creative_version_id is None:
        lead.creative_version_id = version.id
        lead.operating_plan_id = version.plan_id
        lead.social_post_id = version.social_post_id
        lead.utm_campaign = str(version.plan_id)
        if not (lead.channel or "").strip():
            lead.channel = version.channel
    if lead.campaign_id is None and campaign_id is not None:
        lead.campaign_id = campaign_id


def interest_is_eligible(payload: dict) -> bool:
    email = _normalize_email(str(payload.get("email") or ""))
    return bool(
        str(payload.get("first_name") or "").strip()
        and str(payload.get("last_name") or "").strip()
        and "@" in email
        and str(payload.get("request_note") or "").strip()
        and bool(payload.get("consent_email"))
    )


def hold_interest(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    payload: dict,
) -> InboundCapture:
    email = _normalize_email(str(payload.get("email") or ""))
    if "@" not in email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Valid email required")
    capture = InboundCapture(
        tenant_id=tenant_id,
        created_by=actor_id,
        lead_id=None,
        first_name=str(payload.get("first_name") or "").strip(),
        last_name=str(payload.get("last_name") or "").strip(),
        email=email,
        company_name=str(payload.get("company_name") or ""),
        title=str(payload.get("title") or ""),
        source=str(payload.get("source") or "public_form"),
        channel=str(payload.get("channel") or "website"),
        campaign=str(payload.get("campaign") or ""),
        ad_name=str(payload.get("ad_name") or ""),
        creative=str(payload.get("creative") or ""),
        keyword=str(payload.get("keyword") or ""),
        landing_page=str(payload.get("landing_page") or ""),
        utm_source=str(payload.get("utm_source") or ""),
        utm_medium=str(payload.get("utm_medium") or ""),
        utm_campaign=str(payload.get("utm_campaign") or ""),
        device=str(payload.get("device") or ""),
        consent_email=bool(payload.get("consent_email")),
        phone=str(payload.get("phone") or "")[:40],
        request_note=str(payload.get("request_note") or "").strip(),
        status="review",
        captured_at=datetime.now(UTC),
        campaign_id=None,
        ad_id="",
    )
    version, campaign_id, ad_external = _resolved_attribution(db, tenant_id, payload)
    capture.campaign_id = campaign_id
    capture.ad_id = ad_external
    _apply_capture_publication(capture, version)
    link = _growth_link(db, tenant_id, payload)
    capture.growth_link_id = link.id if link is not None else None
    db.add(capture)
    db.flush()
    return capture


def _fill_blank(row: object, field: str, value: str) -> None:
    if value and not getattr(row, field):
        setattr(row, field, value)


def _resolve_capture_identity(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    payload: dict,
    email: str,
    domain: str,
    contact: Contact | None,
) -> tuple[Account | None, Contact]:
    account = None
    company_name = str(payload.get("company_name") or "").strip()
    if company_name:
        account = db.scalar(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.deleted_at.is_(None),
                or_(Account.name.ilike(company_name), Account.domain == domain),
            )
        )
    if account is None and domain and domain not in FREE_MAIL_DOMAINS:
        account = db.scalar(
            select(Account).where(Account.tenant_id == tenant_id, Account.domain == domain, Account.deleted_at.is_(None))
        )
    if account is None and company_name:
        account = Account(
            tenant_id=tenant_id,
            created_by=actor_id,
            name=company_name,
            domain="" if domain in FREE_MAIL_DOMAINS else domain,
            industry="",
            employee_count=None,
        )
        db.add(account)
        db.flush()
    if contact is None:
        contact = Contact(
            tenant_id=tenant_id,
            created_by=actor_id,
            account_id=account.id if account else None,
            first_name=str(payload.get("first_name") or "").strip(),
            last_name=str(payload.get("last_name") or "").strip(),
            email=email,
            phone=str(payload.get("phone") or "")[:40],
            title=str(payload.get("title") or ""),
            consent_email=bool(payload.get("consent_email")),
            opt_out=False,
        )
        db.add(contact)
        db.flush()
    else:
        if account is not None and contact.account_id is None:
            contact.account_id = account.id
        phone = str(payload.get("phone") or "")[:40]
        title = str(payload.get("title") or "")
        if phone:
            contact.phone = phone
        if title:
            contact.title = title
        if payload.get("consent_email") and not contact.opt_out:
            contact.consent_email = True
    return account, contact


def capture_inbound(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    payload: dict,
    correlation_id: str = "",
) -> tuple[InboundCapture, Lead | None, list[DedupeReview]]:
    email = _normalize_email(payload["email"])
    if not email or "@" not in email:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Valid email required")

    contact = db.scalar(
        select(Contact).where(Contact.tenant_id == tenant_id, Contact.email == email, Contact.deleted_at.is_(None))
    )
    if contact and contact.opt_out:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This person has opted out of contact")

    lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.email == email, Lead.deleted_at.is_(None)))
    domain = _domain_from_email(email)
    account, contact = _resolve_capture_identity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        payload=payload,
        email=email,
        domain=domain,
        contact=contact,
    )

    reviews: list[DedupeReview] = []
    created_lead = False
    version, campaign_id, ad_external = _resolved_attribution(db, tenant_id, payload)
    growth_link = _growth_link(db, tenant_id, payload)
    if lead is None:
        lead = Lead(
            tenant_id=tenant_id,
            created_by=actor_id,
            account_id=account.id if account else None,
            contact_id=contact.id,
            first_name=payload["first_name"],
            last_name=payload["last_name"],
            email=email,
            company_name=payload.get("company_name") or (account.name if account else ""),
            title=payload.get("title", ""),
            source=payload.get("source") or "inbound",
            channel=payload.get("channel") or "website",
            campaign=payload.get("campaign") or payload.get("utm_campaign") or "",
            utm_source=payload.get("utm_source") or "",
            utm_medium=payload.get("utm_medium") or "",
            utm_campaign=str(version.plan_id) if version is not None else (payload.get("utm_campaign") or ""),
            campaign_id=campaign_id,
            ad_id=ad_external,
            status="new",
            consent_email=bool(payload.get("consent_email")),
            opt_out=False,
            notes=str(payload.get("request_note") or "").strip()[:4000],
        )
        _apply_first_touch(lead, version, campaign_id)
        _apply_growth_first_touch(db, lead, growth_link)
        db.add(lead)
        db.flush()
        score_lead(db, lead, emit=False)
        emit_event(
            db,
            tenant_id=tenant_id,
            event_type="lead.created",
            entity_type="lead",
            entity_id=str(lead.id),
            correlation_id=correlation_id,
        )
        created_lead = True
    else:
        note = str(payload.get("request_note") or "").strip()
        if note and note not in (lead.notes or ""):
            current = (lead.notes or "").strip()
            lead.notes = f"{current}\n{note}".strip() if current else note
        review = DedupeReview(
            tenant_id=tenant_id,
            created_by=actor_id,
            left_type="lead",
            left_id=str(lead.id),
            right_type="inbound_capture",
            right_id="pending",
            match_kind="email",
            confidence=95,
            reason="Exact email already exists on a lead.",
            status="pending",
        )
        db.add(review)
        reviews.append(review)
        if account is not None and lead.account_id is None:
            lead.account_id = account.id
        if lead.contact_id is None:
            lead.contact_id = contact.id
        _fill_blank(lead, "title", str(payload.get("title") or ""))
        _fill_blank(lead, "utm_source", str(payload.get("utm_source") or ""))
        _fill_blank(lead, "utm_medium", str(payload.get("utm_medium") or ""))
        _fill_blank(lead, "utm_campaign", str(payload.get("utm_campaign") or ""))
        if payload.get("consent_email") and not lead.opt_out:
            lead.consent_email = True

    if payload.get("company_name"):
        fuzzy = db.scalars(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.deleted_at.is_(None),
                Account.name.ilike(f"%{payload['company_name']}%"),
            )
        ).all()
        for row in fuzzy[:3]:
            if account is not None and row.id == account.id:
                continue
            review = DedupeReview(
                tenant_id=tenant_id,
                created_by=actor_id,
                left_type="account",
                left_id=str(row.id),
                right_type="lead",
                right_id=str(lead.id),
                match_kind="fuzzy_name",
                confidence=60,
                reason=f"Company name resembles {row.name}. Merge only after human review.",
                status="pending",
            )
            db.add(review)
            reviews.append(review)

    capture = InboundCapture(
        tenant_id=tenant_id,
        created_by=actor_id,
        lead_id=lead.id,
        first_name=payload["first_name"],
        last_name=payload["last_name"],
        email=email,
        company_name=payload.get("company_name") or "",
        title=payload.get("title") or "",
        source=payload.get("source") or "inbound",
        channel=payload.get("channel") or "website",
        campaign=payload.get("campaign") or "",
        ad_name=payload.get("ad_name") or "",
        creative=payload.get("creative") or "",
        keyword=payload.get("keyword") or "",
        landing_page=payload.get("landing_page") or "",
        utm_source=payload.get("utm_source") or "",
        utm_medium=payload.get("utm_medium") or "",
        utm_campaign=payload.get("utm_campaign") or "",
        device=payload.get("device") or "",
        consent_email=bool(payload.get("consent_email")),
        phone=str(payload.get("phone") or "")[:40],
        request_note=str(payload.get("request_note") or "").strip(),
        status="accepted" if created_lead else "duplicate_review",
        captured_at=datetime.now(UTC),
        campaign_id=campaign_id,
        ad_id=ad_external,
        growth_link_id=growth_link.id if growth_link is not None else None,
    )
    _apply_capture_publication(capture, version)
    db.add(capture)
    db.flush()
    for review in reviews:
        if review.right_type == "inbound_capture" and review.right_id == "pending":
            review.right_id = str(capture.id)
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="enquiry.received",
        entity_type="lead",
        entity_id=str(lead.id),
        payload={"capture_id": str(capture.id), "source": capture.source},
        correlation_id=correlation_id,
    )
    return capture, lead, reviews


def decide_dedupe(db: Session, row: DedupeReview, decision: str) -> DedupeReview:
    if decision not in {"merge", "dismiss"}:
        raise HTTPException(status_code=422, detail="Decision must be merge or dismiss")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="Review already decided")
    row.status = "merged" if decision == "merge" else "dismissed"
    return row
