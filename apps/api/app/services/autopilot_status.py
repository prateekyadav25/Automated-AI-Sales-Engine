import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ai import AIApproval, AIRecommendation
from app.models.autonomy import AutonomousRun, AutonomousRunStep, EntityAutomationState
from app.models.crm import Activity, Customer, Lead, LeadScore, Opportunity
from app.models.identity import DomainEvent
from app.models.lifecycle import MeetingRecord
from app.models.post_sale import ExpansionRecommendation
from app.providers.ads import get_ads_provider
from app.providers.calendar import get_calendar_provider
from app.providers.email import get_email_provider
from app.providers.lead_discovery import get_lead_discovery_provider
from app.schemas.autonomy import (
    AutonomyActivityOut,
    AutonomyStatusOut,
    AutonomyTodayOut,
    EntityAutomationOut,
    ProviderHealthOut,
)
from app.services.automation_state import get_state, latest_run_for
from app.services.autopilot_settings import get_or_create_settings
from app.services.provider_ops import action_counts, alert_thresholds, get_health_state
from app.services.provider_resolve import resolve_channel
from app.services.scheduler_health import beat_status
from app.services.voice_router import get_voice_provider


def _mode(*, connected: bool, is_mock: bool) -> str:
    if is_mock:
        return "MOCK"
    if connected:
        return "LIVE"
    return "NOT CONNECTED"


def _provider_state(*, connected: bool, is_mock: bool, reason: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    if is_mock:
        return "MOCK"
    if connected:
        return "CONNECTED"
    lowered = reason.lower()
    if "rate" in lowered:
        return "RATE_LIMITED"
    if "degrad" in lowered:
        return "DEGRADED"
    if "missing" in lowered or "not configured" in lowered or "not implemented" in lowered:
        return "NOT_CONFIGURED"
    if "error" in lowered or "fail" in lowered:
        return "ERROR"
    return "NOT_CONFIGURED"


def provider_health(db: Session | None = None, tenant_id: UUID | None = None) -> list[ProviderHealthOut]:
    settings = get_settings()
    openai_resolved = resolve_channel(db, tenant_id, "openai") if db is not None and tenant_id is not None else None
    openai_connected = bool(openai_resolved and openai_resolved.mode == "LIVE" and openai_resolved.secrets.get("access_token")) or bool(settings.openai_api_key)
    discovery = get_lead_discovery_provider(db, tenant_id).health()
    email = get_email_provider(db, tenant_id).health()
    calendar = get_calendar_provider(db, tenant_id).health()
    linkedin = get_ads_provider("linkedin", db, tenant_id).health()
    meta = get_ads_provider("instagram", db, tenant_id).health()
    voice = get_voice_provider(db, tenant_id).health()
    from app.providers.finance import get_erp_provider, get_finance_provider
    from app.providers.support import get_support_provider
    from app.providers.usage import get_usage_provider

    usage = get_usage_provider(db, tenant_id).health()
    support = get_support_provider(db, tenant_id).health()
    finance = get_finance_provider(db, tenant_id).health()
    erp = get_erp_provider(db, tenant_id).health()

    def _enrich(row: ProviderHealthOut, provider_key: str) -> ProviderHealthOut:
        persisted = get_health_state(db, tenant_id=tenant_id, provider=provider_key) if db and tenant_id else None
        counts = action_counts(db, tenant_id=tenant_id, provider=provider_key) if db and tenant_id else {}
        if persisted:
            row.last_success_at = row.last_success_at or persisted.last_success_at
            row.last_failure_at = row.last_failure_at or persisted.last_failure_at
            row.last_error_summary = row.last_error_summary or persisted.last_error_summary
            if persisted.state in {"DEGRADED", "RATE_LIMITED", "ERROR"}:
                row.state = persisted.state
        row.mode = _mode(connected=row.connected, is_mock=row.is_mock)
        row.pending_actions = int(counts.get("REQUESTED", 0) + counts.get("RETRYING", 0))
        row.failed_actions = int(counts.get("DEAD_LETTER", 0) + counts.get("FAILED", 0))
        return row

    rows = [
        ProviderHealthOut(
            name="OpenAI",
            provider=settings.resolved_llm_provider if settings.resolved_llm_provider != "not_configured" else "openai",
            is_mock=settings.resolved_llm_provider == "mock" and not openai_connected,
            connected=openai_connected,
            reason=(
                openai_resolved.reason
                if openai_resolved and openai_resolved.mode == "LIVE"
                else (
                    "Live key present"
                    if openai_connected
                    else (
                        "LLM_PROVIDER is openai but credentials are missing"
                        if settings.llm_provider == "openai"
                        else "LLM_PROVIDER is mock until OPENAI_API_KEY is set"
                    )
                )
            ),
            state="CONNECTED" if openai_connected else ("NOT_CONFIGURED" if settings.llm_provider == "openai" else "MOCK"),
        ),
        ProviderHealthOut(
            name="Apify",
            provider=str(discovery.get("provider", "mock-discovery")),
            is_mock=bool(discovery.get("is_mock", True)),
            connected=bool(discovery.get("connected", False)),
            reason=str(discovery.get("reason", "")),
            state=_provider_state(
                connected=bool(discovery.get("connected", False)),
                is_mock=bool(discovery.get("is_mock", True)),
                reason=str(discovery.get("reason", "")),
            ),
        ),
        ProviderHealthOut(
            name="Gmail",
            provider=email.provider,
            is_mock=email.is_mock,
            connected=email.connected,
            reason=email.reason,
            state=email.state or _provider_state(connected=email.connected, is_mock=email.is_mock, reason=email.reason),
            last_success_at=email.last_success_at,
            last_failure_at=email.last_failure_at,
            last_error_summary=email.last_error_summary,
        ),
        ProviderHealthOut(
            name="Google Calendar",
            provider=calendar.provider,
            is_mock=calendar.is_mock,
            connected=calendar.connected,
            reason=calendar.reason,
            state=calendar.state or _provider_state(
                connected=calendar.connected, is_mock=calendar.is_mock, reason=calendar.reason
            ),
            last_success_at=calendar.last_success_at,
            last_failure_at=calendar.last_failure_at,
            last_error_summary=calendar.last_error_summary,
        ),
        ProviderHealthOut(
            name="LinkedIn Ads",
            provider=linkedin.provider,
            is_mock=linkedin.is_mock,
            connected=linkedin.connected,
            reason=linkedin.reason,
            state=_provider_state(connected=linkedin.connected, is_mock=linkedin.is_mock, reason=linkedin.reason),
        ),
        ProviderHealthOut(
            name="Meta Ads",
            provider=meta.provider,
            is_mock=meta.is_mock,
            connected=meta.connected,
            reason=meta.reason,
            state=_provider_state(connected=meta.connected, is_mock=meta.is_mock, reason=meta.reason),
        ),
        ProviderHealthOut(
            name="Voice",
            provider=voice.provider,
            is_mock=voice.is_mock,
            connected=voice.connected,
            reason=voice.reason,
            state=_provider_state(connected=voice.connected, is_mock=voice.is_mock, reason=voice.reason),
        ),
        ProviderHealthOut(
            name="Usage",
            provider=usage.provider,
            is_mock=usage.is_mock,
            connected=usage.connected,
            reason=usage.reason,
            state=usage.state,
        ),
        ProviderHealthOut(
            name="Support",
            provider=support.provider,
            is_mock=support.is_mock,
            connected=support.connected,
            reason=support.reason,
            state=support.state,
        ),
        ProviderHealthOut(
            name="Finance",
            provider=finance.provider,
            is_mock=finance.is_mock,
            connected=finance.connected,
            reason=finance.reason,
            state=finance.state,
        ),
        ProviderHealthOut(
            name="ERP",
            provider=erp.provider,
            is_mock=erp.is_mock,
            connected=erp.connected,
            reason=erp.reason,
            state=erp.state,
        ),
    ]
    keys = {
        "OpenAI": "openai",
        "Apify": "apify",
        "Gmail": "google",
        "Google Calendar": "google",
        "LinkedIn Ads": "linkedin-ads",
        "Meta Ads": "meta-ads",
        "Voice": voice.provider,
        "Usage": "usage",
        "Support": "support",
        "Finance": "finance",
        "ERP": "erp",
    }
    return [_enrich(row, keys.get(row.name, row.provider)) for row in rows]


def _today_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def build_status(db: Session, *, tenant_id: UUID, actor_id: UUID) -> AutonomyStatusOut:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    start = _today_start()
    last = db.scalar(
        select(AutonomousRun)
        .where(
            AutonomousRun.tenant_id == tenant_id,
            AutonomousRun.deleted_at.is_(None),
            AutonomousRun.workflow == "cycle",
        )
        .order_by(AutonomousRun.created_at.desc())
    )
    next_cycle = None
    if last and last.created_at:
        created = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=UTC)
        next_cycle = created + timedelta(minutes=15)
    today = AutonomyTodayOut(
        targets_discovered=int(
            db.scalar(
                select(func.count())
                .select_from(Lead)
                .where(
                    Lead.tenant_id == tenant_id,
                    Lead.deleted_at.is_(None),
                    Lead.source == "ai_discovery",
                    Lead.created_at >= start,
                )
            )
            or 0
        ),
        leads_enriched=int(
            db.scalar(
                select(func.count())
                .select_from(DomainEvent)
                .where(
                    DomainEvent.tenant_id == tenant_id,
                    DomainEvent.event_type == "lead.enriched",
                    DomainEvent.created_at >= start,
                )
            )
            or 0
        ),
        leads_scored=int(
            db.scalar(
                select(func.count())
                .select_from(LeadScore)
                .where(LeadScore.tenant_id == tenant_id, LeadScore.deleted_at.is_(None), LeadScore.created_at >= start)
            )
            or 0
        ),
        leads_qualified=int(
            db.scalar(
                select(func.count())
                .select_from(DomainEvent)
                .where(
                    DomainEvent.tenant_id == tenant_id,
                    DomainEvent.event_type == "lead.qualified",
                    DomainEvent.created_at >= start,
                )
            )
            or 0
        ),
        research_completed=int(
            db.scalar(
                select(func.count())
                .select_from(AIRecommendation)
                .where(
                    AIRecommendation.tenant_id == tenant_id,
                    AIRecommendation.kind == "research",
                    AIRecommendation.deleted_at.is_(None),
                    AIRecommendation.created_at >= start,
                )
            )
            or 0
        ),
        messages_prepared=int(
            db.scalar(
                select(func.count())
                .select_from(AIApproval)
                .where(
                    AIApproval.tenant_id == tenant_id,
                    AIApproval.action_type.endswith(".send"),
                    AIApproval.created_at >= start,
                )
            )
            or 0
        ),
        approvals_waiting=int(
            db.scalar(
                select(func.count())
                .select_from(AIApproval)
                .where(AIApproval.tenant_id == tenant_id, AIApproval.deleted_at.is_(None), AIApproval.status == "pending")
            )
            or 0
        ),
        meetings_booked=int(
            db.scalar(
                select(func.count())
                .select_from(MeetingRecord)
                .where(
                    MeetingRecord.tenant_id == tenant_id,
                    MeetingRecord.deleted_at.is_(None),
                    MeetingRecord.status.in_(["booked", "rescheduled"]),
                    MeetingRecord.created_at >= start,
                )
            )
            or 0
        ),
        opportunities_created=int(
            db.scalar(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None), Opportunity.created_at >= start)
            )
            or 0
        ),
        customers_at_risk=int(
            db.scalar(
                select(func.count())
                .select_from(Customer)
                .where(
                    Customer.tenant_id == tenant_id,
                    Customer.deleted_at.is_(None),
                    Customer.lifecycle_state.in_(["AT_RISK", "RENEWAL_IN_PROGRESS"]),
                )
            )
            or 0
        ),
        renewals_processed=int(
            db.scalar(
                select(func.count())
                .select_from(DomainEvent)
                .where(
                    DomainEvent.tenant_id == tenant_id,
                    DomainEvent.event_type.in_(["renewal.window_opened", "renewal.prepared"]),
                    DomainEvent.created_at >= start,
                )
            )
            or 0
        ),
        expansion_opportunities=int(
            db.scalar(
                select(func.count())
                .select_from(ExpansionRecommendation)
                .where(
                    ExpansionRecommendation.tenant_id == tenant_id,
                    ExpansionRecommendation.deleted_at.is_(None),
                    ExpansionRecommendation.status == "open",
                )
            )
            or 0
        ),
    )
    providers = provider_health(db, tenant_id)
    from app.services.autopilot_settings import get_or_create_settings as _settings

    live_flags = _settings(db, tenant_id=tenant_id, actor_id=actor_id)
    always_optional = set()
    if not live_flags.usage_live_enabled:
        always_optional.add("Usage")
    if not live_flags.support_live_enabled:
        always_optional.add("Support")
    if not live_flags.finance_live_enabled:
        always_optional.add("Finance")
    if not live_flags.erp_live_enabled:
        always_optional.add("ERP")
    blocked_config = [
        row.name
        for row in providers
        if row.state in {"NOT_CONFIGURED", "ERROR", "RATE_LIMITED", "DEGRADED"} and row.name not in always_optional
    ]
    blocked_policy = int(
        db.scalar(
            select(func.count())
            .select_from(EntityAutomationState)
            .where(
                EntityAutomationState.tenant_id == tenant_id,
                EntityAutomationState.deleted_at.is_(None),
                EntityAutomationState.state == "BLOCKED",
            )
        )
        or 0
    )
    failed = int(
        db.scalar(
            select(func.count())
            .select_from(AutonomousRunStep)
            .where(
                AutonomousRunStep.tenant_id == tenant_id,
                AutonomousRunStep.deleted_at.is_(None),
                AutonomousRunStep.status.in_(["FAILED", "failed"]),
            )
        )
        or 0
    )
    counts = action_counts(db, tenant_id=tenant_id)
    pending_actions = int(counts.get("REQUESTED", 0) + counts.get("RETRYING", 0))
    dead_letters = int(counts.get("DEAD_LETTER", 0))
    thresholds = alert_thresholds(settings.alert_rules_json)
    alerts: list[str] = []
    if dead_letters >= thresholds["dead_letters"]:
        alerts.append("dead letters")
    if pending_actions >= thresholds["inbox_backlog"]:
        alerts.append("queue backlog")
    if failed >= thresholds["provider_failure_spike"]:
        alerts.append("provider failure spike")
    beat = beat_status(db)
    if beat["scheduler_unhealthy"]:
        alerts.append("scheduler unhealthy")
    return AutonomyStatusOut(
        enabled=settings.enabled,
        last_cycle_at=last.created_at if last else None,
        next_cycle_at=next_cycle,
        worker="In-process event flush is available. Celery Beat schedules reconcile every 15 minutes.",
        queue="Redis broker when the worker and beat services are running.",
        scheduler_unhealthy=bool(beat["scheduler_unhealthy"]),
        today=today,
        providers=providers,
        blocked_human=today.approvals_waiting,
        blocked_config=blocked_config,
        blocked_policy=blocked_policy,
        failed_steps=failed,
        pending_actions=pending_actions,
        dead_letters=dead_letters,
        alerts=alerts,
    )


def activity_feed(db: Session, *, tenant_id: UUID, limit: int = 40) -> list[AutonomyActivityOut]:
    events = db.scalars(
        select(DomainEvent)
        .where(DomainEvent.tenant_id == tenant_id)
        .order_by(DomainEvent.created_at.desc())
        .limit(limit)
    ).all()
    activities = db.scalars(
        select(Activity)
        .where(Activity.tenant_id == tenant_id, Activity.deleted_at.is_(None), Activity.actor_type == "ai")
        .order_by(Activity.created_at.desc())
        .limit(limit)
    ).all()
    titles = {
        "email.sent": "Email sent through Gmail",
        "email.received": "Inbound reply received",
        "meeting.booked": "Meeting booked",
        "meeting.created": "Meeting created",
        "lead.created": "Lead created",
        "lead.qualified": "Lead qualified",
        "lead.ready_for_outreach": "Lead ready for outreach",
        "customer.created": "Customer created",
        "handoff.created": "Handoff package created",
        "onboarding.started": "Onboarding started",
        "onboarding.milestone_due": "Onboarding milestone due",
        "onboarding.completed": "Onboarding completed",
        "customer.health_changed": "Health recalculated",
        "customer.risk_detected": "Customer risk detected",
        "qbr.prepared": "QBR brief prepared",
        "renewal.window_opened": "Renewal window opened",
        "renewal.prepared": "Renewal brief prepared",
        "expansion.detected": "Expansion identified",
        "upsell.detected": "Upsell identified",
        "cross_sell.detected": "Cross-sell identified",
        "advocacy.eligible": "Advocacy candidate identified",
        "referral.received": "Referral received",
        "discovery.ran": "Discovery run completed",
        "campaign.launched": "Campaign launched",
        "voice.dialed": "Voice dial placed",
        "voice.status": "Call status updated",
        "voice.suppressed": "Do-not-call applied",
        "meeting.requested": "Meeting requested from call",
        "sequence.followup": "Sequence follow-up queued",
    }
    rows: list[AutonomyActivityOut] = []
    for event in events:
        title = titles.get(event.event_type, event.event_type)
        if event.event_type == "email.sent":
            try:
                payload = json.loads(event.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            provider = str(payload.get("provider") or "email")
            title = f"Email sent through {provider}"
        rows.append(
            AutonomyActivityOut(
                id=str(event.id),
                occurred_at=event.created_at,
                kind="event",
                title=title,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                status="processed" if event.processed_at else "pending",
            )
        )
    for activity in activities:
        rows.append(
            AutonomyActivityOut(
                id=str(activity.id),
                occurred_at=activity.created_at,
                kind="activity",
                title=activity.title,
                entity_type=activity.entity_type,
                entity_id=activity.entity_id,
            )
        )
    rows.sort(key=lambda row: row.occurred_at, reverse=True)
    return rows[:limit]


def entity_trace(db: Session, *, tenant_id: UUID, entity_type: str, entity_id: str) -> EntityAutomationOut:
    state = get_state(db, tenant_id=tenant_id, entity_type=entity_type, entity_id=entity_id)
    if state is None:
        return EntityAutomationOut(
            entity_type=entity_type,
            entity_id=entity_id,
            state="NONE",
            last_action="",
            next_action="",
            blocked_reason="",
            paused=False,
        )
    run = latest_run_for(db, tenant_id=tenant_id, run_id=state.run_id)
    return EntityAutomationOut(
        entity_type=entity_type,
        entity_id=entity_id,
        state=state.state,
        last_action=state.last_action,
        next_action=state.next_action,
        blocked_reason=state.blocked_reason,
        paused=state.paused_at is not None,
        run_id=state.run_id,
        workflow=run.workflow if run else "",
        run_status=run.status if run else "",
    )
