from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ml import EntityFieldHistory, OpportunityFieldHistory, RecommendationFeedback
from app.services.ml.timeutil import now_utc


def record_opportunity_fields(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    opportunity_id: UUID,
    changes: dict[str, tuple[object, object]],
    changed_at: datetime | None = None,
) -> list[OpportunityFieldHistory]:
    stamped = changed_at or now_utc()
    rows: list[OpportunityFieldHistory] = []
    for field, (old, new) in changes.items():
        if str(old) == str(new):
            continue
        row = OpportunityFieldHistory(
            tenant_id=tenant_id,
            created_by=actor_id,
            opportunity_id=opportunity_id,
            field_name=field,
            old_value=str(old if old is not None else ""),
            new_value=str(new if new is not None else ""),
            changed_at=stamped,
        )
        db.add(row)
        rows.append(row)
    if rows:
        db.flush()
    return rows


def record_entity_field(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    entity_type: str,
    entity_id: str,
    field_name: str,
    old_value: object,
    new_value: object,
    changed_at: datetime | None = None,
) -> EntityFieldHistory | None:
    if str(old_value) == str(new_value):
        return None
    row = EntityFieldHistory(
        tenant_id=tenant_id,
        created_by=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        old_value=str(old_value if old_value is not None else ""),
        new_value=str(new_value if new_value is not None else ""),
        changed_at=changed_at or now_utc(),
    )
    db.add(row)
    db.flush()
    return row


def record_feedback(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    recommendation_id: UUID,
    action: str,
    entity_type: str = "expansion_recommendation",
    entity_id: str = "",
    note: str = "",
    useful: str = "",
) -> RecommendationFeedback:
    if action not in {"accepted", "rejected", "edited", "ignored", "expired"}:
        raise ValueError("Unknown feedback action")
    if useful and useful not in {"YES", "NO"}:
        raise ValueError("useful must be YES or NO")
    row = RecommendationFeedback(
        tenant_id=tenant_id,
        created_by=actor_id,
        recommendation_id=recommendation_id,
        entity_type=entity_type,
        entity_id=entity_id or str(recommendation_id),
        action=action,
        note=note,
        useful=useful,
        acted_at=now_utc(),
    )
    db.add(row)
    db.flush()
    return row
