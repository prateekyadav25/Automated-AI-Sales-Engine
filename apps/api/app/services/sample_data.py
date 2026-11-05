"""Retire the fictional sample records that the demo seed creates.

Sample rows are found by provenance: accounts on the reserved ``.example`` domain or
marked fictional, people with ``.example`` email addresses, signals written by the seed,
and the showroom's draft posts. Every row that points at a sample row is retired with it,
following links until nothing new is found. Seed campaigns and sequences are not treated as
samples on their own, because real enquiries can point at them. Rows are soft-deleted and
stay in the database. Open approvals for sample work are rejected and active sample
enrollments are stopped, so neither can run.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, String, Table, Uuid, or_, select, update
from sqlalchemy.orm import Session

import app.models  # noqa: F401  Registers every table on Base.metadata.
from app.db.base import Base
from app.models.ai import AIApproval
from app.models.content import ContentDraft
from app.models.crm import Account, Contact, Lead
from app.models.lifecycle import SequenceEnrollment
from app.models.social import SocialPost
from app.seed_showroom import SHOWROOM_DRAFTS, SHOWROOM_POST
from app.services.audit import write_audit

SAMPLE_DOMAIN = "%.example"
SAMPLE_NOTE = "%fictional%"
SEED_SOURCE = "seed"
OPEN_APPROVALS = ("pending", "held")
REJECTION_NOTE = "Retired with the fictional sample data. A real send waits for a real lead and an approval."
UUID_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CHUNK = 500
# Soft-deleting a ledger row releases its claim, so a retired sample could be sent or claimed again.
LEDGERS = frozenset(
    {
        "automation_idempotency_keys",
        "external_effects",
        "provider_actions",
        "provider_inbox_events",
        "lead_form_receipts",
    }
)


def _chunks(values: Iterable[UUID]) -> Iterator[list[UUID]]:
    items = list(values)
    for start in range(0, len(items), CHUNK):
        yield items[start : start + CHUNK]


def _tables() -> list[Table]:
    return [
        table
        for table in Base.metadata.tables.values()
        if table.name not in LEDGERS
        and {"id", "tenant_id", "deleted_at"} <= set(table.c.keys())
        and isinstance(table.c.id.type, Uuid)
    ]


def _links(table: Table) -> list[Column]:
    return [
        column
        for column in table.c
        if column.name.endswith("_id") and column.name != "tenant_id" and isinstance(column.type, (Uuid, String))
    ]


def _roots(db: Session, tenant_id: UUID, tables: list[Table]) -> dict[str, set[UUID]]:
    found: dict[str, set[UUID]] = defaultdict(set)
    found[Account.__tablename__].update(
        db.scalars(
            select(Account.id).where(
                Account.tenant_id == tenant_id,
                or_(Account.domain.ilike(SAMPLE_DOMAIN), Account.notes.ilike(SAMPLE_NOTE)),
            )
        )
    )
    for model in (Lead, Contact):
        found[model.__tablename__].update(
            db.scalars(select(model.id).where(model.tenant_id == tenant_id, model.email.ilike(f"%@{SAMPLE_DOMAIN}")))
        )
    found[ContentDraft.__tablename__].update(
        db.scalars(
            select(ContentDraft.id).where(
                ContentDraft.tenant_id == tenant_id,
                ContentDraft.headline.in_([headline for _, _, headline, _, _ in SHOWROOM_DRAFTS]),
            )
        )
    )
    found[SocialPost.__tablename__].update(
        db.scalars(select(SocialPost.id).where(SocialPost.tenant_id == tenant_id, SocialPost.body == SHOWROOM_POST))
    )
    for table in tables:
        if "is_mock" not in table.c or "source" not in table.c:
            continue
        found[table.name].update(
            db.scalars(
                select(table.c.id).where(
                    table.c.tenant_id == tenant_id,
                    table.c.is_mock.is_(True),
                    table.c.source == SEED_SOURCE,
                )
            )
        )
    return found


def _spread(
    db: Session, tenant_id: UUID, tables: list[Table], found: dict[str, set[UUID]], frontier: set[UUID]
) -> None:
    known = set().union(*found.values())
    while frontier:
        reached: set[UUID] = set()
        for batch in _chunks(frontier):
            texts = [str(value) for value in batch]
            for table in tables:
                conditions = [column.in_(batch if isinstance(column.type, Uuid) else texts) for column in _links(table)]
                if not conditions:
                    continue
                for row_id in db.scalars(select(table.c.id).where(table.c.tenant_id == tenant_id, or_(*conditions))):
                    if row_id not in known:
                        known.add(row_id)
                        reached.add(row_id)
                        found[table.name].add(row_id)
        frontier = reached


def _approvals_naming(db: Session, tenant_id: UUID, found: dict[str, set[UUID]]) -> set[UUID]:
    known = {str(value) for value in set().union(*found.values())}
    named: set[UUID] = set()
    for approval_id, payload in db.execute(
        select(AIApproval.id, AIApproval.payload_json).where(AIApproval.tenant_id == tenant_id)
    ):
        if approval_id not in found[AIApproval.__tablename__] and known.intersection(UUID_TEXT.findall(payload or "")):
            named.add(approval_id)
    return named


def find_sample_data(db: Session, *, tenant_id: UUID) -> dict[str, set[UUID]]:
    tables = _tables()
    found = _roots(db, tenant_id, tables)
    _spread(db, tenant_id, tables, found, set().union(*found.values()))
    named = _approvals_naming(db, tenant_id, found)
    found[AIApproval.__tablename__].update(named)
    _spread(db, tenant_id, tables, found, named)
    return {name: ids for name, ids in found.items() if ids}


def retire_sample_data(db: Session, *, tenant_id: UUID, now: datetime) -> dict[str, int]:
    """Soft-delete the tenant's sample rows. Returns newly retired rows per table."""
    found = find_sample_data(db, tenant_id=tenant_id)
    tables = {table.name: table for table in _tables()}
    counts: dict[str, int] = {}
    for name in sorted(found):
        table = tables[name]
        ids = found[name]
        if name == AIApproval.__tablename__:
            for batch in _chunks(ids):
                db.execute(
                    update(AIApproval)
                    .where(
                        AIApproval.tenant_id == tenant_id,
                        AIApproval.id.in_(batch),
                        AIApproval.status.in_(OPEN_APPROVALS),
                    )
                    .values(status="rejected", decision_note=REJECTION_NOTE)
                    .execution_options(synchronize_session=False)
                )
        if name == SequenceEnrollment.__tablename__:
            for batch in _chunks(ids):
                db.execute(
                    update(SequenceEnrollment)
                    .where(
                        SequenceEnrollment.tenant_id == tenant_id,
                        SequenceEnrollment.id.in_(batch),
                        SequenceEnrollment.status == "active",
                    )
                    .values(status="stopped", next_run_at=None)
                    .execution_options(synchronize_session=False)
                )
        retired: list[str] = []
        for batch in _chunks(ids):
            rows = (
                db.execute(
                    select(table.c.id).where(
                        table.c.tenant_id == tenant_id, table.c.id.in_(batch), table.c.deleted_at.is_(None)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                continue
            db.execute(update(table).where(table.c.tenant_id == tenant_id, table.c.id.in_(rows)).values(deleted_at=now))
            retired.extend(str(row) for row in rows)
        if not retired:
            continue
        counts[name] = len(retired)
        write_audit(
            db,
            tenant_id=tenant_id,
            actor_id=None,
            action="sample_data.retired",
            entity_type=name,
            before={"deleted_at": None},
            after={"deleted_at": now.isoformat(), "ids": retired},
            actor_type="system",
        )
    db.flush()
    return counts
