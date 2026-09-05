from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.acquisition import DedupeReview, InboundCapture
from app.models.crm import Account, Contact, Lead
from app.services.audit import emit_event
from app.services.scoring import score_lead


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _domain_from_email(email: str) -> str:
    if "@" not in email:
        return ""
    return email.split("@", 1)[1].lower()


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
    account = None
    if payload.get("company_name"):
        account = db.scalar(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.deleted_at.is_(None),
                or_(Account.name.ilike(payload["company_name"]), Account.domain == domain),
            )
        )
    if account is None and domain:
        account = db.scalar(
            select(Account).where(Account.tenant_id == tenant_id, Account.domain == domain, Account.deleted_at.is_(None))
        )

    reviews: list[DedupeReview] = []
    created_lead = False
    if lead is None:
        lead = Lead(
            tenant_id=tenant_id,
            created_by=actor_id,
            account_id=account.id if account else None,
            first_name=payload["first_name"],
            last_name=payload["last_name"],
            email=email,
            company_name=payload.get("company_name") or (account.name if account else ""),
            title=payload.get("title", ""),
            source=payload.get("source") or "inbound",
            channel=payload.get("channel") or "website",
            campaign=payload.get("campaign") or "",
            utm_source=payload.get("utm_source") or "",
            status="new",
            consent_email=bool(payload.get("consent_email")),
            opt_out=False,
        )
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

    if account is None and payload.get("company_name"):
        fuzzy = db.scalars(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.deleted_at.is_(None),
                Account.name.ilike(f"%{payload['company_name']}%"),
            )
        ).all()
        for row in fuzzy[:3]:
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
        status="accepted" if created_lead else "duplicate_review",
        captured_at=datetime.now(UTC),
    )
    db.add(capture)
    db.flush()
    for review in reviews:
        if review.right_type == "inbound_capture" and review.right_id == "pending":
            review.right_id = str(capture.id)
    _ = correlation_id
    return capture, lead, reviews


def decide_dedupe(db: Session, row: DedupeReview, decision: str) -> DedupeReview:
    if decision not in {"merge", "dismiss"}:
        raise HTTPException(status_code=422, detail="Decision must be merge or dismiss")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="Review already decided")
    row.status = "merged" if decision == "merge" else "dismissed"
    return row
