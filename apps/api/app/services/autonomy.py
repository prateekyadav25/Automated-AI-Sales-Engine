import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.autonomy import AutonomousRun, AutonomousRunStep
from app.models.crm import Account, Lead
from app.models.identity import Tenant, User
from app.models.lifecycle import Campaign
from app.services.audit import emit_event, write_audit
from app.services.automation_state import get_state
from app.services.autopilot_settings import (
    at_daily_lead_cap,
    get_or_create_settings,
    in_quiet_hours,
)
from app.services.crm import add_activity
from app.services.discovery import run_discovery
from app.services.idempotency import claim_key
from app.services.market import refresh_account_intelligence
from app.services.orchestrator import due_sequence_work, process_pending_events
from app.services.scoring import score_lead


def _step(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    run: AutonomousRun,
    name: str,
    position: int,
    status: str,
    detail: dict,
) -> AutonomousRunStep:
    now = datetime.now(UTC)
    row = AutonomousRunStep(
        tenant_id=tenant_id,
        created_by=actor_id,
        run_id=run.id,
        name=name,
        position=position,
        status=status,
        detail_json=json.dumps(detail, default=str),
        started_at=now,
        finished_at=now,
    )
    db.add(row)
    db.flush()
    return row


def run_autonomous_cycle(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    trigger: str = "manual",
    correlation_id: str = "",
    profile_urls: list[str] | None = None,
) -> AutonomousRun:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    run = AutonomousRun(
        tenant_id=tenant_id,
        created_by=actor_id,
        status="running",
        trigger=trigger,
        workflow="cycle",
        trigger_event="reconcile",
        correlation_id=correlation_id,
        summary="",
    )
    db.add(run)
    db.flush()
    if not settings.enabled:
        _step(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run=run,
            name="discover",
            position=1,
            status="skipped",
            detail={"reason": "autopilot_disabled"},
        )
        run.status = "skipped"
        run.finished_at = datetime.now(UTC)
        run.summary = "Autopilot is disabled for this tenant."
        return run

    discovery = {
        "created": 0,
        "skipped": {},
        "lead_ids": [],
        "provider": "skipped",
        "is_mock": True,
        "connected": False,
        "reason": "Discovery skipped",
        "candidate_count": 0,
        "icp_name": "",
    }
    if settings.discovery_enabled and not at_daily_lead_cap(db, settings) and not in_quiet_hours(settings):
        discovery = run_discovery(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            profile_urls=profile_urls,
            correlation_id=correlation_id,
        )
    elif at_daily_lead_cap(db, settings):
        discovery["reason"] = "Daily discovered-lead cap reached"
    elif in_quiet_hours(settings):
        discovery["reason"] = "Quiet hours"
    elif not settings.discovery_enabled:
        discovery["reason"] = "Discovery module disabled"
    _step(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        run=run,
        name="discover",
        position=1,
        status="completed" if discovery["connected"] or discovery["created"] else "skipped",
        detail=discovery,
    )

    market_created = {"account_signals": 0, "intent_signals": 0, "technology_signals": 0, "triggers": 0}
    accounts_scanned = 0
    if settings.market_monitoring_enabled:
        accounts = db.scalars(
            select(Account).where(Account.tenant_id == tenant_id, Account.deleted_at.is_(None)).limit(20)
        ).all()
        accounts_scanned = len(accounts)
        for account in accounts:
            result = refresh_account_intelligence(db, tenant_id=tenant_id, actor_id=actor_id, account=account)
            for key, value in result.items():
                market_created[key] = market_created.get(key, 0) + value
    _step(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        run=run,
        name="refresh_markets",
        position=2,
        status="completed" if settings.market_monitoring_enabled else "skipped",
        detail={"accounts_scanned": accounts_scanned, "created": market_created, "provider": "mock-intelligence", "is_mock": True},
    )

    leads = db.scalars(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.deleted_at.is_(None),
            Lead.status.notin_(["unqualified", "converted"]),
        )
    ).all()
    scored = 0
    queued_events = 0
    for lead in leads:
        state = get_state(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id))
        if state is None or not state.paused_at:
            if state is None:
                emit_event(
                    db,
                    tenant_id=tenant_id,
                    event_type="lead.created",
                    entity_type="lead",
                    entity_id=str(lead.id),
                    correlation_id=correlation_id,
                )
                queued_events += 1
            elif settings.auto_update_scores and settings.lead_scoring_enabled:
                score_lead(db, lead, emit=True, correlation_id=correlation_id)
                scored += 1
    processed = process_pending_events(db, tenant_id=tenant_id, actor_id=actor_id, limit=200)
    _step(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        run=run,
        name="rescore",
        position=3,
        status="completed",
        detail={"scored": scored, "queued_events": queued_events, "processed_events": processed},
    )

    due = due_sequence_work(db, tenant_id=tenant_id, actor_id=actor_id)
    _step(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        run=run,
        name="propose_enrollments",
        position=4,
        status="completed",
        detail=due,
    )

    campaigns = db.scalars(
        select(Campaign).where(
            Campaign.tenant_id == tenant_id,
            Campaign.deleted_at.is_(None),
            Campaign.status == "draft",
            Campaign.channel.in_(["linkedin", "instagram"]),
        )
    ).all()
    queued_ads = 0
    for campaign in campaigns:
        key = f"ads.spend:{campaign.id}"
        fresh, _ = claim_key(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            key=key,
            workflow="cycle",
            entity_id=str(campaign.id),
            action_type="ads.spend",
        )
        if not fresh:
            continue
        db.add(
            AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="ads.spend",
                title=f"Launch {campaign.channel} campaign {campaign.name}",
                payload_json=json.dumps(
                    {"campaign_id": str(campaign.id), "channel": campaign.channel, "run_id": str(run.id)}
                ),
                status="pending",
                run_id=run.id,
                entity_type="campaign",
                entity_id=str(campaign.id),
                idempotency_key=key,
            )
        )
        queued_ads += 1
    _step(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        run=run,
        name="queue_approvals",
        position=5,
        status="completed",
        detail={"ads_queued": queued_ads, "due_sends": due.get("queued", 0)},
    )

    add_activity(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="autonomous_run",
        entity_id=str(run.id),
        activity_type="autonomy",
        title="Autopilot cycle finished",
        body="Reconciliation queued intake and due work. External send still requires approval.",
        actor_type="ai",
    )
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    run.summary = (
        f"Discovered {discovery['created']}. Rescored {scored}. "
        f"Processed {processed} events. Queued {due.get('queued', 0)} due sends and {queued_ads} ad launches."
    )
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="autonomy.run",
        entity_type="autonomous_run",
        entity_id=str(run.id),
        after={"summary": run.summary, "status": run.status},
        correlation_id=correlation_id,
        actor_type="ai",
    )
    return run


def run_autonomous_cycles_for_all_tenants() -> int:
    from app.db.session import get_engine, get_session

    get_engine()
    db = get_session()
    try:
        tenants = db.scalars(select(Tenant).where(Tenant.is_active.is_(True))).all()
        ran = 0
        for tenant in tenants:
            settings = get_or_create_settings(db, tenant_id=tenant.id)
            if not settings.enabled:
                continue
            actor = db.scalar(select(User).where(User.tenant_id == tenant.id, User.is_active.is_(True)))
            if actor is None:
                continue
            run_autonomous_cycle(db, tenant_id=tenant.id, actor_id=actor.id, trigger="schedule")
            ran += 1
        db.commit()
        return ran
    finally:
        db.close()
