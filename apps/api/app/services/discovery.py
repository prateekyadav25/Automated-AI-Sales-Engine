from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.crm import ICP, Account, Contact, Lead
from app.providers.lead_discovery import DiscoveredLead, DiscoveryQuery, get_lead_discovery_provider
from app.services.audit import emit_event, write_audit
from app.services.crm import add_activity
from app.services.scoring import score_lead


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def default_icp(db: Session, tenant_id: UUID) -> ICP | None:
    rows = db.scalars(select(ICP).where(ICP.tenant_id == tenant_id, ICP.deleted_at.is_(None))).all()
    return next((row for row in rows if row.is_default), rows[0] if rows else None)


def _find_account(db: Session, tenant_id: UUID, company_name: str, email: str) -> Account | None:
    if company_name:
        account = db.scalar(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.deleted_at.is_(None),
                func.lower(Account.name) == company_name.lower(),
            )
        )
        if account:
            return account
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    if domain:
        return db.scalar(
            select(Account).where(Account.tenant_id == tenant_id, Account.domain == domain, Account.deleted_at.is_(None))
        )
    return None


def persist_discovered_lead(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    candidate: DiscoveredLead,
) -> tuple[str, Lead | None]:
    email = _normalize_email(candidate.email)
    if email:
        contact = db.scalar(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.email == email, Contact.deleted_at.is_(None))
        )
        if contact and contact.opt_out:
            return "opt_out", None
        existing = db.scalar(
            select(Lead).where(Lead.tenant_id == tenant_id, Lead.email == email, Lead.deleted_at.is_(None))
        )
        if existing:
            return "duplicate_email", existing

    person_match = db.scalar(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.deleted_at.is_(None),
            func.lower(Lead.first_name) == candidate.first_name.lower(),
            func.lower(Lead.last_name) == candidate.last_name.lower(),
            func.lower(Lead.company_name) == (candidate.company_name or "").lower(),
        )
    )
    if person_match:
        return "duplicate_person", person_match

    account = _find_account(db, tenant_id, candidate.company_name, email)
    if account is None and candidate.company_name:
        account = Account(
            tenant_id=tenant_id,
            created_by=actor_id,
            name=candidate.company_name,
            domain=email.split("@", 1)[1].lower() if "@" in email else "",
            ownership="prospect",
            notes="Created by AI discovery. Review before outreach.",
        )
        db.add(account)
        db.flush()

    contact_id = None
    if email:
        contact = db.scalar(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.email == email, Contact.deleted_at.is_(None))
        )
        if contact is None:
            contact = Contact(
                tenant_id=tenant_id,
                created_by=actor_id,
                account_id=account.id if account else None,
                first_name=candidate.first_name,
                last_name=candidate.last_name,
                email=email,
                title=candidate.title,
                consent_email=False,
                opt_out=False,
            )
            db.add(contact)
            db.flush()
        contact_id = contact.id

    notes = f"LinkedIn: {candidate.linkedin_url}" if candidate.linkedin_url else ""
    lead = Lead(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=account.id if account else None,
        contact_id=contact_id,
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        email=email,
        company_name=candidate.company_name or (account.name if account else ""),
        title=candidate.title,
        source="ai_discovery",
        channel="ai_discovery",
        status="new",
        consent_email=False,
        opt_out=False,
        notes=notes,
    )
    db.add(lead)
    db.flush()
    score_lead(db, lead, emit=False)
    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="discovery",
        title="Lead discovered",
        body="Source is AI discovery. Consent is false until a human records it.",
        actor_type="ai",
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="lead.created",
        entity_type="lead",
        entity_id=str(lead.id),
    )
    return "created", lead


def run_discovery(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    profile_urls: list[str] | None = None,
    search_query: str = "",
    correlation_id: str = "",
    provider=None,
) -> dict:
    icp = default_icp(db, tenant_id)
    settings = get_settings()
    query = DiscoveryQuery(
        industries=icp.industries if icp else "",
        geographies=icp.geographies if icp else "",
        search_query=search_query,
        profile_urls=tuple(url.strip() for url in (profile_urls or []) if url.strip()),
        max_items=settings.apify_max_items,
        process_token=settings.apify_linkedin_process_token,
    )
    used = provider or get_lead_discovery_provider()
    result = used.discover(query)
    created = 0
    skipped: dict[str, int] = {}
    lead_ids: list[str] = []
    for candidate in result.candidates:
        reason, lead = persist_discovered_lead(db, tenant_id=tenant_id, actor_id=actor_id, candidate=candidate)
        if reason == "created" and lead is not None:
            created += 1
            lead_ids.append(str(lead.id))
        else:
            skipped[reason] = skipped.get(reason, 0) + 1
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="discovery.run",
        entity_type="lead",
        after={
            "created": created,
            "skipped": skipped,
            "provider": result.provider,
            "is_mock": result.is_mock,
        },
        correlation_id=correlation_id,
        actor_type="ai",
    )
    return {
        "created": created,
        "skipped": skipped,
        "lead_ids": lead_ids,
        "provider": result.provider,
        "is_mock": result.is_mock,
        "connected": result.connected,
        "reason": result.reason,
        "candidate_count": len(result.candidates),
        "icp_name": icp.name if icp else "",
    }
