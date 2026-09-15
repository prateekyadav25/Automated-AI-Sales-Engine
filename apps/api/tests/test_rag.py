from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag import ingest_text, retrieve
from app.db.session import get_session
from app.models.identity import User


def test_retrieve_is_tenant_filtered_on_sqlite(client) -> None:
    _ = client
    db: Session = get_session()
    try:
        user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        other = db.scalar(select(User).where(User.email == "admin@northline.demo"))
        assert user is not None and other is not None
        ingest_text(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            title="Vector note",
            text="Tenant scoped retrieval must never leak another workspace.",
        )
        db.commit()
        hits = retrieve(db, tenant_id=user.tenant_id, query="workspace retrieval")
        assert hits
        leaked = retrieve(db, tenant_id=other.tenant_id, query="workspace retrieval")
        assert all(row["title"] != "Vector note" for row in leaked)
        empty = retrieve(db, tenant_id=uuid4(), query="workspace retrieval")
        assert empty == []
    finally:
        db.close()
