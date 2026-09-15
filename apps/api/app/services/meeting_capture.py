from __future__ import annotations

import json
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.funnel import MeetingCapture
from app.models.lifecycle import MeetingRecord
from app.providers.meeting_capture import UploadMeetingCaptureProvider, get_meeting_capture_provider
from app.services.audit import write_audit
from app.services.meeting_intelligence import apply_meeting_insights, extract_insights
from app.services.query import get_owned


def queue_recording_consent(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting: MeetingRecord,
) -> AIApproval:
    key = f"meeting.record:{meeting.id}"
    existing = db.scalar(
        select(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.idempotency_key == key,
            AIApproval.deleted_at.is_(None),
        )
    )
    if existing:
        return existing
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="meeting.record",
        title=f"Record meeting {meeting.title}",
        payload_json=json.dumps({"meeting_id": str(meeting.id)}),
        status="pending",
        entity_type="meeting",
        entity_id=str(meeting.id),
        idempotency_key=key,
    )
    db.add(approval)
    db.flush()
    return approval


def grant_recording_consent(db: Session, *, tenant_id: UUID, meeting_id: UUID) -> MeetingRecord:
    meeting = get_owned(db, MeetingRecord, tenant_id, meeting_id)
    meeting.recording_consent = True
    return meeting


def assert_recording_consent(meeting: MeetingRecord) -> None:
    if not meeting.recording_consent:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recording consent is required before a bot may join.")


def schedule_capture(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting: MeetingRecord,
    meeting_url: str,
) -> MeetingCapture:
    assert_recording_consent(meeting)
    provider = get_meeting_capture_provider(db, tenant_id)
    result = provider.schedule_bot(meeting_url=meeting_url, title=meeting.title)
    row = MeetingCapture(
        tenant_id=tenant_id,
        created_by=actor_id,
        meeting_record_id=meeting.id,
        provider=result.provider,
        provider_bot_id=result.bot_id or f"pending:{uuid4()}",
        status=result.status or ("scheduled" if result.ok else "failed"),
        meeting_url=meeting_url,
        consent_evidence_json=json.dumps({"recording_consent": True, "meeting_id": str(meeting.id)}),
        last_error=result.reason,
    )
    db.add(row)
    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="meeting.capture_requested",
        entity_type="meeting",
        entity_id=str(meeting.id),
        after={"provider": result.provider, "ok": result.ok},
    )
    db.flush()
    return row


def refresh_capture(db: Session, *, tenant_id: UUID, actor_id: UUID, capture: MeetingCapture) -> MeetingCapture:
    provider = get_meeting_capture_provider(db, tenant_id)
    if not capture.provider_bot_id or capture.provider_bot_id.startswith("pending:"):
        return capture
    result = provider.fetch(bot_id=capture.provider_bot_id)
    capture.status = result.status or capture.status
    capture.recording_ref = result.recording_ref
    capture.last_error = result.reason
    if result.transcript:
        capture.transcript_ref = capture.provider_bot_id
    if result.transcript and capture.meeting_record_id:
        meeting = get_owned(db, MeetingRecord, tenant_id, capture.meeting_record_id)
        meeting.transcript = result.transcript
        insights = extract_insights(transcript=result.transcript, db=db, tenant_id=tenant_id)
        apply_meeting_insights(db, tenant_id=tenant_id, actor_id=actor_id, meeting=meeting, insights=insights)
    return capture


def ingest_manual_transcript(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting: MeetingRecord,
    transcript: str,
) -> MeetingRecord:
    meeting.transcript = transcript.strip()
    db.add(
        MeetingCapture(
            tenant_id=tenant_id,
            created_by=actor_id,
            meeting_record_id=meeting.id,
            provider="manual",
            provider_bot_id=f"manual:{meeting.id}:{uuid4().hex[:8]}",
            status="completed",
            consent_evidence_json=json.dumps({"recording_consent": meeting.recording_consent}),
        )
    )
    insights = extract_insights(transcript=meeting.transcript, db=db, tenant_id=tenant_id)
    apply_meeting_insights(db, tenant_id=tenant_id, actor_id=actor_id, meeting=meeting, insights=insights)
    return meeting


def ingest_upload(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    meeting: MeetingRecord,
    filename: str,
    data: bytes,
) -> MeetingRecord:
    assert_recording_consent(meeting)
    provider = UploadMeetingCaptureProvider()
    result = provider.transcribe(filename=filename, data=data)
    if not result.ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.reason)
    meeting.transcript = result.transcript
    db.add(
        MeetingCapture(
            tenant_id=tenant_id,
            created_by=actor_id,
            meeting_record_id=meeting.id,
            provider="upload-stt",
            provider_bot_id=f"upload:{meeting.id}:{uuid4().hex[:8]}",
            status="completed",
            consent_evidence_json=json.dumps({"recording_consent": True}),
        )
    )
    insights = extract_insights(transcript=result.transcript, db=db, tenant_id=tenant_id)
    apply_meeting_insights(db, tenant_id=tenant_id, actor_id=actor_id, meeting=meeting, insights=insights)
    return meeting
