import json
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.models.ai import AIApproval
from app.models.crm import Account, Customer, Lead, Opportunity, Renewal
from app.models.identity import Tenant, User
from app.models.integrations import EmailMessage, ProviderAction, ProviderInboxEvent
from app.models.lifecycle import OnboardingPlan
from app.models.post_sale import Contract, HandoffPackage
from app.services.autopilot_settings import get_or_create_settings
from app.services.crm import close_won
from app.services.dispatcher import dispatch_approval
from app.services.email_send import execute_email_send
from app.services.idempotency import claim_daily_slot, claim_key
from app.services.inbox import record_inbox_event

pytestmark = pytest.mark.postgres


def _url() -> str | None:
    return os.environ.get("POSTGRES_CONCURRENCY_URL") or os.environ.get("POSTGRES_RLS_ADMIN_URL")


@pytest.fixture(scope="module")
def pg() -> sessionmaker:
    url = _url()
    if not url:
        pytest.skip("POSTGRES_RLS_ADMIN_URL is not set")

    os.environ.setdefault("DATABASE_URL", url)
    os.environ.setdefault("DATABASE_ADMIN_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return factory


def _ids(db: Session) -> tuple:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == "agrayian")) or db.scalar(select(Tenant))
    user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.is_active.is_(True)))
    assert tenant and user
    return tenant.id, user.id


def test_two_workers_close_won_once(pg: sessionmaker) -> None:
    setup = pg()
    tenant_id, actor_id = _ids(setup)
    account = Account(tenant_id=tenant_id, created_by=actor_id, name=f"Conc {uuid4().hex[:8]}")
    setup.add(account)
    setup.flush()
    opp = Opportunity(
        tenant_id=tenant_id,
        created_by=actor_id,
        account_id=account.id,
        name="Concurrent close",
        stage="commit",
        amount=Decimal("10000"),
        probability=90,
    )
    setup.add(opp)
    setup.commit()
    opp_id = opp.id
    setup.close()

    def _run() -> None:
        db = pg()
        try:
            close_won(db, tenant_id=tenant_id, actor_id=actor_id, opportunity_id=opp_id, correlation_id="c")
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: _run(), range(2)))

    db = pg()
    try:
        customers = int(db.scalar(select(func.count()).select_from(Customer).where(Customer.opportunity_id == opp_id)) or 0)
        contracts = int(db.scalar(select(func.count()).select_from(Contract).where(Contract.opportunity_id == opp_id)) or 0)
        customer_ids = db.scalars(select(Customer.id).where(Customer.opportunity_id == opp_id)).all()
        renewals = int(
            db.scalar(select(func.count()).select_from(Renewal).where(Renewal.customer_id.in_(customer_ids), Renewal.deleted_at.is_(None))) or 0
        ) if customer_ids else 0
        handoffs = int(
            db.scalar(select(func.count()).select_from(HandoffPackage).where(HandoffPackage.opportunity_id == opp_id)) or 0
        )
        assert customers == 1
        assert contracts == 1
        assert renewals == 1
        assert handoffs == 1
        onboarding = int(
            db.scalar(
                select(func.count()).select_from(OnboardingPlan).where(OnboardingPlan.customer_id.in_(customer_ids))
            )
            or 0
        )
        assert onboarding == 1
    finally:
        db.close()


def test_claim_key_unique_violation(pg: sessionmaker) -> None:
    db1 = pg()
    db2 = pg()
    tenant_id, actor_id = _ids(db1)
    key = f"pilot:{uuid4()}"

    def _claim(db: Session) -> bool:
        claimed, _ = claim_key(db, tenant_id=tenant_id, actor_id=actor_id, key=key, action_type="test")
        db.commit()
        return claimed

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_claim, [db1, db2]))
    db1.close()
    db2.close()
    assert results.count(True) == 1
    assert results.count(False) == 1


def _lead_and_approval(db: Session, tenant_id, actor_id, email: str) -> AIApproval:
    lead = Lead(
        tenant_id=tenant_id,
        created_by=actor_id,
        first_name="Pilot",
        last_name="Send",
        email=email,
        company_name="Pilot Co",
        consent_email=True,
        opt_out=False,
    )
    db.add(lead)
    db.flush()
    approval = AIApproval(
        tenant_id=tenant_id,
        created_by=actor_id,
        action_level=2,
        action_type="email.send",
        title="Send follow-up",
        payload_json=json.dumps({"lead_id": str(lead.id), "subject": "Hi", "body": "Hello"}),
        status="approved",
        entity_type="lead",
        entity_id=str(lead.id),
    )
    db.add(approval)
    db.flush()
    return approval


def test_two_workers_same_send_once(pg: sessionmaker) -> None:
    setup = pg()
    tenant_id, actor_id = _ids(setup)
    settings = get_or_create_settings(setup, tenant_id=tenant_id, actor_id=actor_id)
    settings.max_emails_per_day = 10_000
    settings.emergency_stop = False
    approval = _lead_and_approval(setup, tenant_id, actor_id, f"send.{uuid4().hex[:8]}@pilot.example")
    setup.commit()
    approval_id = approval.id
    setup.close()

    def _run() -> None:
        db = pg()
        try:
            row = db.get(AIApproval, approval_id)
            execute_email_send(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: _run(), range(2)))

    db = pg()
    try:
        sent = int(
            db.scalar(
                select(func.count())
                .select_from(EmailMessage)
                .where(EmailMessage.approval_id == approval_id, EmailMessage.status == "SENT")
            )
            or 0
        )
        actions = int(
            db.scalar(
                select(func.count())
                .select_from(ProviderAction)
                .where(ProviderAction.approval_id == approval_id, ProviderAction.action_type == "email.send")
            )
            or 0
        )
        assert sent == 1
        assert actions == 1
    finally:
        db.close()


def test_duplicate_inbox_callback_once(pg: sessionmaker) -> None:
    setup = pg()
    tenant_id, actor_id = _ids(setup)
    external_id = f"cb-{uuid4()}"
    setup.close()

    def _run() -> None:
        db = pg()
        try:
            record_inbox_event(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                provider="gmail",
                external_id=external_id,
                payload={"id": external_id},
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: _run(), range(2)))

    db = pg()
    try:
        count = int(
            db.scalar(
                select(func.count())
                .select_from(ProviderInboxEvent)
                .where(
                    ProviderInboxEvent.tenant_id == tenant_id,
                    ProviderInboxEvent.provider == "gmail",
                    ProviderInboxEvent.external_id == external_id,
                )
            )
            or 0
        )
        assert count == 1
    finally:
        db.close()


def test_event_and_reconcile_share_claim(pg: sessionmaker) -> None:
    db1 = pg()
    db2 = pg()
    tenant_id, actor_id = _ids(db1)
    key = f"lead.intake:{uuid4()}"

    def _claim(db: Session) -> bool:
        claimed, _ = claim_key(db, tenant_id=tenant_id, actor_id=actor_id, key=key, workflow="intake")
        db.commit()
        return claimed

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_claim, [db1, db2]))
    db1.close()
    db2.close()
    assert results.count(True) == 1


def test_daily_caps_not_bypassed(pg: sessionmaker) -> None:
    setup = pg()
    tenant_id, actor_id = _ids(setup)
    settings = get_or_create_settings(setup, tenant_id=tenant_id, actor_id=actor_id)
    settings.max_emails_per_day = 1
    settings.emergency_stop = False
    first = _lead_and_approval(setup, tenant_id, actor_id, f"cap1.{uuid4().hex[:8]}@pilot.example")
    second = _lead_and_approval(setup, tenant_id, actor_id, f"cap2.{uuid4().hex[:8]}@pilot.example")
    setup.commit()
    ids = [first.id, second.id]
    setup.close()

    def _run(approval_id) -> None:
        db = pg()
        try:
            row = db.get(AIApproval, approval_id)
            execute_email_send(db, tenant_id=tenant_id, actor_id=actor_id, approval=row)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(_run, ids))

    db = pg()
    try:
        sent = int(
            db.scalar(
                select(func.count())
                .select_from(EmailMessage)
                .where(EmailMessage.approval_id.in_(ids), EmailMessage.status == "SENT")
            )
            or 0
        )
        assert sent <= 1
        kind = f"cap-proof-{uuid4().hex[:8]}"
        claimed = [claim_daily_slot(db, tenant_id=tenant_id, actor_id=actor_id, kind=kind, limit=1) for _ in range(2)]
        assert claimed.count(True) == 1
        db.commit()
    finally:
        db.close()


def test_stale_and_emergency_refuse_execute(pg: sessionmaker) -> None:
    db = pg()
    try:
        tenant_id, actor_id = _ids(db)
        settings = get_or_create_settings(db, tenant_id=tenant_id, actor_id=actor_id)
        settings.emergency_stop = True
        approval = _lead_and_approval(db, tenant_id, actor_id, f"stop.{uuid4().hex[:8]}@pilot.example")
        db.flush()
        stopped = dispatch_approval(db, tenant_id=tenant_id, actor_id=actor_id, row=approval)
        assert "Emergency stop" in stopped
        settings.emergency_stop = False
        lead = db.get(Lead, UUID(str(approval.entity_id)))
        assert lead is not None
        lead.opt_out = True
        db.flush()
        stale = dispatch_approval(db, tenant_id=tenant_id, actor_id=actor_id, row=approval)
        assert "opted out" in stale.lower()
        db.commit()
    finally:
        db.close()
