import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import MockLLMProvider, NotConfiguredLLMProvider, get_llm_provider
from app.ai.runtime import research_account
from app.models.ai import AIRecommendation
from app.models.autonomy import AutomationIdempotencyKey, AutonomousRun, AutonomousRunStep, AutopilotSettings
from app.models.crm import Lead
from app.models.identity import DomainEvent, User
from app.models.lifecycle import Sequence, SequenceEnrollment, SequenceStep
from app.services.assessment import Fact
from app.services.audit import emit_event
from app.services.automation_state import get_state, is_entity_paused, upsert_state
from app.services.autopilot_settings import get_or_create_settings, in_quiet_hours
from app.services.crm import add_activity
from app.services.demo_guard import external_execution_block
from app.services.discovery import assign_discovered_lead, record_discovery_gap
from app.services.enrichment import enrich_lead
from app.services.external_hold import hold_stale_external_work
from app.services.idempotency import claim_key, remember_result
from app.services.inbox import handle_email_received
from app.services.lifecycle import enroll_sequence
from app.services.nba import generate_for_lead
from app.services.purchase_followthrough import PURCHASE_EVENTS, reconcile_purchase_event
from app.services.qualification import qualify_lead
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
    "MEETING_SCHEDULED",
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
    running = status == "running"
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
        finished_at=None if running else now,
        lease_owner="worker" if running else "",
        lease_until=now + timedelta(minutes=5) if running else None,
        outcome="" if running else status,
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


def select_sequence(db: Session, tenant_id: UUID, lead: Lead | None = None) -> Sequence | None:
    from app.services.journey_engine import select_activated_sequence

    return select_activated_sequence(db, tenant_id, lead)


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
    from app.services.assessment import assess_and_store, latest_decision
    from app.services.journey_engine import block_evaluation, evaluation_key, mark_execution

    assessment = latest_decision(db, tenant_id=tenant_id, lead_id=lead.id)
    if assessment is None:
        assess_and_store(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            settings=settings,
            correlation_id=correlation_id,
        )
        assessment = latest_decision(db, tenant_id=tenant_id, lead_id=lead.id)
    if assessment is not None and assessment.response_eligible and lead.source != "ai_discovery":
        from app.services.acknowledgement import prepare_acknowledgement

        return prepare_acknowledgement(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, settings=settings, run=run)
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
        mark_execution(
            db,
            tenant_id=tenant_id,
            entity_id=str(lead.id),
            execution_status="blocked",
            business_state="disqualified",
            resume_step="outreach",
            evaluation=block_evaluation(db, tenant_id=tenant_id, lead=lead, blocked_reason="Lead has opted out"),
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
        mark_execution(
            db,
            tenant_id=tenant_id,
            entity_id=str(lead.id),
            execution_status="blocked",
            business_state="assessed",
            resume_step="outreach",
            evaluation=block_evaluation(db, tenant_id=tenant_id, lead=lead, blocked_reason="Lead has no consent"),
        )
        return {"status": "BLOCKED", "reason": "Lead has no consent"}
    state = get_state(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id))
    if state is not None and state.last_action == "wrong_person":
        return {"status": "BLOCKED", "reason": "wrong_person"}
    if state is not None and (state.paused_at is not None or state.state == "PAUSED" or state.last_action == "out_of_office"):
        return {"status": "BLOCKED", "reason": "paused"}
    if assessment is None or not assessment.outbound_eligible:
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="outreach_blocked",
            next_action="review_assessment",
            blocked_reason="assessment does not permit outbound",
            run_id=run.id,
        )
        mark_execution(
            db,
            tenant_id=tenant_id,
            entity_id=str(lead.id),
            execution_status="blocked",
            business_state="assessed",
            resume_step="outreach",
            evaluation=block_evaluation(db, tenant_id=tenant_id, lead=lead, blocked_reason="assessment does not permit outbound"),
        )
        return {"status": "BLOCKED", "reason": "assessment does not permit outbound"}
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
    from app.services.grants import send_authorization
    from app.services.journey_engine import open_configuration_exception

    decision = send_authorization(db, tenant_id=tenant_id, settings=settings, action_type="sequence.email.send")
    if decision == "blocked":
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="grant_required",
            next_action="configure_grant",
            blocked_reason="scoped_grant_required",
            run_id=run.id,
        )
        mark_execution(
            db,
            tenant_id=tenant_id,
            entity_id=str(lead.id),
            execution_status="blocked",
            business_state="qualified",
            resume_step="outreach",
            evaluation=block_evaluation(db, tenant_id=tenant_id, lead=lead, blocked_reason="scoped_grant_required"),
        )
        return {"status": "BLOCKED", "reason": "scoped_grant_required"}
    sequence = select_sequence(db, tenant_id, lead)
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
        open_configuration_exception(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            reason="no_activated_sequence",
            run_id=run.id,
        )
        return {"status": "BLOCKED", "reason": "no_sequence"}
    try:
        enrollment = enroll_sequence(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            sequence=sequence,
            lead=lead,
            run_id=run.id,
            actor_type="ai",
            authorization=decision,
        )
    except HTTPException as exc:
        if exc.status_code != 409 or not str(exc.detail).startswith("Product configuration:"):
            raise
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="product_configuration",
            next_action="choose_operating_plan",
            blocked_reason=str(exc.detail),
            run_id=run.id,
        )
        return {"status": "BLOCKED", "reason": "product_not_selected", "detail": str(exc.detail)}
    waiting = decision != "execute"
    upsert_state(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        entity_type="lead",
        entity_id=str(lead.id),
        state="OUTREACH_APPROVAL_PENDING" if waiting else "READY_FOR_OUTREACH",
        last_action="enroll_sequence",
        next_action="approve_send" if waiting else "deliver",
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
        status="WAITING_FOR_APPROVAL" if waiting else "QUEUED",
        detail={"sequence_id": str(sequence.id), "enrollment_id": str(enrollment.id), "authorization": decision},
        entity_type="lead",
        entity_id=str(lead.id),
        idempotency_key=f"enroll:{lead.id}:{sequence.id}",
    )
    mark_execution(
        db,
        tenant_id=tenant_id,
        entity_id=str(lead.id),
        execution_status="waiting" if waiting else "queued",
        business_state="engaging",
        evaluation=evaluation_key(lead),
    )
    return {
        "status": "WAITING_FOR_APPROVAL" if waiting else "QUEUED",
        "sequence_id": str(sequence.id),
        "enrollment_id": str(enrollment.id),
    }


def run_lead_intake(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    lead: Lead,
    correlation_id: str = "",
    from_step: str = "enrich",
) -> dict:
    from app.services.journey_engine import block_evaluation, mark_execution

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
        if existing_state and existing_state.state in {"BLOCKED", "PAUSED"}:
            current = block_evaluation(
                db,
                tenant_id=tenant_id,
                lead=lead,
                blocked_reason=existing_state.blocked_reason or "",
            )
            if existing_state.evaluation_key and existing_state.evaluation_key == current:
                return {"status": "SKIPPED", "reason": "still_blocked", "run_id": str(run.id)}
        elif existing_state and _rank(existing_state.state) >= _rank("READY_FOR_OUTREACH"):
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
    if lead.source == "ai_discovery" and lead.owner_id is None:
        assign_discovered_lead(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead, correlation_id=correlation_id)
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
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                lead=lead,
                correlation_id=correlation_id,
                allow_simulated=lead.source != "ai_discovery",
            )
            incomplete = bool(detail.get("incomplete")) if isinstance(detail, dict) else False
            _add_step(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                run=run,
                name="enrich",
                position=position,
                status="incomplete" if incomplete else "completed",
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
        observed = []
        if lead.source == "ai_discovery" and (lead.title or "").strip():
            observed.append(
                Fact(
                    "persona",
                    "observed",
                    lead.title.strip(),
                    "present",
                    (lead.discovery_provider or "discovery")[:80],
                    lead.title.strip()[:500],
                )
            )
        qualification = qualify_lead(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            settings=settings,
            correlation_id=correlation_id,
            fact_overrides=observed,
        )
        qualified = bool(qualification["qualified"])
        held = bool(qualification.get("held_for_response"))
        step_status = "completed" if qualified else "waiting" if held else "BLOCKED"
        next_action = "research" if qualified else str(qualification.get("next_action") or "")
        entity_state = "QUALIFIED" if qualified else "WAITING_FOR_CUSTOMER" if held else "BLOCKED"
        _add_step(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run=run,
            name="qualify",
            position=position,
            status=step_status,
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
            state=entity_state,
            last_action="qualify",
            next_action=next_action,
            blocked_reason="" if qualified or held else "; ".join(qualification.get("reasons", [])),
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
        research_status = "completed"
        if fresh:
            model = get_llm_provider(db, tenant_id)
            if isinstance(model, (MockLLMProvider, NotConfiguredLLMProvider)):
                brief = {
                    "provider": "unsupported",
                    "is_mock": True,
                    "reason": "Account research is not available. No brief was invented.",
                }
                research_status = "incomplete"
            else:
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
            status=research_status,
            detail={"provider": brief.get("provider"), "is_mock": brief.get("is_mock"), "skipped": not fresh, "reason": brief.get("reason", "")},
            entity_type="account",
            entity_id=str(lead.account_id),
            idempotency_key=f"research:{lead.account_id}",
        )
        position += 1

    response_eligible = bool(qualification.get("response_eligible")) and lead.source != "ai_discovery" if "qualification" in locals() else False
    meeting_eligible = bool(qualification.get("meeting_eligible")) if "qualification" in locals() else False
    if response_eligible:
        from app.services.acknowledgement import prepare_acknowledgement

        result["acknowledgement"] = prepare_acknowledgement(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            settings=settings,
            run=run,
        )
    if meeting_eligible:
        from app.services.calendar_booking import offer_discovery_meeting

        result["meeting"] = offer_discovery_meeting(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            run_id=run.id,
        )
    if qualified and not response_eligible:
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
            run_status = "blocked"
        run.business_state = run_status
        _finish_run(run, summary, run_status)
        remember_result(key_row, str(run.id))
        return result

    if lead.source == "ai_discovery":
        action = record_discovery_gap(db, tenant_id=tenant_id, actor_id=actor_id, lead=lead)
        reason = "Lead has no consent" if not lead.consent_email else "assessment does not permit outbound"
        upsert_state(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            state="BLOCKED",
            last_action="discovery_follow_through",
            next_action="record_channel_permission" if not lead.consent_email else "review_assessment",
            blocked_reason=reason,
            run_id=run.id,
        )
        mark_execution(
            db,
            tenant_id=tenant_id,
            entity_id=str(lead.id),
            execution_status="blocked",
            business_state="assessed",
            resume_step="outreach",
            evaluation=block_evaluation(db, tenant_id=tenant_id, lead=lead, blocked_reason=reason),
        )
        result["discovery_gap"] = action

    ack = result.get("acknowledgement") or {}
    meeting = result.get("meeting") or {}
    if meeting.get("status") == "waiting_for_configuration":
        finish_status = "waiting_for_configuration"
    elif meeting_eligible:
        finish_status = "waiting_for_customer"
    elif ack.get("status") == "sent":
        finish_status = "completed"
    elif ack.get("status") == "waiting_for_approval":
        finish_status = "WAITING_FOR_APPROVAL"
    elif ack.get("status") == "waiting_for_configuration":
        finish_status = "waiting_for_configuration"
    elif ack.get("status") == "waiting_for_authorization":
        finish_status = "waiting_for_authorization"
    elif ack.get("status") == "unknown":
        finish_status = "running"
    else:
        held = bool(qualification.get("held_for_response")) if "qualification" in locals() else False
        finish_status = "waiting_for_customer" if held else "blocked"
    run.business_state = finish_status
    if finish_status == "running":
        run.status = "running"
        run.summary = f"Intake acknowledgement outcome is unknown for {lead.email or lead.id}."
    else:
        _finish_run(run, f"Intake {finish_status} for {lead.email or lead.id}.", finish_status)
    remember_result(key_row, str(run.id))
    return result


def handle_event(db: Session, event: DomainEvent, *, actor_id: UUID | None = None) -> str:
    tenant_id = event.tenant_id
    actor = _actor(db, tenant_id, actor_id)
    if event.event_type in PURCHASE_EVENTS:
        return reconcile_purchase_event(db, event, actor_id=actor)
    settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor)
    if not settings.enabled:
        return "skipped_disabled"
    event_type = event.event_type
    from app.services.post_sale import POST_SALE_EVENTS, handle_post_sale_event

    if event_type in POST_SALE_EVENTS:
        return handle_post_sale_event(db, event, actor_id=actor)
    if event_type in {
        "lead.created",
        "lead.enriched",
        "lead.scored",
        "lead.qualified",
        "lead.disqualified",
        "lead.ready_for_outreach",
        "email.sent",
        "email.received",
        "meeting.booked",
        "meeting.created",
        "lead.sales_qualified",
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
        if event_type == "email.sent":
            upsert_state(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                entity_type="lead",
                entity_id=str(lead.id),
                state="CONTACTED",
                last_action="email_sent",
                next_action="wait_for_reply",
                blocked_reason="",
            )
            return "contacted"
        if event_type == "email.received":
            payload = {}
            try:
                payload = json.loads(event.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            return handle_email_received(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                lead=lead,
                message_id=str(payload.get("message_id") or ""),
            )
        if event_type in {"meeting.booked", "meeting.created"}:
            upsert_state(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                entity_type="lead",
                entity_id=str(lead.id),
                state="MEETING_SCHEDULED",
                last_action="meeting_booked",
                next_action="prepare_meeting",
                blocked_reason="",
            )
            if lead.status != "meeting_scheduled":
                lead.status = "meeting_scheduled"
            qualify_lead(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                lead=lead,
                settings=settings,
                correlation_id=event.correlation_id,
            )
            return "meeting_booked"
        if event_type == "lead.sales_qualified":
            from app.services.assessment import handoff_sales_opportunity

            handoff_sales_opportunity(
                db,
                tenant_id=tenant_id,
                actor_id=actor,
                lead=lead,
                correlation_id=event.correlation_id,
            )
            return "sales_handoff"
        return "recorded"
    return "ignored"


def process_pending_events(
    db: Session,
    *,
    tenant_id: UUID | None = None,
    actor_id: UUID | None = None,
    limit: int = 200,
) -> int:
    from app.db.tenant_context import supports_rls
    from app.db.tenant_jobs import run_per_tenant

    if tenant_id is None and supports_rls(db):
        return run_per_tenant(
            db,
            lambda tid: process_pending_events(db, tenant_id=tid, actor_id=actor_id, limit=limit),
        )
    from app.services.event_delivery import acknowledge, claim_next_event, fail_delivery

    hold_stale_external_work(db, tenant_id=tenant_id)
    db.flush()
    processed = 0
    while processed < limit:
        event = claim_next_event(db, tenant_id=tenant_id)
        if event is None:
            break
        try:
            handle_event(db, event, actor_id=actor_id)
            acknowledge(db, event, actor_id=actor_id)
        except Exception as exc:  # noqa: BLE001 — isolated per event
            fail_delivery(db, event, str(exc), actor_id=actor_id)
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
    hold_stale_external_work(db, tenant_id=tenant_id)
    db.flush()
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
        if step is None:
            enrollment.status = "blocked"
            continue
        lead = _load_lead(db, tenant_id, str(enrollment.lead_id))
        if lead is None or lead.opt_out or (step.action_type in {"email_draft", "email_send", "send"} and not lead.consent_email):
            continue
        if is_entity_paused(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id)):
            continue
        lead_state = get_state(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id))
        if lead_state is not None and lead_state.last_action == "wrong_person":
            continue
        if external_execution_block(db, tenant_id=tenant_id, action="sequence.email.send", recipient=lead.email or ""):
            continue
        from app.services.journey_engine import execute_due_step

        outcome = execute_due_step(db, tenant_id=tenant_id, actor_id=actor_id, enrollment=enrollment, step=step, lead=lead)
        if outcome == "email_queued":
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
