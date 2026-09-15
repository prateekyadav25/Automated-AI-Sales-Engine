from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ai import KnowledgeSource
from app.models.identity import Tenant
from app.providers.malware import get_malware_scanner
from app.providers.object_storage import get_object_storage
from app.services.autopilot_settings import get_or_create_settings


def apply_scan(
    db: Session,
    *,
    tenant_id: UUID,
    source: KnowledgeSource,
    raw: bytes,
    filename: str,
    object_key: str,
) -> KnowledgeSource:
    storage = get_object_storage()
    quarantine_key = f"{object_key}.quarantine"
    storage.put(quarantine_key, raw, content_type=source.mime_type or "application/octet-stream")
    source.quarantine_key = quarantine_key
    result = get_malware_scanner().scan(raw, filename=filename)
    source.malware_status = result.status
    tenant = db.get(Tenant, tenant_id)
    settings = get_or_create_settings(db, tenant_id=tenant_id)
    mode = (tenant.operating_mode if tenant else "DEMO") or "DEMO"
    if result.status == "SCANNED_BLOCKED":
        source.object_key = ""
        source.status = "quarantined"
        return source
    if result.status in {"NOT_SCANNED", "NOT_CONFIGURED"}:
        blocked = mode == "PRODUCTION" or not settings.allow_unscanned_uploads
        if blocked:
            source.object_key = ""
            source.status = "blocked"
            raise HTTPException(status_code=409, detail="Upload blocked: malware scanner is unavailable")
    source.object_key = object_key
    storage.put(object_key, raw, content_type=source.mime_type or "application/octet-stream")
    return source
