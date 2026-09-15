import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.autonomy import AutopilotSettings
from app.models.crm import ICP, Account, Contact, Lead
from app.models.identity import DomainEvent
from app.models.integrations import ProviderAction
from app.providers.lead_discovery import DiscoveredLead, get_lead_discovery_provider
from app.services.audit import emit_event, write_audit
from app.services.autopilot_settings import at_daily_lead_cap, discovered_today, get_or_create_settings
from app.services.crm import add_activity
from app.services.discovery_query import build_discovery_query
from app.services.idempotency import claim_daily_slot
from app.services.provider_metrics import DISCOVERY_CANDIDATES, DISCOVERY_CREATED, DISCOVERY_DUPLICATES
from app.services.provider_ops import (
    begin_action,
    block_action,
    confirm_action,
    fail_action,
    is_circuit_open,
    record_provider_result,
)
from app.services.scoring import score_lead


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_url(url: str) -> str:
    value = (url or "").strip().lower().rstrip("/")
    return value.split("?")[0]


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
    provider: str = "apify",
) -> tuple[str, Lead | None]:
    email = _normalize_email(candidate.email)
    linkedin = _normalize_url(candidate.linkedin_url)
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

    if linkedin:
        url_match = db.scalar(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.deleted_at.is_(None),
                func.lower(Lead.linkedin_url) == linkedin,
            )
        )
        if url_match:
            return "duplicate_linkedin", url_match

    if candidate.provider_ref:
        ref_match = db.scalar(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.deleted_at.is_(None),
                Lead.provider_ref == candidate.provider_ref,
            )
        )
        if ref_match:
            return "duplicate_provider_ref", ref_match

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
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    if account is None and domain:
        account = db.scalar(
            select(Account).where(Account.tenant_id == tenant_id, Account.domain == domain, Account.deleted_at.is_(None))
        )
    if account is None and candidate.company_name:
        account = Account(
            tenant_id=tenant_id,
            created_by=actor_id,
            name=candidate.company_name,
            domain=domain,
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
                linkedin_url=(linkedin or candidate.linkedin_url)[:255],
                preferred_channel="EMAIL",
                consent_voice=False,
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
        linkedin_url=(linkedin or candidate.linkedin_url)[:255],
        provider_ref=candidate.provider_ref[:200],
        discovery_provider=provider,
        retrieved_at=datetime.now(UTC),
        discovery_confidence=candidate.confidence,
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


def _day_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def discovery_runs_today(db: Session, tenant_id: UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ProviderAction)
            .where(
                ProviderAction.tenant_id == tenant_id,
                ProviderAction.deleted_at.is_(None),
                ProviderAction.action_type == "discovery.search",
                ProviderAction.created_at >= _day_start(),
            )
        )
        or 0
    )


def candidates_today(db: Session, tenant_id: UUID) -> int:
    events = db.scalars(
        select(DomainEvent).where(
            DomainEvent.tenant_id == tenant_id,
            DomainEvent.event_type == "discovery.ran",
            DomainEvent.created_at >= _day_start(),
        )
    ).all()
    total = 0
    for event in events:
        try:
            payload = json.loads(event.payload_json or "{}")
        except (ValueError, TypeError):
            payload = {}
        total += int(payload.get("candidate_count") or 0)
    return total


def remaining_candidate_budget(db: Session, settings: AutopilotSettings) -> int:
    per_run = settings.max_candidates_per_run if settings.max_candidates_per_run > 0 else 10
    per_day = settings.max_candidates_per_day if settings.max_candidates_per_day > 0 else 25
    leftover = max(per_day - candidates_today(db, settings.tenant_id), 0)
    leftover_leads = max(settings.max_leads_per_day - discovered_today(db, settings.tenant_id), 0) if settings.max_leads_per_day > 0 else leftover
    return max(0, min(per_run, leftover, leftover_leads))


def run_discovery(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    profile_urls: list[str] | None = None,
    search_query: str = "",
    correlation_id: str = "",
    provider=None,
    enforce_budget: bool = True,
) -> dict:
    icp = default_icp(db, tenant_id)
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    env = get_settings()
    empty = {
        "created": 0,
        "skipped": {},
        "lead_ids": [],
        "provider": "skipped",
        "is_mock": True,
        "connected": False,
        "reason": "",
        "candidate_count": 0,
        "icp_name": icp.name if icp else "",
    }
    if enforce_budget and settings.max_discovery_runs_per_day > 0 and discovery_runs_today(db, tenant_id) >= settings.max_discovery_runs_per_day:
        empty["reason"] = "Daily discovery run cap reached"
        return empty
    if enforce_budget and not claim_daily_slot(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        kind="discovery",
        limit=settings.max_discovery_runs_per_day,
    ):
        empty["reason"] = "Daily discovery run cap reached"
        return empty
    if enforce_budget and at_daily_lead_cap(db, settings):
        empty["reason"] = "Daily discovered-lead cap reached"
        return empty
    if is_circuit_open(db, tenant_id=tenant_id, provider="apify"):
        empty["reason"] = "Blocked by provider"
        empty["provider"] = "apify"
        empty["is_mock"] = False
        return empty
    max_items = remaining_candidate_budget(db, settings) if enforce_budget else min(env.apify_max_items, settings.max_candidates_per_run or 10)
    if enforce_budget and max_items <= 0:
        empty["reason"] = "Daily candidate cap reached"
        return empty
    query = build_discovery_query(
        icp,
        search_query=search_query,
        profile_urls=profile_urls,
        max_items=max_items,
        process_token=env.apify_linkedin_process_token,
    )
    used = provider or get_lead_discovery_provider(db, tenant_id)
    health = used.health() if hasattr(used, "health") else {"provider": "discovery"}
    action = begin_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_type="discovery.search",
        idempotency_key=f"discovery.search:{tenant_id}:{uuid4()}",
        provider=str(health.get("provider") if isinstance(health, dict) else "discovery"),
        request_summary=f"max_items={query.max_items}",
    )
    result = used.discover(query)
    action.provider = result.provider
    created = 0
    skipped: dict[str, int] = {}
    lead_ids: list[str] = []
    for candidate in result.candidates[:max_items]:
        reason, lead = persist_discovered_lead(
            db, tenant_id=tenant_id, actor_id=actor_id, candidate=candidate, provider=result.provider
        )
        if reason == "created" and lead is not None:
            created += 1
            lead_ids.append(str(lead.id))
        else:
            skipped[reason] = skipped.get(reason, 0) + 1
    DISCOVERY_CANDIDATES.labels(provider=result.provider[:40]).inc(len(result.candidates))
    DISCOVERY_CREATED.labels(provider=result.provider[:40]).inc(created)
    DISCOVERY_DUPLICATES.labels(provider=result.provider[:40]).inc(sum(skipped.values()))
    record_provider_result(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        provider=result.provider,
        action="discovery.search",
        ok=result.failure_class == "" and (result.connected or result.is_mock),
        failure_class=result.failure_class,
        error=result.reason,
    )
    if result.failure_class:
        fail_action(action, failure_class=result.failure_class, error=result.reason, retryable=result.failure_class == "TRANSIENT")
    elif not result.connected and not result.is_mock:
        block_action(action, reason=result.reason or "Discovery provider unavailable")
    else:
        confirm_action(action, provider=result.provider, external_id="", response_summary=f"created={created}")
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
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="discovery.ran",
        entity_type="icp",
        entity_id=str(icp.id) if icp else "",
        payload={"candidate_count": len(result.candidates), "created": created, "provider": result.provider},
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
