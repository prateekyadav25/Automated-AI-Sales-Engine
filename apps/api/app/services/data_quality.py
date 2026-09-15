from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.crm import Account, Customer, Lead, Opportunity
from app.models.pilot import DataQualityIssue
from app.models.post_sale import Contract
from app.models.signals import MLFeatureSnapshot, MLOutcomeLabel
from app.services.ml.catalog import TASKS
from app.services.ml.readiness import list_readiness


def _upsert_issue(db: Session, *, tenant_id: UUID, entity_type: str, entity_id: str, code: str, detail: str) -> None:
    row = db.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.tenant_id == tenant_id,
            DataQualityIssue.entity_type == entity_type,
            DataQualityIssue.entity_id == entity_id,
            DataQualityIssue.code == code,
            DataQualityIssue.deleted_at.is_(None),
        )
    )
    if row is None:
        row = DataQualityIssue(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            code=code,
            detail=detail,
        )
        db.add(row)
    else:
        row.status = "open"
        row.detail = detail


def refresh_quality(db: Session, *, tenant_id: UUID) -> list[dict]:
    leads = db.scalars(select(Lead).where(Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None))).all()
    for lead in leads:
        if not lead.account_id:
            _upsert_issue(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id), code="missing_account", detail="Lead has no account")
        if not lead.source:
            _upsert_issue(db, tenant_id=tenant_id, entity_type="lead", entity_id=str(lead.id), code="missing_source", detail="Lead has no source")
    accounts = db.scalars(select(Account).where(Account.tenant_id == tenant_id, Account.deleted_at.is_(None))).all()
    for account in accounts:
        if not account.industry:
            _upsert_issue(db, tenant_id=tenant_id, entity_type="account", entity_id=str(account.id), code="missing_industry", detail="Account industry is empty")
    opps = db.scalars(select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None))).all()
    for opp in opps:
        if opp.stage == "closed_lost" and not opp.loss_reason:
            _upsert_issue(db, tenant_id=tenant_id, entity_type="opportunity", entity_id=str(opp.id), code="missing_close_outcome", detail="Closed lost without reason")
        snap = db.scalar(
            select(MLFeatureSnapshot).where(
                MLFeatureSnapshot.tenant_id == tenant_id,
                MLFeatureSnapshot.entity_type == "opportunity",
                MLFeatureSnapshot.entity_id == str(opp.id),
                MLFeatureSnapshot.task_key == "OPPORTUNITY_WIN",
                MLFeatureSnapshot.deleted_at.is_(None),
            )
        )
        if snap is None:
            _upsert_issue(
                db,
                tenant_id=tenant_id,
                entity_type="opportunity",
                entity_id=str(opp.id),
                code="missing_win_snapshot",
                detail="Opportunity has no OPPORTUNITY_WIN snapshot",
            )
    customers = db.scalars(select(Customer).where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None))).all()
    for customer in customers:
        contract = db.scalar(select(Contract).where(Contract.tenant_id == tenant_id, Contract.customer_id == customer.id, Contract.deleted_at.is_(None)))
        if contract is None:
            _upsert_issue(db, tenant_id=tenant_id, entity_type="customer", entity_id=str(customer.id), code="missing_contract", detail="Customer has no contract")
        if customer.status == "churned" and not customer.churn_reason:
            _upsert_issue(db, tenant_id=tenant_id, entity_type="customer", entity_id=str(customer.id), code="missing_customer_outcome", detail="Churned without reason")
    db.flush()
    rows = db.scalars(select(DataQualityIssue).where(DataQualityIssue.tenant_id == tenant_id, DataQualityIssue.deleted_at.is_(None), DataQualityIssue.status == "open")).all()
    return [{"entity_type": row.entity_type, "entity_id": row.entity_id, "code": row.code, "detail": row.detail} for row in rows]


def outcome_completeness(db: Session, *, tenant_id: UUID) -> list[dict]:
    reports = []
    for task_key, spec in TASKS.items():
        eligible = 0
        if spec["entity_type"] == "lead":
            eligible = int(db.scalar(select(func.count()).select_from(Lead).where(Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None))) or 0)
        elif spec["entity_type"] == "opportunity":
            eligible = int(db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None))) or 0)
        elif spec["entity_type"] == "customer":
            eligible = int(db.scalar(select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None))) or 0)
        mature = int(
            db.scalar(
                select(func.count())
                .select_from(MLOutcomeLabel)
                .where(
                    MLOutcomeLabel.tenant_id == tenant_id,
                    MLOutcomeLabel.task_key == task_key,
                    MLOutcomeLabel.label_status.in_(["POSITIVE", "NEGATIVE"]),
                    MLOutcomeLabel.deleted_at.is_(None),
                )
            )
            or 0
        )
        reports.append(
            {
                "task_key": task_key,
                "eligible": eligible,
                "mature": mature,
                "completeness": round(mature / eligible, 4) if eligible else 0.0,
            }
        )
    return reports


def learning_progress(db: Session, *, tenant_id: UUID) -> list[dict]:
    readiness = list_readiness(db, tenant_id=tenant_id)
    complete = {row["task_key"]: row for row in outcome_completeness(db, tenant_id=tenant_id)}
    merged = []
    for row in readiness:
        extra = complete.get(row["task_key"], {})
        merged.append({**row, "completeness": extra.get("completeness", 0), "eligible": extra.get("eligible", 0)})
    return merged
