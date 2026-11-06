"""Turn a verified Meta lead notification into one attributed enquiry.

The tenant and operating plan come from a local form mapping. A prepared
demonstration never opens a live Graph client. An explicit client is a
test double and is the only retrieval path used by isolated fixtures.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.tenant_context import clear_tenant_context, set_lead_intake, set_tenant_context
from app.models.ai import AIApproval
from app.models.crm import Lead, Task
from app.models.identity import User
from app.models.lead_form import LeadFormBinding, LeadFormReceipt
from app.models.operating_plan import OperatingPlan
from app.providers.meta_leads import (
    LeadHttp,
    LeadRead,
    answered_at,
    disclaimer_values,
    dumps,
    field_values,
    leadgen_changes,
    live_meta_lead_client,
    read_lead,
)
from app.services.acquisition import capture_inbound
from app.services.assessment import assess_and_store
from app.services.crm import add_activity
from app.services.demo_guard import lead_retrieval_block
from app.services.product_context import build_product_context, context_from_mapping

PROVIDER = "meta"
SOURCE = "meta_lead_form"
RETRY_STATUSES = {"received", "retrieving", "rate_limited", "unavailable"}
REVIEW_PERMISSION = "Review this Meta enquiry before any reply. Permission to answer was not established."
POSTING_TOKEN_UNUSED = "A Meta lead retrieval token is not configured. The posting token was not used."
UNKNOWN_FORM = "Unknown Meta form. No enquiry was created."
AMBIGUOUS_FORM = "More than one workspace maps this Meta form. No enquiry was created."
MISSING_EMAIL = "The form did not include an email. The submission was kept and was not discarded."
DEFAULT_FIELD_MAP = {
    "email": ["email"],
    "full_name": ["full_name"],
    "first_name": ["first_name"],
    "last_name": ["last_name"],
    "phone": ["phone_number", "phone"],
    "company_name": ["company_name"],
    "title": ["job_title"],
    "request_note": ["request_note", "comments"],
}


def bind_lead_form(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    page_id: str,
    form_id: str,
    operating_plan_id: UUID,
    form_purpose: str = "",
    field_map: dict | None = None,
    permission_questions: dict | None = None,
) -> LeadFormBinding:
    """Store an explicit mapping. This does not call Meta or pick a plan."""
    page = page_id.strip()
    form = form_id.strip()
    if not page or not form:
        raise HTTPException(status_code=422, detail="A Meta page id and form id are required.")
    plan = db.get(OperatingPlan, operating_plan_id)
    if plan is None or plan.tenant_id != tenant_id or plan.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Choose an operating plan in this workspace.")
    context = build_product_context(db, tenant_id, plan=plan)
    existing = db.scalar(
        select(LeadFormBinding).where(
            LeadFormBinding.tenant_id == tenant_id,
            LeadFormBinding.provider == PROVIDER,
            LeadFormBinding.page_id == page,
            LeadFormBinding.form_id == form,
            LeadFormBinding.deleted_at.is_(None),
        )
    )
    binding = existing or LeadFormBinding(
        tenant_id=tenant_id,
        created_by=actor_id,
        provider=PROVIDER,
        page_id=page,
        form_id=form,
    )
    binding.operating_plan_id = plan.id
    binding.context_json = json.dumps(context.as_dict())
    binding.field_map_json = json.dumps(field_map or DEFAULT_FIELD_MAP)
    binding.permission_json = json.dumps(permission_questions or {})
    binding.form_purpose = form_purpose.strip()[:200]
    binding.status = "active"
    binding.updated_by = actor_id
    if existing is None:
        db.add(binding)
    db.flush()
    return binding


def accept_leadgen_notification(db: Session, payload: dict) -> dict:
    """Persist each new leadgen id. A repeat of the same id is not a second row."""
    set_lead_intake(db, True)
    try:
        return _accept_leadgen_notification(db, payload)
    finally:
        set_lead_intake(db, False)


def _accept_leadgen_notification(db: Session, payload: dict) -> dict:
    created = 0
    duplicate = 0
    for change in leadgen_changes(payload):
        lead_id = change["provider_lead_id"]
        existing = db.scalar(
            select(LeadFormReceipt).where(
                LeadFormReceipt.provider == PROVIDER,
                LeadFormReceipt.provider_lead_id == lead_id,
            )
        )
        if existing is not None:
            duplicate += 1
            continue
        db.add(
            LeadFormReceipt(
                provider=PROVIDER,
                provider_lead_id=lead_id,
                page_id=change["page_id"],
                form_id=change["form_id"],
                ad_id=change["ad_id"],
                adgroup_id=change["adgroup_id"],
                notification_json=dumps(change["raw"]),
                status="received",
            )
        )
        created += 1
    db.flush()
    return {"accepted": created, "duplicate": duplicate}


def process_due_lead_receipts(db: Session, client: LeadHttp | None = None) -> int:
    """Retrieve and capture due receipts. A missing client is not a live call.

    Unbound receipts have no tenant yet. The intake flag lets this worker see them
    and every form mapping, so two workspaces claiming one form stay ambiguous.
    Tenant-owned writes happen only after the mapping selects one tenant.
    """
    set_lead_intake(db, True)
    clear_tenant_context(db)
    rows = db.scalars(
        select(LeadFormReceipt)
        .where(LeadFormReceipt.status.in_(tuple(RETRY_STATUSES)))
        .order_by(LeadFormReceipt.created_at.asc())
        .limit(20)
    ).all()
    live: LeadHttp | None = client
    handled = 0
    try:
        for row in rows:
            clear_tenant_context(db)
            set_lead_intake(db, True)
            live = process_lead_receipt(db, row, client=live, allow_live=client is None)
            db.flush()
            handled += 1
        return handled
    finally:
        set_lead_intake(db, False)
        clear_tenant_context(db)
        if client is None and live is not None:
            close = getattr(live, "close", None)
            if close is not None:
                close()


def process_lead_receipt(db: Session, receipt: LeadFormReceipt, *, client: LeadHttp | None, allow_live: bool) -> LeadHttp | None:
    """One receipt. Returns the client so a later receipt can reuse an opened double."""
    if receipt.capture_id is not None and receipt.status == "processed":
        return client
    if receipt.capture_id is not None:
        _finish_journey(db, receipt)
        return client
    bindings = _bindings(db, receipt.page_id, receipt.form_id)
    tenants = {row.tenant_id for row in bindings}
    if not bindings:
        _review(receipt, UNKNOWN_FORM)
        return client
    if len(tenants) != 1:
        _review(receipt, AMBIGUOUS_FORM)
        return client
    binding = bindings[0]
    set_tenant_context(db, binding.tenant_id)
    receipt.tenant_id = binding.tenant_id
    receipt.binding_id = binding.id
    receipt.operating_plan_id = binding.operating_plan_id
    if not (receipt.detail_json or "").strip():
        client = _retrieve(db, receipt, client=client, allow_live=allow_live)
        if not (receipt.detail_json or "").strip():
            return client
    _capture_detail(db, receipt, binding)
    return client


def native_form_rows(db: Session, tenant_id: UUID) -> list[dict]:
    """Receipts for this workspace, plus forms that no workspace owns yet."""
    rows = db.scalars(
        select(LeadFormReceipt)
        .where(or_(LeadFormReceipt.tenant_id == tenant_id, LeadFormReceipt.tenant_id.is_(None)))
        .order_by(LeadFormReceipt.created_at.desc())
        .limit(20)
    ).all()
    return [_public_row(db, row) for row in rows]


def native_form_for_lead(db: Session, lead: Lead) -> dict:
    receipt = db.scalar(
        select(LeadFormReceipt)
        .where(LeadFormReceipt.tenant_id == lead.tenant_id, LeadFormReceipt.lead_id == lead.id)
        .order_by(LeadFormReceipt.created_at.desc())
    )
    if receipt is None:
        return {}
    return _public_row(db, receipt)


def _bindings(db: Session, page_id: str, form_id: str) -> list[LeadFormBinding]:
    if not page_id or not form_id:
        return []
    return list(
        db.scalars(
            select(LeadFormBinding).where(
                LeadFormBinding.provider == PROVIDER,
                LeadFormBinding.page_id == page_id,
                LeadFormBinding.form_id == form_id,
                LeadFormBinding.status == "active",
                LeadFormBinding.deleted_at.is_(None),
            )
        ).all()
    )


def _retrieve(db: Session, receipt: LeadFormReceipt, *, client: LeadHttp | None, allow_live: bool) -> LeadHttp | None:
    token = ""
    if client is None and allow_live:
        if receipt.tenant_id is not None:
            blocked = lead_retrieval_block(db, receipt.tenant_id)
            if blocked:
                receipt.error = blocked
                return None
        token = get_settings().meta_lead_access_token.strip()
        if not token:
            _review(receipt, POSTING_TOKEN_UNUSED)
            return None
        client = live_meta_lead_client(token)
    if client is None:
        return None
    receipt.status = "retrieving"
    receipt.attempts += 1
    db.flush()
    result = read_lead(client, receipt.provider_lead_id, token or "fixture-lead-token")
    _apply_read(receipt, result)
    return client


def _apply_read(receipt: LeadFormReceipt, result: LeadRead) -> None:
    if result.kind == "ok":
        receipt.detail_json = dumps(result.payload)
        receipt.error = ""
        return
    receipt.error = result.message[:500]
    if result.kind == "permission_denied":
        receipt.status = "permission_denied"
        return
    if result.kind == "rate_limited":
        receipt.status = "rate_limited"
        return
    if result.kind == "unavailable":
        receipt.status = "needs_review" if receipt.attempts >= 5 else "unavailable"
        return
    receipt.status = "needs_review" if receipt.attempts >= 5 else "received"


def _capture_detail(db: Session, receipt: LeadFormReceipt, binding: LeadFormBinding) -> None:
    detail = json.loads(receipt.detail_json or "{}")
    if not isinstance(detail, dict):
        _review(receipt, "Meta returned a lead detail that could not be read.")
        return
    answers = field_values(detail)
    mapped = _mapped(answers, _load_json(binding.field_map_json) or DEFAULT_FIELD_MAP)
    receipt.answers_json = dumps(answers)
    _store_attribution(receipt, detail)
    permissions = _permissions(binding, answers, disclaimer_values(detail), detail, receipt)
    receipt.permission_json = dumps({"questions": permissions})
    email = mapped.get("email", "").strip().lower()
    if "@" not in email:
        _review(receipt, MISSING_EMAIL)
        return
    actor = _actor(db, binding.tenant_id)
    if actor is None:
        _review(receipt, "This workspace has no active user. The enquiry was kept.")
        return
    lead_exists = db.scalar(
        select(Lead.id).where(Lead.tenant_id == binding.tenant_id, Lead.email == email.casefold(), Lead.deleted_at.is_(None))
    )
    first, last = _person_name(mapped)
    ad_id = receipt.ad_id if receipt.attribution == "ad" and lead_exists is None else ""
    payload = {
        "first_name": first,
        "last_name": last,
        "email": email,
        "phone": mapped.get("phone", ""),
        "company_name": mapped.get("company_name", ""),
        "title": mapped.get("title", ""),
        "source": SOURCE,
        "channel": SOURCE,
        "request_note": mapped.get("request_note", ""),
        "consent_email": _granted(permissions, "answer_enquiry"),
        "utm_source": PROVIDER,
        "utm_medium": "lead_form",
        "utm_campaign": receipt.provider_campaign_id,
        "ad_id": ad_id,
        "campaign": receipt.provider_campaign_id,
    }
    try:
        capture, lead, _reviews = capture_inbound(
            db,
            tenant_id=binding.tenant_id,
            actor_id=actor.id,
            payload=payload,
            correlation_id=receipt.provider_lead_id,
        )
    except HTTPException as exc:
        _review(receipt, str(exc.detail or "The enquiry was kept and was not captured."))
        return
    if lead is None:
        _review(receipt, "The enquiry was kept and no lead was created.")
        return
    if lead_exists is None and receipt.attribution == "ad" and receipt.ad_id and not (lead.ad_id or "").strip():
        lead.ad_id = receipt.ad_id
    if lead.operating_plan_id is None:
        lead.operating_plan_id = binding.operating_plan_id
    if not (lead.provider_ref or "").strip():
        lead.provider_ref = f"meta:{receipt.provider_lead_id}"[:200]
    capture.operating_plan_id = binding.operating_plan_id
    capture.ad_id = receipt.ad_id if receipt.attribution == "ad" else ""
    receipt.capture_id = capture.id
    receipt.lead_id = lead.id
    receipt.created_by = actor.id
    later = capture.status == "duplicate_review"
    add_activity(
        db,
        tenant_id=binding.tenant_id,
        actor_id=actor.id,
        entity_type="lead",
        entity_id=str(lead.id),
        activity_type="meta_lead_form",
        title="Later Meta lead form enquiry" if later else "Meta lead form enquiry",
        body=f"Form {receipt.form_id}. Purpose {binding.form_purpose or 'not recorded'}. Provider lead {receipt.provider_lead_id}.",
        actor_type="system",
    )
    db.flush()
    _finish_journey(db, receipt)


def _finish_journey(db: Session, receipt: LeadFormReceipt) -> None:
    if receipt.tenant_id is None or receipt.lead_id is None:
        receipt.status = "needs_review"
        return
    lead = db.get(Lead, receipt.lead_id)
    actor = _actor(db, receipt.tenant_id)
    if lead is None or actor is None or lead.tenant_id != receipt.tenant_id:
        _review(receipt, "The mapped lead could not be read. Nothing was sent.")
        return
    permissions = _load_json(receipt.permission_json).get("questions") or []
    granted = _granted(permissions, "answer_enquiry")
    # Imported here because orchestrator loads marketing, which loads this module.
    from app.services.orchestrator import run_lead_intake

    if granted and lead.consent_email and not lead.opt_out:
        run_lead_intake(db, tenant_id=receipt.tenant_id, actor_id=actor.id, lead=lead, correlation_id=receipt.provider_lead_id)
        receipt.status = "processed"
        receipt.error = ""
        return
    assess_and_store(db, tenant_id=receipt.tenant_id, actor_id=actor.id, lead=lead)
    _review_task(db, tenant_id=receipt.tenant_id, actor_id=actor.id, lead=lead)
    receipt.status = "needs_review"
    receipt.error = REVIEW_PERMISSION
    db.flush()


def _review_task(db: Session, *, tenant_id: UUID, actor_id: UUID, lead: Lead) -> None:
    existing = db.scalar(
        select(Task).where(
            Task.tenant_id == tenant_id,
            Task.entity_type == "lead",
            Task.entity_id == str(lead.id),
            Task.title == REVIEW_PERMISSION,
            Task.status == "open",
            Task.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return
    db.add(
        Task(
            tenant_id=tenant_id,
            created_by=actor_id,
            title=REVIEW_PERMISSION,
            description="The Meta enquiry is retained. Email, sequence, and call permission are separate. Nothing was sent.",
            status="open",
            source="system",
            owner_id=lead.owner_id,
            entity_type="lead",
            entity_id=str(lead.id),
        )
    )


def _store_attribution(receipt: LeadFormReceipt, detail: dict) -> None:
    """Keep an ad id only when the provider supplied one. Do not invent one."""
    detail_ad = _clean_id(detail.get("ad_id"))
    detail_campaign = _clean_id(detail.get("campaign_id"))
    detail_adset = _clean_id(detail.get("adset_id"))
    if detail_ad:
        receipt.ad_id = detail_ad
    if detail_campaign:
        receipt.provider_campaign_id = detail_campaign
    if detail_adset and not receipt.adgroup_id:
        receipt.adgroup_id = detail_adset
    receipt.attribution = "ad" if receipt.ad_id else "unattributed"


def _permissions(binding: LeadFormBinding, answers: dict[str, str], disclaimers: dict[str, str], detail: dict, receipt: LeadFormReceipt) -> list[dict]:
    configured = _load_json(binding.permission_json)
    moment = answered_at(detail.get("created_time") or _load_json(receipt.notification_json).get("created_time"))
    stored: list[dict] = []
    for purpose in ("answer_enquiry", "marketing_sequence", "calls"):
        rule = configured.get(purpose) if isinstance(configured.get(purpose), dict) else {}
        question = str(rule.get("question") or "").strip()
        source = str(rule.get("source") or "field").strip()
        yes_values = {str(item).strip().casefold() for item in rule.get("yes_values") or [] if str(item).strip()}
        if source == "disclaimer":
            answer = disclaimers.get(question, "")
        else:
            answer = answers.get(question, "")
        granted = bool(question) and answer.casefold() in yes_values
        stored.append(
            {
                "purpose": purpose,
                "source": source,
                "question": question,
                "form_id": receipt.form_id,
                "answer": answer,
                "granted": granted,
                "meaning": str(rule.get("meaning") or ""),
                "answered_at": moment,
                "established": bool(question) and bool(answer),
            }
        )
    return stored


def _public_row(db: Session, receipt: LeadFormReceipt) -> dict:
    context = context_from_mapping(_load_json(_binding_context(db, receipt)))
    answers = _load_json(receipt.answers_json)
    permissions = _load_json(receipt.permission_json).get("questions") or []
    missing = _missing(answers, receipt)
    return {
        "id": str(receipt.id),
        "platform": "Meta native lead form",
        "page_id": receipt.page_id,
        "form_id": receipt.form_id,
        "form_purpose": _binding_purpose(db, receipt),
        "status": receipt.status,
        "error": receipt.error,
        "product_name": context.customer_facing_name,
        "offer_label": context.offer_label(),
        "operating_plan_id": str(receipt.operating_plan_id or ""),
        "attribution": receipt.attribution or "unattributed",
        "ad_id": receipt.ad_id if receipt.attribution == "ad" else "",
        "adgroup_id": receipt.adgroup_id,
        "provider_campaign_id": receipt.provider_campaign_id,
        "supplied_fields": sorted(answers) if isinstance(answers, dict) else [],
        "supplied_answers": answers if isinstance(answers, dict) else {},
        "missing_fields": missing,
        "permission": _permission_text(permissions),
        "lead_id": str(receipt.lead_id or ""),
        "acknowledgement": _acknowledgement(db, receipt),
        "review": receipt.error if receipt.status == "needs_review" else "",
    }


def _acknowledgement(db: Session, receipt: LeadFormReceipt) -> str:
    if receipt.lead_id is None or receipt.tenant_id is None:
        return "not prepared"
    approval = db.scalar(
        select(AIApproval)
        .where(
            AIApproval.tenant_id == receipt.tenant_id,
            AIApproval.entity_type == "lead",
            AIApproval.entity_id == str(receipt.lead_id),
            AIApproval.action_type == "email.acknowledge",
            AIApproval.deleted_at.is_(None),
        )
        .order_by(AIApproval.created_at.desc())
    )
    if approval is None:
        return "not prepared"
    return approval.status


def _missing(answers: dict, receipt: LeadFormReceipt) -> list[str]:
    if not isinstance(answers, dict):
        answers = {}
    mapped = _mapped(answers, DEFAULT_FIELD_MAP)
    missing: list[str] = []
    if "@" not in mapped.get("email", ""):
        missing.append("email")
    if not (mapped.get("full_name") or mapped.get("first_name")):
        missing.append("name")
    if not mapped.get("company_name"):
        missing.append("company")
    if not mapped.get("title"):
        missing.append("role")
    if not mapped.get("request_note"):
        missing.append("request note")
    if receipt.attribution != "ad":
        missing.append("ad")
    permissions = _load_json(receipt.permission_json).get("questions") or []
    if not _granted(permissions, "answer_enquiry"):
        missing.append("permission to answer")
    return missing


def _mapped(answers: dict[str, str], field_map: dict) -> dict[str, str]:
    found: dict[str, str] = {}
    for target, names in field_map.items():
        if not isinstance(names, list):
            continue
        for name in names:
            value = answers.get(str(name), "")
            if value:
                found[str(target)] = value
                break
    return found


def _person_name(mapped: dict[str, str]) -> tuple[str, str]:
    first = mapped.get("first_name", "").strip()
    last = mapped.get("last_name", "").strip()
    if first or last:
        return first[:80], last[:80]
    parts = [part for part in mapped.get("full_name", "").split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0][:80], ""
    return parts[0][:80], " ".join(parts[1:])[:80]


def _granted(permissions: object, purpose: str) -> bool:
    if not isinstance(permissions, list):
        return False
    for row in permissions:
        if isinstance(row, dict) and row.get("purpose") == purpose:
            return bool(row.get("granted"))
    return False


def _permission_text(permissions: object) -> str:
    if not isinstance(permissions, list) or not permissions:
        return "Permission was not established."
    labels = {
        "answer_enquiry": "answer",
        "marketing_sequence": "marketing sequence",
        "calls": "calls",
    }
    parts: list[str] = []
    for row in permissions:
        if not isinstance(row, dict):
            continue
        purpose = str(row.get("purpose") or "")
        label = labels.get(purpose, purpose)
        if row.get("granted"):
            parts.append(f"{label} granted")
        elif row.get("answer"):
            parts.append(f"{label} not granted")
        else:
            parts.append(f"{label} not established")
    return "; ".join(parts) if parts else "Permission was not established."


def _binding_context(db: Session, receipt: LeadFormReceipt) -> str:
    if receipt.binding_id is None:
        return ""
    binding = db.get(LeadFormBinding, receipt.binding_id)
    if binding is None:
        return ""
    return binding.context_json or ""


def _binding_purpose(db: Session, receipt: LeadFormReceipt) -> str:
    if receipt.binding_id is None:
        return ""
    binding = db.get(LeadFormBinding, receipt.binding_id)
    if binding is None:
        return ""
    return binding.form_purpose or ""


def _actor(db: Session, tenant_id: UUID) -> User | None:
    return db.scalar(select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)).order_by(User.created_at.asc()))


def _review(receipt: LeadFormReceipt, message: str) -> None:
    receipt.status = "needs_review"
    receipt.error = message


def _load_json(raw: str | dict | None) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw or not str(raw).strip():
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _clean_id(value: object) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"", "0", "null", "none"}:
        return ""
    return text

