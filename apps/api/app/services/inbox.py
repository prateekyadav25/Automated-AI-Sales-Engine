import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_engine, get_session
from app.models.crm import Contact, Lead
from app.models.identity import User
from app.models.integrations import EmailMessage, ProviderAccount, ProviderInboxEvent
from app.models.lifecycle import Conversation
from app.providers.email import InboundEmail, get_email_provider
from app.services.audit import emit_event
from app.services.crm import add_activity
from app.services.email_send import find_or_create_thread
from app.services.provider_accounts import connected_google_account, mark_error, mark_success
from app.services.reply_intelligence import classify_reply
from app.services.reply_router import route_reply


def _match_lead(db: Session, tenant_id: UUID, inbound: InboundEmail) -> Lead | None:
    email = inbound.from_addr
    if "<" in email and ">" in email:
        email = email[email.index("<") + 1 : email.index(">")].strip()
    email = email.lower()
    if not email:
        return None
    lead = db.scalar(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.email == email,
            Lead.deleted_at.is_(None),
        )
    )
    if lead is not None:
        return lead
    contact = db.scalar(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.email == email,
            Contact.deleted_at.is_(None),
        )
    )
    if contact is None:
        return None
    return db.scalar(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.contact_id == contact.id,
            Lead.deleted_at.is_(None),
        )
    )


def record_inbox_event(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    provider: str,
    external_id: str,
    payload: dict,
) -> ProviderInboxEvent:
    existing = db.scalar(
        select(ProviderInboxEvent).where(
            ProviderInboxEvent.tenant_id == tenant_id,
            ProviderInboxEvent.provider == provider,
            ProviderInboxEvent.external_id == external_id,
            ProviderInboxEvent.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    row = ProviderInboxEvent(
        tenant_id=tenant_id,
        created_by=actor_id,
        provider=provider,
        external_id=external_id,
        payload_json=json.dumps(payload, default=str),
        status="received",
        attempts=0,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        recovered = db.scalar(
            select(ProviderInboxEvent).where(
                ProviderInboxEvent.tenant_id == tenant_id,
                ProviderInboxEvent.provider == provider,
                ProviderInboxEvent.external_id == external_id,
                ProviderInboxEvent.deleted_at.is_(None),
            )
        )
        if recovered is None:
            raise
        return recovered
    return row


def persist_inbound(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    inbound: InboundEmail,
    provider: str,
) -> EmailMessage | None:
    existing = db.scalar(
        select(EmailMessage).where(
            EmailMessage.tenant_id == tenant_id,
            EmailMessage.provider == provider,
            EmailMessage.provider_message_id == inbound.provider_message_id,
            EmailMessage.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    lead = _match_lead(db, tenant_id, inbound)
    conversation = None
    if inbound.thread_id:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.provider_thread_id == inbound.thread_id,
                Conversation.deleted_at.is_(None),
            )
        )
    if conversation is None and lead is not None:
        conversation = find_or_create_thread(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            lead=lead,
            subject=inbound.subject,
            provider=provider,
            is_mock=provider.startswith("mock"),
            thread_id=inbound.thread_id,
        )
    if conversation is None:
        conversation = Conversation(
            tenant_id=tenant_id,
            created_by=actor_id,
            channel="email",
            subject=inbound.subject,
            status="open",
            consent=True,
            provider=provider,
            is_mock=provider.startswith("mock"),
            transcript=inbound.body_text,
            summary="Inbound thread",
            provider_thread_id=inbound.thread_id,
            lead_id=lead.id if lead else None,
        )
        db.add(conversation)
        db.flush()
    message = EmailMessage(
        tenant_id=tenant_id,
        created_by=actor_id,
        conversation_id=conversation.id,
        direction="inbound",
        from_addr=inbound.from_addr,
        to_addrs=json.dumps(inbound.to_addrs),
        subject=inbound.subject,
        body_text=inbound.body_text,
        provider=provider,
        provider_message_id=inbound.provider_message_id,
        provider_thread_id=inbound.thread_id,
        status="SENT",
        received_at=inbound.received_at,
        lead_id=lead.id if lead else None,
    )
    try:
        with db.begin_nested():
            db.add(message)
            conversation.status = "replied"
            conversation.transcript = ((conversation.transcript or "") + f"\n\nInbound: {inbound.body_text}").strip()
            conversation.summary = inbound.subject or conversation.summary
            db.flush()
    except IntegrityError:
        recovered = db.scalar(
            select(EmailMessage).where(
                EmailMessage.tenant_id == tenant_id,
                EmailMessage.provider == provider,
                EmailMessage.provider_message_id == inbound.provider_message_id,
                EmailMessage.deleted_at.is_(None),
            )
        )
        if recovered is None:
            raise
        return recovered
    if lead is not None:
        add_activity(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type="lead",
            entity_id=str(lead.id),
            activity_type="email",
            title="Inbound email received",
            body=inbound.subject,
            actor_type="ai",
        )
        emit_event(
            db,
            tenant_id=tenant_id,
            event_type="email.received",
            entity_type="lead",
            entity_id=str(lead.id),
            payload={"message_id": str(message.id), "provider_message_id": inbound.provider_message_id},
        )
    return message


def process_inbox_event(db: Session, event: ProviderInboxEvent, *, actor_id: UUID) -> str:
    if event.processed_at is not None:
        return "already"
    event.attempts += 1
    try:
        payload = json.loads(event.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
        event.status = "failed"
        event.error = "Invalid JSON payload"
        return "failed"
    try:
        if event.provider in {"usage", "support", "finance", "erp"}:
            from app.services.signal_ingest import ingest_inbox_event

            ingest_inbox_event(db, event, actor_id=actor_id, payload=payload if isinstance(payload, dict) else {})
        elif event.provider in {"twilio", "vapi", "exotel"}:
            from app.services.voice import apply_call_event

            apply_call_event(
                db,
                tenant_id=event.tenant_id,
                actor_id=actor_id,
                provider=event.provider,
                payload=payload if isinstance(payload, dict) else {},
            )
        else:
            inbound = InboundEmail(
                provider_message_id=str(payload.get("provider_message_id") or event.external_id),
                thread_id=str(payload.get("thread_id") or ""),
                from_addr=str(payload.get("from_addr") or ""),
                to_addrs=list(payload.get("to_addrs") or []),
                subject=str(payload.get("subject") or ""),
                body_text=str(payload.get("body_text") or ""),
                received_at=datetime.now(UTC),
                history_id=str(payload.get("history_id") or ""),
            )
            persist_inbound(db, tenant_id=event.tenant_id, actor_id=actor_id, inbound=inbound, provider=event.provider)
        event.processed_at = datetime.now(UTC)
        event.status = "processed"
        event.error = ""
        return "processed"
    except Exception as exc:  # noqa: BLE001
        event.status = "failed" if event.attempts < 5 else "dead_letter"
        event.error = str(exc)[:400]
        return event.status


def process_pending_inbox(db: Session, *, limit: int = 50) -> int:
    rows = db.scalars(
        select(ProviderInboxEvent)
        .where(
            ProviderInboxEvent.deleted_at.is_(None),
            ProviderInboxEvent.processed_at.is_(None),
            ProviderInboxEvent.status.in_(["received", "failed"]),
        )
        .limit(limit)
    ).all()
    count = 0
    for event in rows:
        actor_id = event.created_by
        if actor_id is None:
            user = db.scalar(select(User).where(User.tenant_id == event.tenant_id, User.is_active.is_(True)))
            if user is None:
                continue
            actor_id = user.id
        process_inbox_event(db, event, actor_id=actor_id)
        count += 1
    return count


def handle_email_received(db: Session, *, tenant_id: UUID, actor_id: UUID, lead: Lead, message_id: str) -> str:
    try:
        mid = UUID(message_id)
    except ValueError:
        return "bad_message"
    message = db.scalar(
        select(EmailMessage).where(
            EmailMessage.tenant_id == tenant_id,
            EmailMessage.id == mid,
            EmailMessage.deleted_at.is_(None),
        )
    )
    if message is None:
        return "missing_message"
    classification = classify_reply(subject=message.subject, body=message.body_text)
    message.classification = str(classification["category"])
    message.classification_json = json.dumps(classification, default=str)
    return route_reply(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        lead=lead,
        message=message,
        classification=classification,
    )


def sync_inbound_for_tenant(db: Session, *, tenant_id: UUID, actor_id: UUID) -> int:
    provider = get_email_provider(db, tenant_id)
    account: ProviderAccount | None = connected_google_account(db, tenant_id)
    history_id = account.last_history_id if account else ""
    try:
        inbound_rows = provider.list_since(history_id=history_id)
    except Exception as exc:  # noqa: BLE001
        if account is not None:
            mark_error(account, str(exc))
        return 0
    count = 0
    for inbound in inbound_rows:
        event = record_inbox_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            provider=provider.health().provider,
            external_id=inbound.provider_message_id or str(uuid4()),
            payload={
                "provider_message_id": inbound.provider_message_id,
                "thread_id": inbound.thread_id,
                "from_addr": inbound.from_addr,
                "to_addrs": inbound.to_addrs,
                "subject": inbound.subject,
                "body_text": inbound.body_text,
                "history_id": inbound.history_id,
            },
        )
        if event.processed_at is None:
            process_inbox_event(db, event, actor_id=actor_id)
            count += 1
        if account is not None and inbound.history_id:
            account.last_history_id = inbound.history_id
    if account is not None:
        account.last_sync_at = datetime.now(UTC)
        mark_success(account)
    return count


def sync_all_tenants() -> int:
    from app.db.tenant_jobs import run_per_tenant

    get_engine()
    db = get_session()
    try:
        def _one(tenant_id):
            user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)))
            if user is None:
                return 0
            return sync_inbound_for_tenant(db, tenant_id=tenant_id, actor_id=user.id)

        total = run_per_tenant(db, _one)
        db.commit()
        return total
    finally:
        db.close()
