from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ai import AIApproval, AIRecommendation
from app.models.autonomy import AutonomousRun, AutonomousRunStep, EntityAutomationState
from app.models.crm import Activity, Lead, LeadScore, Opportunity
from app.models.identity import DomainEvent
from app.providers.ads import get_ads_provider
from app.providers.email import get_email_provider
from app.providers.lead_discovery import get_lead_discovery_provider
from app.providers.voice import get_voice_provider
from app.schemas.autonomy import (
    AutonomyActivityOut,
    AutonomyStatusOut,
    AutonomyTodayOut,
    EntityAutomationOut,
    ProviderHealthOut,
)
from app.services.automation_state import get_state, latest_run_for
from app.services.autopilot_settings import get_or_create_settings


def _provider_state(*, connected: bool, is_mock: bool, reason: str) -> str:
    if is_mock and not connected:
        return "Misconfigured" if "missing" in reason.lower() or "not configured" in reason.lower() else "Mock"
    if is_mock:
        return "Mock"
    if connected:
        return "Connected"
    return "Unavailable"


def provider_health() -> list[ProviderHealthOut]:
    settings = get_settings()
    openai_connected = bool(settings.openai_api_key)
    discovery = get_lead_discovery_provider().health()
    email = get_email_provider().health()
    linkedin = get_ads_provider("linkedin").health()
    meta = get_ads_provider("instagram").health()
    voice = get_voice_provider().health()
    rows = [
        ProviderHealthOut(
            name="OpenAI",
            provider=settings.resolved_llm_provider,
            is_mock=settings.resolved_llm_provider == "mock",
            connected=openai_connected,
            reason="Live key present" if openai_connected else "LLM_PROVIDER is mock until OPENAI_API_KEY is set",
            state="Connected" if openai_connected else "Mock",
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
            name="Email",
            provider=email.provider,
            is_mock=email.is_mock,
            connected=email.connected,
            reason=email.reason,
            state=_provider_state(connected=email.connected, is_mock=email.is_mock, reason=email.reason),
        ),
        ProviderHealthOut(
            name="Calendar",
            provider="google-calendar",
            is_mock=True,
            connected=False,
            reason="Google Calendar is not implemented in this batch.",
            state="Misconfigured",
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
    ]
    return rows


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
        opportunities_created=int(
            db.scalar(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None), Opportunity.created_at >= start)
            )
            or 0
        ),
    )
    providers = provider_health()
    blocked_config = [row.name for row in providers if row.state in {"Misconfigured", "Unavailable"}]
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
    return AutonomyStatusOut(
        enabled=settings.enabled,
        last_cycle_at=last.created_at if last else None,
        next_cycle_at=next_cycle,
        worker="In-process event flush is available. Celery Beat schedules reconcile every 15 minutes.",
        queue="Redis broker when the worker and beat services are running.",
        today=today,
        providers=providers,
        blocked_human=today.approvals_waiting,
        blocked_config=blocked_config,
        blocked_policy=blocked_policy,
        failed_steps=failed,
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
    rows: list[AutonomyActivityOut] = []
    for event in events:
        rows.append(
            AutonomyActivityOut(
                id=str(event.id),
                occurred_at=event.created_at,
                kind="event",
                title=event.event_type,
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
