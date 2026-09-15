import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.tenant_context import set_tenant_context
from app.models.crm import Account
from app.models.identity import Tenant

pytestmark = pytest.mark.postgres


def _urls() -> tuple[str, str] | None:
    admin = os.environ.get("POSTGRES_RLS_ADMIN_URL") or os.environ.get("DATABASE_ADMIN_URL")
    app_url = os.environ.get("POSTGRES_RLS_URL")
    if not admin:
        return None
    return admin, app_url or admin.replace("://agrayian:", "://agrayian_app:")


@pytest.fixture(scope="module")
def rls_session() -> Session:
    urls = _urls()
    if urls is None:
        pytest.skip("POSTGRES_RLS_ADMIN_URL is not set")
    admin_url, app_url = urls
    os.environ.setdefault("DATABASE_ADMIN_URL", admin_url)
    os.environ.setdefault("DATABASE_URL", admin_url)
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    engine = create_engine(app_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_rls_blocks_cross_tenant_without_app_predicate(rls_session: Session) -> None:
    tenants = list(rls_session.scalars(select(Tenant).where(Tenant.is_active.is_(True))).all())
    if len(tenants) < 2:
        pytest.skip("Need two tenants (run seed against the RLS database)")
    left, right = tenants[0], tenants[1]
    set_tenant_context(rls_session, left.id)
    name = f"RLS secret {uuid4()}"
    row = Account(tenant_id=left.id, name=name)
    rls_session.add(row)
    rls_session.flush()
    leaked = rls_session.scalar(select(Account).where(Account.id == row.id))
    assert leaked is not None
    set_tenant_context(rls_session, right.id)
    hidden = rls_session.scalar(select(Account).where(Account.id == row.id))
    assert hidden is None
    unscoped = list(rls_session.scalars(select(Account)).all())
    assert all(item.tenant_id == right.id for item in unscoped)
    rls_session.rollback()


def test_rls_blocks_customer_signals_without_predicate(rls_session: Session) -> None:
    from app.models.signals import CustomerSignal

    tenants = list(rls_session.scalars(select(Tenant).where(Tenant.is_active.is_(True))).all())
    if len(tenants) < 2:
        pytest.skip("Need two tenants (run seed against the RLS database)")
    left, right = tenants[0], tenants[1]
    set_tenant_context(rls_session, left.id)
    row = CustomerSignal(
        tenant_id=left.id,
        signal_type="user.active",
        signal_category="USAGE",
        source_provider="usage",
        external_reference=str(uuid4()),
    )
    rls_session.add(row)
    rls_session.flush()
    set_tenant_context(rls_session, right.id)
    hidden = rls_session.scalar(select(CustomerSignal).where(CustomerSignal.id == row.id))
    assert hidden is None
    rls_session.rollback()


def test_rls_blocks_usage_events_and_mappings_without_predicate(rls_session: Session) -> None:
    from app.models.signals import ExternalEntityMapping, UsageEvent

    tenants = list(rls_session.scalars(select(Tenant).where(Tenant.is_active.is_(True))).all())
    if len(tenants) < 2:
        pytest.skip("Need two tenants (run seed against the RLS database)")
    left, right = tenants[0], tenants[1]
    set_tenant_context(rls_session, left.id)
    event = UsageEvent(
        tenant_id=left.id,
        provider="usage",
        external_id=str(uuid4()),
        event_type="user.active",
    )
    mapping = ExternalEntityMapping(
        tenant_id=left.id,
        provider="usage",
        entity_type="account",
        external_id=str(uuid4()),
        status="pending",
    )
    rls_session.add(event)
    rls_session.add(mapping)
    rls_session.flush()
    set_tenant_context(rls_session, right.id)
    assert rls_session.scalar(select(UsageEvent).where(UsageEvent.id == event.id)) is None
    assert rls_session.scalar(select(ExternalEntityMapping).where(ExternalEntityMapping.id == mapping.id)) is None
    rls_session.rollback()


def test_rls_blocks_ml_predictions_and_snapshots(rls_session: Session) -> None:
    from app.models.ml import Prediction
    from app.models.signals import MLFeatureSnapshot

    tenants = list(rls_session.scalars(select(Tenant).where(Tenant.is_active.is_(True))).all())
    if len(tenants) < 2:
        pytest.skip("Need two tenants (run seed against the RLS database)")
    left, right = tenants[0], tenants[1]
    set_tenant_context(rls_session, left.id)
    snap = MLFeatureSnapshot(
        tenant_id=left.id,
        entity_type="lead",
        entity_id=str(uuid4()),
        task_key="LEAD_CONVERSION",
        feature_set_version="v1",
        features_json="{}",
    )
    pred = Prediction(
        tenant_id=left.id,
        task_key="LEAD_CONVERSION",
        entity_type="lead",
        entity_id=str(uuid4()),
        execution_mode="SHADOW",
        provider_key="rules",
    )
    rls_session.add(snap)
    rls_session.add(pred)
    rls_session.flush()
    set_tenant_context(rls_session, right.id)
    assert rls_session.scalar(select(MLFeatureSnapshot).where(MLFeatureSnapshot.id == snap.id)) is None
    assert rls_session.scalar(select(Prediction).where(Prediction.id == pred.id)) is None
    rls_session.rollback()
