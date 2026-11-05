"""Retiring the seeded sample companies leaves real records and other workspaces alone."""

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.session import get_session
from app.models.ai import AIApproval
from app.models.autonomy import AutomationIdempotencyKey
from app.models.content import ContentDraft
from app.models.crm import Account, Lead, Opportunity, Task
from app.models.identity import AuditLog
from app.models.lifecycle import DealInsight
from app.models.market import TriggerEvent
from app.models.social import SocialPost
from app.seed_showroom import SHOWROOM_DRAFTS, SHOWROOM_POST
from app.services.sample_data import retire_sample_data
from tests.growth_support import user


def test_sample_companies_retire_with_everything_linked_to_them(client: TestClient) -> None:
    _ = client
    db = get_session()
    try:
        admin = user(db)
        tenant_id = admin.tenant_id
        meridian = db.scalar(select(Account).where(Account.tenant_id == tenant_id, Account.name == "Meridian Bank"))
        assert meridian is not None and meridian.deleted_at is None
        sample_lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.email.like("%.example")))
        assert sample_lead is not None
        real = Account(tenant_id=tenant_id, created_by=admin.id, name="Real Buyer Pvt Ltd", domain="realbuyer.in")
        db.add(real)
        db.flush()
        real_task = Task(tenant_id=tenant_id, created_by=admin.id, title="Call the real buyer", entity_type="account", entity_id=str(real.id))
        sample_task = Task(tenant_id=tenant_id, created_by=admin.id, title="Call Meridian", entity_type="account", entity_id=str(meridian.id))
        named = AIApproval(
            tenant_id=tenant_id,
            created_by=admin.id,
            action_level=2,
            action_type="email.send",
            title="Introduction",
            payload_json=json.dumps({"lead_id": str(sample_lead.id)}),
            status="pending",
        )
        claim = AutomationIdempotencyKey(
            tenant_id=tenant_id,
            created_by=admin.id,
            key=f"sample_retirement_test:{sample_lead.id}",
            workflow="lead_intake",
            entity_id=str(sample_lead.id),
            action_type="intake",
        )
        db.add_all([real_task, sample_task, named, claim])
        db.flush()
        northline = user(db, "admin@northline.demo")
        northline_samples = db.scalar(
            select(func.count(Account.id)).where(Account.tenant_id == northline.tenant_id, Account.deleted_at.is_(None))
        )

        counts = retire_sample_data(db, tenant_id=tenant_id, now=datetime.now(UTC))

        assert counts["accounts"] >= 7
        assert db.scalar(
            select(func.count(Account.id)).where(
                Account.tenant_id == tenant_id, Account.deleted_at.is_(None), Account.domain.like("%.example")
            )
        ) == 0
        for row in (meridian, sample_lead, real, real_task, sample_task, named, claim):
            db.refresh(row)
        assert claim.deleted_at is None
        assert meridian.deleted_at is not None and sample_lead.deleted_at is not None
        assert sample_task.deleted_at is not None
        assert named.deleted_at is not None and named.status == "rejected"
        assert real.deleted_at is None and real_task.deleted_at is None
        sample_opportunities = select(Opportunity.id).where(Opportunity.tenant_id == tenant_id, Opportunity.account_id == meridian.id)
        assert db.scalar(
            select(func.count(DealInsight.id)).where(DealInsight.opportunity_id.in_(sample_opportunities), DealInsight.deleted_at.is_(None))
        ) == 0
        assert db.scalar(
            select(func.count(TriggerEvent.id)).where(
                TriggerEvent.tenant_id == tenant_id, TriggerEvent.source == "seed", TriggerEvent.deleted_at.is_(None)
            )
        ) == 0
        showroom = [headline for _, _, headline, _, _ in SHOWROOM_DRAFTS]
        assert db.scalar(
            select(func.count(ContentDraft.id)).where(
                ContentDraft.tenant_id == tenant_id, ContentDraft.headline.in_(showroom), ContentDraft.deleted_at.is_(None)
            )
        ) == 0
        assert db.scalar(
            select(func.count(SocialPost.id)).where(
                SocialPost.tenant_id == tenant_id, SocialPost.body == SHOWROOM_POST, SocialPost.deleted_at.is_(None)
            )
        ) == 0
        assert db.scalar(
            select(func.count(Account.id)).where(Account.tenant_id == northline.tenant_id, Account.deleted_at.is_(None))
        ) == northline_samples
        audited = db.scalars(
            select(AuditLog).where(AuditLog.tenant_id == tenant_id, AuditLog.action == "sample_data.retired")
        ).all()
        assert {row.entity_type for row in audited} >= {"accounts", "leads", "tasks", "ai_approvals"}
        assert all(row.actor_type == "system" for row in audited)

        assert retire_sample_data(db, tenant_id=tenant_id, now=datetime.now(UTC)) == {}
    finally:
        db.rollback()
        db.close()
