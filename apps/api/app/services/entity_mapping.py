import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval
from app.models.crm import Account, Customer
from app.models.post_sale import Contract
from app.models.signals import ExternalEntityMapping
from app.services.audit import emit_event, write_audit


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def get_mapping(
    db: Session,
    *,
    tenant_id: UUID,
    provider: str,
    entity_type: str,
    external_id: str,
) -> ExternalEntityMapping | None:
    if not external_id:
        return None
    return db.scalar(
        select(ExternalEntityMapping).where(
            ExternalEntityMapping.tenant_id == tenant_id,
            ExternalEntityMapping.provider == provider,
            ExternalEntityMapping.entity_type == entity_type,
            ExternalEntityMapping.external_id == str(external_id),
            ExternalEntityMapping.deleted_at.is_(None),
        )
    )


def upsert_mapping(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    provider: str,
    entity_type: str,
    external_id: str,
    internal_entity_type: str = "",
    internal_entity_id: str = "",
    status: str = "pending",
    confidence: int = 0,
    evidence: dict | None = None,
) -> ExternalEntityMapping:
    row = get_mapping(db, tenant_id=tenant_id, provider=provider, entity_type=entity_type, external_id=external_id)
    if row is None:
        row = ExternalEntityMapping(
            tenant_id=tenant_id,
            created_by=actor_id,
            provider=provider,
            entity_type=entity_type,
            external_id=str(external_id),
        )
        db.add(row)
    row.internal_entity_type = internal_entity_type or row.internal_entity_type
    row.internal_entity_id = internal_entity_id or row.internal_entity_id
    row.status = status
    row.confidence = confidence
    row.evidence_json = json.dumps(evidence or {}, default=str)[:4000]
    if status == "confirmed":
        row.last_verified_at = datetime.now(UTC)
    db.flush()
    return row


def confirm_mapping(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    mapping: ExternalEntityMapping,
    internal_entity_type: str | None = None,
    internal_entity_id: str | None = None,
) -> ExternalEntityMapping:
    if internal_entity_type:
        mapping.internal_entity_type = internal_entity_type
    if internal_entity_id:
        mapping.internal_entity_id = internal_entity_id
    mapping.status = "confirmed"
    mapping.last_verified_at = datetime.now(UTC)
    mapping.confidence = max(mapping.confidence, 95)
    emit_event(
        db,
        tenant_id=tenant_id,
        event_type="mapping.confirmed",
        entity_type=mapping.internal_entity_type or "mapping",
        entity_id=mapping.internal_entity_id or str(mapping.id),
        payload={"mapping_id": str(mapping.id), "provider": mapping.provider},
    )
    _ = actor_id
    return mapping


def ignore_mapping(db: Session, *, mapping: ExternalEntityMapping) -> ExternalEntityMapping:
    mapping.status = "ignored"
    return mapping


def unlink_mapping(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    mapping: ExternalEntityMapping,
) -> ExternalEntityMapping:
    previous = {"internal_entity_id": mapping.internal_entity_id, "status": mapping.status}
    customer_id = mapping.internal_entity_id
    mapping.status = "unlinked"
    mapping.internal_entity_id = ""
    # Circular: customer_intelligence -> ingest -> entity_mapping.
    from app.services.customer_intelligence import refresh_customer_intelligence

    write_audit(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="mapping.unlink",
        entity_type="external_entity_mapping",
        entity_id=str(mapping.id),
        before=previous,
        after={"status": "unlinked"},
    )
    if customer_id:
        try:
            customer = db.get(Customer, UUID(customer_id))
        except ValueError:
            customer = None
        if customer is not None and customer.tenant_id == tenant_id:
            refresh_customer_intelligence(db, tenant_id=tenant_id, actor_id=actor_id, customer=customer)
    return mapping


def _customer_for_account(db: Session, tenant_id: UUID, account_id: UUID) -> Customer | None:
    return db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.account_id == account_id,
            Customer.deleted_at.is_(None),
        )
    )


def _queue_mapping_approval(db: Session, *, tenant_id: UUID, actor_id: UUID | None, mapping: ExternalEntityMapping) -> None:
    key = f"mapping.confirm:{mapping.id}"
    existing = db.scalar(
        select(AIApproval).where(
            AIApproval.tenant_id == tenant_id,
            AIApproval.idempotency_key == key,
            AIApproval.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    db.add(
        AIApproval(
            tenant_id=tenant_id,
            created_by=actor_id,
            action_level=1,
            action_type="mapping.confirm",
            title=f"Confirm {mapping.provider} {mapping.entity_type} {mapping.external_id}",
            payload_json=json.dumps(
                {
                    "mapping_id": str(mapping.id),
                    "provider": mapping.provider,
                    "external_id": mapping.external_id,
                    "suggested_entity_type": mapping.internal_entity_type,
                    "suggested_entity_id": mapping.internal_entity_id,
                    "why": "Fuzzy or incomplete identity match. Confirm before live scoring.",
                    "evidence": mapping.evidence_json,
                }
            ),
            status="pending",
            entity_type="mapping",
            entity_id=str(mapping.id),
            idempotency_key=key,
        )
    )


def resolve_customer(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    provider: str,
    payload: dict,
) -> Customer | None:
    """Resolve a customer without trusting body tenant_id or an unmapped customer_id."""
    for entity_type, key in (
        ("customer", "customer_external_id"),
        ("account", "account_external_id"),
        ("account", "external_account_id"),
        ("contract", "contract_external_id"),
        ("billing", "billing_account_id"),
        ("invoice", "invoice_external_id"),
        ("ticket", "ticket_external_id"),
    ):
        external_id = str(payload.get(key) or "")
        if not external_id:
            continue
        mapping = get_mapping(db, tenant_id=tenant_id, provider=provider, entity_type=entity_type, external_id=external_id)
        if mapping is None or mapping.status != "confirmed" or not mapping.internal_entity_id:
            mapping = db.scalar(
                select(ExternalEntityMapping).where(
                    ExternalEntityMapping.tenant_id == tenant_id,
                    ExternalEntityMapping.entity_type == entity_type,
                    ExternalEntityMapping.external_id == str(external_id),
                    ExternalEntityMapping.status == "confirmed",
                    ExternalEntityMapping.deleted_at.is_(None),
                )
            )
        if mapping is None or mapping.status != "confirmed" or not mapping.internal_entity_id:
            continue
        if mapping.provider != provider:
            upsert_mapping(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                provider=provider,
                entity_type=entity_type,
                external_id=external_id,
                internal_entity_type=mapping.internal_entity_type,
                internal_entity_id=mapping.internal_entity_id,
                status="confirmed",
                confidence=mapping.confidence,
                evidence={"method": "confirmed_peer", "source_provider": mapping.provider},
            )
        if mapping.internal_entity_type == "customer":
            row = db.scalar(
                select(Customer).where(
                    Customer.tenant_id == tenant_id,
                    Customer.id == UUID(mapping.internal_entity_id),
                    Customer.deleted_at.is_(None),
                )
            )
            if row is not None:
                return row
        if mapping.internal_entity_type == "account":
            found = _customer_for_account(db, tenant_id, UUID(mapping.internal_entity_id))
            if found is not None:
                return found

    domain = _norm(payload.get("domain") or payload.get("account_domain") or payload.get("email_domain"))
    if "@" in domain:
        domain = domain.split("@")[-1]
    if domain:
        account = db.scalar(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.domain == domain,
                Account.deleted_at.is_(None),
            )
        )
        if account is not None:
            customer = _customer_for_account(db, tenant_id, account.id)
            external_id = str(payload.get("account_external_id") or payload.get("customer_external_id") or domain)
            if customer is not None and external_id:
                upsert_mapping(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    provider=provider,
                    entity_type="account",
                    external_id=external_id,
                    internal_entity_type="customer",
                    internal_entity_id=str(customer.id),
                    status="confirmed",
                    confidence=90,
                    evidence={"method": "domain", "domain": domain},
                )
            return customer

    contract_ref = str(payload.get("contract_id") or payload.get("billing_account_id") or "")
    try:
        cid = UUID(contract_ref) if contract_ref else None
    except ValueError:
        cid = None
    if cid is not None:
        contract = db.scalar(
            select(Contract).where(
                Contract.tenant_id == tenant_id,
                Contract.id == cid,
                Contract.deleted_at.is_(None),
            )
        )
        if contract is not None:
            return db.scalar(
                select(Customer).where(
                    Customer.tenant_id == tenant_id,
                    Customer.id == contract.customer_id,
                    Customer.deleted_at.is_(None),
                )
            )

    name = str(payload.get("account_name") or payload.get("company_name") or "").strip()
    if name:
        accounts = db.scalars(
            select(Account).where(Account.tenant_id == tenant_id, Account.deleted_at.is_(None), Account.name.ilike(f"%{name}%"))
        ).all()
        if len(accounts) == 1:
            customer = _customer_for_account(db, tenant_id, accounts[0].id)
            external_id = str(payload.get("account_external_id") or payload.get("customer_external_id") or name)
            if customer is not None and external_id:
                mapping = upsert_mapping(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    provider=provider,
                    entity_type="account",
                    external_id=external_id,
                    internal_entity_type="customer",
                    internal_entity_id=str(customer.id),
                    status="pending",
                    confidence=40,
                    evidence={"method": "fuzzy_name", "name": name, "account_id": str(accounts[0].id)},
                )
                _queue_mapping_approval(db, tenant_id=tenant_id, actor_id=actor_id, mapping=mapping)
            return None

    body_customer = str(payload.get("customer_id") or "")
    if body_customer:
        mapped = get_mapping(
            db,
            tenant_id=tenant_id,
            provider=provider,
            entity_type="customer",
            external_id=body_customer,
        )
        if mapped is not None and mapped.status == "confirmed" and mapped.internal_entity_id:
            try:
                return db.scalar(
                    select(Customer).where(
                        Customer.tenant_id == tenant_id,
                        Customer.id == UUID(mapped.internal_entity_id),
                        Customer.deleted_at.is_(None),
                    )
                )
            except ValueError:
                return None
    return None


def list_mappings(db: Session, tenant_id: UUID, *, status: str | None = None) -> list[ExternalEntityMapping]:
    stmt = select(ExternalEntityMapping).where(
        ExternalEntityMapping.tenant_id == tenant_id,
        ExternalEntityMapping.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(ExternalEntityMapping.status == status)
    return list(db.scalars(stmt.order_by(ExternalEntityMapping.created_at.desc())).all())
