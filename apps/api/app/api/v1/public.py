import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.db.tenant_context import set_tenant_context
from app.models.identity import User
from app.schemas.acquisition import CaptureIn, CaptureOut, CaptureResult
from app.schemas.common import Envelope
from app.schemas.crm import LeadOut, LeadScoreOut
from app.services.acquisition import capture_inbound
from app.services.crm import latest_lead_score
from app.services.orchestrator import process_pending_events
from app.services.public_forms import resolve_form_key

router = APIRouter(prefix="/public", tags=["public"])


def _lead_out(db: Session, lead) -> LeadOut:
    payload = LeadOut.model_validate(lead)
    score = latest_lead_score(db, lead)
    if score is not None:
        payload.latest_score = LeadScoreOut.model_validate(score)
    return payload


@router.get("/forms/{token}", response_class=HTMLResponse)
def embeddable_form(token: str, request: Request, db: Annotated[Session, Depends(get_db)]) -> HTMLResponse:
    enforce_rate_limit(key=f"public-form:{request.client.host if request.client else 'unknown'}", limit=60, window_seconds=60)
    resolve_form_key(db, token)
    endpoint = json.dumps(f"{str(request.base_url).rstrip('/')}/api/v1/public/forms/{token}/capture")
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Contact</title>
<style>body{{font-family:sans-serif;max-width:28rem;margin:2rem auto;}}label{{display:block;margin:.6rem 0 .2rem}}input,button{{width:100%;padding:.5rem}}</style>
</head><body>
<form id="agrayian-form">
<label>First name</label><input name="first_name" required>
<label>Last name</label><input name="last_name" required>
<label>Email</label><input name="email" type="email" required>
<label>Company</label><input name="company_name">
<label><input type="checkbox" name="consent_email" value="true"> I consent to email</label>
<button type="submit">Submit</button>
<p id="status"></p>
</form>
<script>
document.getElementById("agrayian-form").addEventListener("submit", async (event) => {{
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  data.consent_email = data.consent_email === "true";
  const response = await fetch({endpoint}, {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify(data)
  }});
  document.getElementById("status").textContent = response.ok ? "Received." : "Could not submit.";
}});
</script>
<p>Powered by AGRAYIAN. Consent is required before outreach.</p>
</body></html>"""
    return HTMLResponse(html)


@router.post("/forms/{token}/capture", response_model=Envelope[CaptureResult])
def public_capture(
    token: str,
    body: CaptureIn,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Envelope[CaptureResult]:
    enforce_rate_limit(
        key=f"public-capture:{token}:{request.client.host if request.client else 'unknown'}",
        limit=20,
        window_seconds=60,
    )
    key = resolve_form_key(db, token)
    set_tenant_context(db, key.tenant_id)
    actor = db.scalar(select(User).where(User.tenant_id == key.tenant_id, User.is_active.is_(True)))
    if actor is None:
        raise HTTPException(status_code=409, detail="Tenant has no active user")
    payload = body.model_dump()
    payload["source"] = payload.get("source") or "public_form"
    payload["channel"] = payload.get("channel") or "website"
    capture_row, lead, reviews = capture_inbound(
        db,
        tenant_id=key.tenant_id,
        actor_id=actor.id,
        payload=payload,
    )
    process_pending_events(db, tenant_id=key.tenant_id, actor_id=actor.id)
    db.commit()
    db.refresh(capture_row)
    if lead is not None:
        db.refresh(lead)
    return Envelope(
        data=CaptureResult(
            capture=CaptureOut.model_validate(capture_row),
            lead=_lead_out(db, lead) if lead is not None else None,
            reviews_opened=len(reviews),
        )
    )
