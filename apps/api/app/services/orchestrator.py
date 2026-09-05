import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.runtime import research_account
from app.models.ai import AIApproval, AIRecommendation
from app.models.autonomy import AutomationIdempotencyKey, AutonomousRun, AutonomousRunStep, AutopilotSettings
from app.models.crm import Lead, Task
from app.models.identity import DomainEvent, User
from app.models.lifecycle import Sequence, SequenceEnrollment, SequenceStep
from app.services.audit import emit_event
from app.services.automation_state import get_state, is_entity_paused, upsert_state
from app.services.autopilot_settings import get_or_create_settings, in_quiet_hours
from app.services.crm import add_activity
from app.services.enrichment import enrich_lead
from app.services.idempotency import claim_key, remember_result
from app.services.lifecycle import enroll_sequence
from app.services.nba import generate_for_lead
from app.services.qualification import latest_score, qualify_lead
from app.services.rbac import user_permissions
from app.services.scoring import score_lead

LEAD_STATES = [
    "DISCOVERED",
    "ENRICHING",
    "ENRICHED",
    "SCORING",
    "SCORED",
    "QUALIFYING",
    "QUALIFIED",
    "RESEARCHING",
    "READY_FOR_OUTREACH",
    "OUTREACH_APPROVAL_PENDING",
    "CONTACTED",
    "BLOCKED",
    "PAUSED",
]


def _rank(state: str) -> int:
    try:
        return LEAD_STATES.index(state)
    except ValueError:
        return -1


def _actor(db: Session, tenant_id: UUID, actor_id: UUID | None) -> UUID:
    if actor_id is not None:
        return actor_id
    user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)))
    if user is None:
        raise RuntimeError("No active user for tenant automation")
    return user.id


def _permissions(db: Session, actor_id: UUID) -> set[str]:
    user = db.get(User, actor_id)
    if user is None:
        return set()
    return user_permissions(db, user)


def _add_step(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    run: AutonomousRun,
    name: str,
    position: int,
    status: str,
    detail: dict,
    entity_type: str = "",
    entity_id: str = "",
    error: str = "",
    idempotency_key: str = "",
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
        entity_type=entity_type,
        entity_id=entity_id,
        error=error,
        idempotency_key=idempotency_key,
        started_at=now,
        finished_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _intake_run(db: Session, *, tenant_id: UUID, actor_id: UUID, lead: Lead, correlation_id: str) -> AutonomousRun:
    existing = db.scalar(
        select(AutonomousRun).where(
            AutonomousRun.tenant_id == tenant_id,
            AutonomousRun.workflow == "lead_intake",
            AutonomousRun.trigger_event == f"lead:{lead.id}",
            AutonomousRun.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    run = AutonomousRun(
        tenant_id=tenant_id,
        created_by=actor_id,
        status="running",
        trigger="event",
        workflow="lead_intake",
        trigger_event=f"lead:{lead.id}",
        correlation_id=correlation_id,
        summary="",
    )
    db.add(run)
    db.flush()
    return run


def _finish_run(run: AutonomousRun, summary: str, status: str = "completed") -> None:
    run.status = status
    run.summary = summary
    run.finished_at = datetime.now(UTC)


def _load_lead(db: Session, tenant_id: UUID, entity_id: str) -> Lead | None:
    try:
        lead_id = UUID(entity_id)
    except ValueError:
        return None
    return db.scalar(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.id == lead_id, Lead.deleted_at.is_(None))
    )


def select_sequence(db: Session, tenant_id: UUID) -> Sequence | None:
    return db.scalar(
        select(Sequence)
        .where(
            Sequence.tenant_id == tenant_id,
            Sequence.deleted_at.is_(None),
            Sequence.channel == "email",
            Sequence.status.in_(["live", "active", "draft"]),
        )
        .order_by(Sequence.created_at.asc())
    )


def prepare_outreach(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    settings: AutopilotSettings,
    run: AutonomousRun,
    correlation_id: str,
    position: int,
) -> dict:
    if in_quiet_hours(settings):
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="READY_FOR_OUTREACH",
            last_action="defer_quiet_hours",
            next_action="prepare_outreach",
            blocked_reason="Quiet hours",
            run_id=run.id,
        )
        _add_step(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run=run,
            name="prepare_outreach",
            position=position,
            status="WAITING_FOR_TIME",
            detail={"reason": "quiet_hours"},
            entity_type="lead",
            entity_id=str(lead.id),
        )
        return {"status": "WAITING_FOR_TIME", "reason": "quiet_hours"}
    if lead.opt_out:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="outreach_blocked",
            blocked_reason="Lead has opted out",
            run_id=run.id,
        )
        return {"status": "BLOCKED", "reason": "opt_out"}
    if not lead.consent_email:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="outreach_blocked",
            next_action="record_consent",
            blocked_reason="Lead has no consent",
            run_id=run.id,
        )
        _add_step(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run=run,
            name="prepare_outreach",
            position=position,
            status="BLOCKED",
            detail={"reason": "Lead has no consent"},
            entity_type="lead",
            entity_id=str(lead.id),
        )
        return {"status": "BLOCKED", "reason": "Lead has no consent"}
    latest = latest_score(db, lead)
    total = latest.total if latest else 0
    if total < settings.minimum_lead_score:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="outreach_blocked",
            blocked_reason="below minimum score",
            run_id=run.id,
        )
        return {"status": "BLOCKED", "reason": "below minimum score", "total": total}
    if not settings.sequence_enrollment_enabled or not settings.outreach_preparation_enabled:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="READY_FOR_OUTREACH",
            last_action="outreach_skipped_policy",
            next_action="enable_sequence_enrollment",
            blocked_reason="Sequence enrollment disabled",
            run_id=run.id,
        )
        return {"status": "SKIPPED", "reason": "module_disabled"}
    sequence = select_sequence(db, tenant_id)
    if sequence is None:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="no_sequence",
            next_action="configure_sequence",
            blocked_reason="no_sequence",
            run_id=run.id,
        )
        if settings.auto_create_internal_tasks:
            db.add(
                Task(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    title="Configure an email sequence",
                    description=f"Qualified lead {lead.email or lead.id} has no eligible sequence.",
                    status="open",
                    priority="medium",
                    entity_type="lead",
                    entity_id=str(lead.id),
                    source="workflow",
                )
            )
        return {"status": "BLOCKED", "reason": "no_sequence"}
    enrollment = enroll_sequence(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        sequence=sequence,
        lead=lead,
        run_id=run.id,
        actor_type="ai",
    )
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        state="OUTREACH_APPROVAL_PENDING",
        last_action="enroll_sequence",
        next_action="approve_send",
        blocked_reason="",
        run_id=run.id,
    )
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="lead.ready_for_outreach",
        entity_type="lead",
        entity_id=str(lead.id),
        payload={"sequence_id": str(sequence.id), "enrollment_id": str(enrollment.id)},
        correlation_id=correlation_id,
    )
    _add_step(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        run=run,
        name="prepare_outreach",
        position=position,
        status="WAITING_FOR_APPROVAL",
        detail={"sequence_id": str(sequence.id), "enrollment_id": str(enrollment.id)},
        entity_type="lead",
        entity_id=str(lead.id),
        idempotency_key=f"enroll:{lead.id}:{sequence.id}",
    )
    return {"status": "WAITING_FOR_APPROVAL", "sequence_id": str(sequence.id), "enrollment_id": str(enrollment.id)}


def run_lead_intake(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    correlation_id: str = "",
    from_step: str = "enrich",
) -> dict:
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
    if not settings.enabled:
        return {"status": "SKIPPED", "reason": "autopilot_disabled"}
    if is_entity_paused(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id)):
        return {"status": "SKIPPED", "reason": "entity_paused"}
    claimed, key_row = claim_key(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        key=f"lead_intake:{lead.id}",
        workflow="lead_intake",
        entity_id=str(lead.id),
        action_type="intake",
    )
    run = _intake_run(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, correlation_id=correlation_id)
    if not claimed and key_row.result_ref:
        existing_state = get_state(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id))
        if existing_state and _rank(existing_state.state) >= _rank("READY_FOR_OUTREACH"):
            return {"status": "SKIPPED", "reason": "already_processed", "run_id": str(run.id)}
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        state="DISCOVERED" if lead.source == "ai_discovery" else "DISCOVERED",
        last_action="intake_started",
        next_action="enrich",
        run_id=run.id,
    )
    position = 1
    result: dict = {"run_id": str(run.id)}
    steps_from = {"enrich": 0, "score": 1, "qualify": 2, "research": 3, "outreach": 4}.get(from_step, 0)

    if steps_from <= 0:
        if settings.enrichment_enabled:
            upsert_state(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entity_type="lead",
                entity_id=str(lead.id),
                state="ENRICHING",
                last_action="enrich",
                next_action="score",
                run_id=run.id,
            )
            fresh, _ = claim_key(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                key=f"enrich:{lead.id}",
                workflow="lead_intake",
                entity_id=str(lead.id),
                action_type="enrich",
            )
            detail = {"skipped": True} if not fresh else enrich_lead(
                db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, correlation_id=correlation_id
            )
            _add_step(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                run=run,
                name="enrich",
                position=position,
                status="completed",
                detail=detail,
                entity_type="lead",
                entity_id=str(lead.id),
                idempotency_key=f"enrich:{lead.id}",
            )
            upsert_state(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entity_type="lead",
                entity_id=str(lead.id),
                state="ENRICHED",
                last_action="enrich",
                next_action="score",
                run_id=run.id,
            )
        position += 1

    score_row = None
    if steps_from <= 1 and settings.lead_scoring_enabled:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="SCORING",
            last_action="score",
            next_action="qualify",
            run_id=run.id,
        )
        score_row = score_lead(db, lead, emit=True, correlation_id=correlation_id)
        _add_step(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run=run,
            name="score",
            position=position,
            status="completed",
            detail={"total": score_row.total, "reasons": score_row.reasons},
            entity_type="lead",
            entity_id=str(lead.id),
        )
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="SCORED",
            last_action="score",
            next_action="qualify",
            run_id=run.id,
        )
        result["score"] = score_row.total
        position += 1

    qualified = False
    if steps_from <= 2 and settings.qualification_enabled:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="QUALIFYING",
            last_action="qualify",
            next_action="research",
            run_id=run.id,
        )
        qualification = qualify_lead(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            settings=settings,
            correlation_id=correlation_id,
        )
        qualified = bool(qualification["qualified"])
        _add_step(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run=run,
            name="qualify",
            position=position,
            status="completed" if qualified else "BLOCKED",
            detail=qualification,
            entity_type="lead",
            entity_id=str(lead.id),
        )
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="QUALIFIED" if qualified else "BLOCKED",
            last_action="qualify",
            next_action="research" if qualified else "",
            blocked_reason="" if qualified else "; ".join(qualification.get("reasons", [])),
            run_id=run.id,
        )
        result["qualified"] = qualified
        position += 1
    elif not settings.qualification_enabled:
        qualified = True

    if qualified and steps_from <= 3 and settings.research_enabled and lead.account_id:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="RESEARCHING",
            last_action="research",
            next_action="prepare_outreach",
            run_id=run.id,
        )
        fresh, _ = claim_key(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            key=f"research:{lead.account_id}",
            workflow="lead_intake",
            entity_id=str(lead.account_id),
            action_type="research",
        )
        brief = {}
        if fresh:
            brief = research_account(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                permissions=_permissions(db, actor_id),
                account_id=lead.account_id,
            )
        _add_step(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run=run,
            name="research",
            position=position,
            status="completed",
            detail={"provider": brief.get("provider"), "is_mock": brief.get("is_mock"), "skipped": not fresh},
            entity_type="account",
            entity_id=str(lead.account_id),
            idempotency_key=f"research:{lead.account_id}",
        )
        position += 1

    if qualified:
        generate_for_lead(db, tenant_id, lead, actor_id)
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="READY_FOR_OUTREACH",
            last_action="nba",
            next_action="prepare_outreach",
            run_id=run.id,
        )
        outreach = prepare_outreach(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            settings=settings,
            run=run,
            correlation_id=correlation_id,
            position=position,
        )
        result["outreach"] = outreach
        summary = f"Intake for {lead.email or lead.id}. Outreach {outreach.get('status')}."
        run_status = "WAITING_FOR_APPROVAL" if outreach.get("status") == "WAITING_FOR_APPROVAL" else "completed"
        if outreach.get("status") == "BLOCKED":
            run_status = "completed"
        _finish_run(run, summary, run_status)
        remember_result(key_row, str(run.id))
        return result

    _finish_run(run, f"Intake blocked for {lead.email or lead.id}.")
    remember_result(key_row, str(run.id))
    return result


def handle_event(db: Session, event: DomainEvent, *, actor_id: UUID | None = None) -> str:
    tenant_id = event.tenant_id
    actor = _actor(db, tenant_id, actor_id)
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor)
    if not settings.enabled:
        return "skipped_disabled"
    event_type = event.event_type
    if event_type in {
        "lead.created",
        "lead.enriched",
        "lead.scored",
        "lead.qualified",
        "lead.disqualified",
        "lead.ready_for_outreach",
        "email.sent",
    }:
        lead = _load_lead(db, tenant_id, event.entity_id)
        if lead is None:
            return "missing_lead"
        if is_entity_paused(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id)):
            return "paused"
        state = get_state(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id))
        if event_type == "lead.created":
            run_lead_intake(db, tenant_id=tenant_id, actor_id=actor, lead=lead, correlation_id=event.correlation_id)
            return "intake"
        if event_type == "lead.enriched":
            if state and _rank(state.state) >= _rank("SCORING"):
                return "skipped"
            run_lead_intake(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                lead=lead,
                correlation_id=event.correlation_id,
                from_step="score",
            )
            return "continued"
        if event_type == "lead.scored":
            if state is None:
                return "deferred"
            if _rank(state.state) >= _rank("QUALIFYING"):
                return "skipped"
            run_lead_intake(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                lead=lead,
                correlation_id=event.correlation_id,
                from_step="qualify",
            )
            return "continued"
        if event_type == "lead.qualified":
            if state and _rank(state.state) >= _rank("RESEARCHING"):
                return "skipped"
            run_lead_intake(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                lead=lead,
                correlation_id=event.correlation_id,
                from_step="research",
            )
            return "continued"
        return "recorded"
    return "ignored"


def process_pending_events(
    db: Session,
    *,
    tenant_id: UUID | None = None,
    actor_id: UUID | None = None,
    limit: int = 200,
) -> int:
    db.flush()
    processed = 0
    while processed < limit:
        stmt = select(DomainEvent).where(DomainEvent.processed_at.is_(None)).order_by(DomainEvent.created_at.asc())
        if tenant_id is not None:
            stmt = stmt.where(DomainEvent.tenant_id == tenant_id)
        event = db.execute(stmt.limit(1)).scalars().first()
        if event is None:
            break
        try:
            handle_event(db, event, actor_id=actor_id)
            event.processed_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 — isolated per event
            event.processed_at = datetime.now(UTC)
            add_activity(
                db,
                tenant_id=event.tenant_id,
                actor_id=actor_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                activity_type="automation_error",
                title="Automation step failed",
                body=str(exc)[:1000],
                actor_type="ai",
            )
        db.flush()
        processed += 1
    return processed


def retry_entity(db: Session, *, tenant_id: UUID, actor_id: UUID, entity_type: str, entity_id: str) -> int:
    row = db.scalar(
        select(AutomationIdempotencyKey).where(
            AutomationIdempotencyKey.tenant_id == tenant_id,
            AutomationIdempotencyKey.key == f"lead_intake:{entity_id}",
            AutomationIdempotencyKey.deleted_at.is_(None),
        )
    )
    if row is not None:
        row.deleted_at = datetime.now(UTC)
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="lead.created" if entity_type == "lead" else f"{entity_type}.retry",
        entity_type=entity_type,
        entity_id=str(entity_id),
    )
    return process_pending_events(db, tenant_id=tenant_id, actor_id=actor_id)


def due_sequence_work(db: Session, *, tenant_id: UUID, actor_id: UUID) -> dict:
    now = datetime.now(UTC)
    enrollments = db.scalars(
        select(SequenceEnrollment).where(
            SequenceEnrollment.tenant_id == tenant_id,
            SequenceEnrollment.deleted_at.is_(None),
            SequenceEnrollment.status == "active",
            SequenceEnrollment.next_run_at.is_not(None),
            SequenceEnrollment.next_run_at <= now,
        )
    ).all()
    queued = 0
    for enrollment in enrollments:
        step = db.scalar(
            select(SequenceStep).where(
                SequenceStep.sequence_id == enrollment.sequence_id,
                SequenceStep.deleted_at.is_(None),
                SequenceStep.position == enrollment.current_step,
            )
        )
        if step is None or step.action_type != "email_draft":
            continue
        key = f"sequence.email.send:{enrollment.lead_id}:{enrollment.id}:{enrollment.current_step}"
        exists = db.scalar(
            select(AIApproval).where(
                AIApproval.tenant_id == tenant_id,
                AIApproval.idempotency_key == key,
                AIApproval.deleted_at.is_(None),
            )
        )
        if exists is not None:
            continue
        lead = _load_lead(db, tenant_id, str(enrollment.lead_id))
        if lead is None or lead.opt_out or not lead.consent_email:
            continue
        db.add(
            AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=2,
                action_type="sequence.email.send",
                title=f"Send sequence step for {lead.email}",
                payload_json=json.dumps(
                    {
                        "enrollment_id": str(enrollment.id),
                        "lead_id": str(lead.id),
                        "template": step.template,
                    }
                ),
                status="pending",
                entity_type="lead",
                entity_id=str(lead.id),
                idempotency_key=key,
            )
        )
        queued += 1
    return {"due": len(enrollments), "queued": queued}


def research_exists(db: Session, tenant_id: UUID, account_id: UUID) -> bool:
    return (
        db.scalar(
            select(AIRecommendation.id).where(
                AIRecommendation.tenant_id == tenant_id,
                AIRecommendation.entity_type == "account",
                AIRecommendation.entity_id == str(account_id),
                AIRecommendation.kind == "research",
                AIRecommendation.deleted_at.is_(None),
            )
        )
        is not None
    )
