import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, get_current_user
from app.db.session import get_db
from app.models.crm import Account, Contact, Lead
from app.schemas.common import Envelope
from app.schemas.crm import ImportCommitIn, ImportPreviewIn, ImportPreviewOut
from app.services.audit import write_audit
from app.services.scoring import score_lead

router = APIRouter(prefix="/imports", tags=["imports"])

ALLOWED = {
    "accounts": {"permission": "accounts.write", "required": ["name"]},
    "contacts": {"permission": "contacts.write", "required": ["first_name", "last_name"]},
    "leads": {"permission": "leads.write", "required": ["first_name", "last_name"]},
}


def _parse(csv_text: str) -> tuple[list[str], list[dict], list[str]]:
    if len(csv_text.encode("utf-8")) > 500_000:
        raise HTTPException(status_code=413, detail="CSV too large")
    reader = csv.DictReader(io.StringIO(csv_text))
    columns = reader.fieldnames or []
    rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    errors: list[str] = []
    if not columns:
        errors.append("No header row found")
    return list(columns), rows[:200], errors


@router.post("/preview", response_model=Envelope[ImportPreviewOut])
def preview_import(
    body: ImportPreviewIn,
    ctx: Annotated[AuthContext, Depends(get_current_user)],
) -> Envelope[ImportPreviewOut]:
    spec = ALLOWED.get(body.entity)
    if spec is None:
        raise HTTPException(status_code=422, detail="Unsupported import entity")
    if spec["permission"] not in ctx.permissions:
        raise HTTPException(status_code=403, detail="Permission denied")
    columns, rows, errors = _parse(body.csv_text)
    for required in spec["required"]:
        if required not in columns:
            errors.append(f"Missing required column '{required}'")
    return Envelope(
        data=ImportPreviewOut(
            entity=body.entity, columns=columns, rows=rows, errors=errors, count=len(rows)
        )
    )


@router.post("/commit")
def commit_import(
    body: ImportCommitIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(get_current_user)],
) -> Envelope[dict]:
    spec = ALLOWED.get(body.entity)
    if spec is None:
        raise HTTPException(status_code=422, detail="Unsupported import entity")
    if spec["permission"] not in ctx.permissions:
        raise HTTPException(status_code=403, detail="Permission denied")
    created = 0
    for raw in body.rows[:200]:
        if body.entity == "accounts" and raw.get("name"):
            db.add(Account(tenant_id=ctx.tenant_id, created_by=ctx.user.id, name=raw["name"], industry=raw.get("industry", "")))
            created += 1
        elif body.entity == "contacts" and raw.get("first_name"):
            db.add(
                Contact(
                    tenant_id=ctx.tenant_id,
                    created_by=ctx.user.id,
                    first_name=raw["first_name"],
                    last_name=raw.get("last_name", ""),
                    email=raw.get("email", ""),
                    title=raw.get("title", ""),
                )
            )
            created += 1
        elif body.entity == "leads" and raw.get("first_name"):
            lead = Lead(
                tenant_id=ctx.tenant_id,
                created_by=ctx.user.id,
                first_name=raw["first_name"],
                last_name=raw.get("last_name", ""),
                email=raw.get("email", ""),
                company_name=raw.get("company_name", ""),
                title=raw.get("title", ""),
                source="import",
            )
            db.add(lead)
            db.flush()
            score_lead(db, lead)
            created += 1
    write_audit(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="import.commit",
        entity_type=body.entity,
        after={"created": created},
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    return Envelope(data={"created": created})
