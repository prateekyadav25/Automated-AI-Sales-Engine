import html
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.db.tenant_context import set_tenant_context
from app.models.identity import User
from app.schemas.acquisition import CaptureIn, CaptureOut, CaptureResult
from app.schemas.common import Envelope
from app.schemas.crm import LeadOut, LeadScoreOut
from app.services.acquisition import capture_inbound, hold_interest, interest_is_eligible
from app.services.crm import latest_lead_score
from app.services.outbox_notify import notify_outbox
from app.services.public_forms import loads_form_fields, public_form_inputs, resolve_form_key
from app.services.social_media import read_social_image

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
    key = resolve_form_key(db, token)
    title = html.escape((key.name or "").strip() or "Tell us what you need")
    fields = loads_form_fields(key.schema_json)
    inputs, labels = public_form_inputs(fields)
    endpoint = json.dumps(f"{str(request.base_url).rstrip('/')}/api/v1/public/forms/{token}/capture")
    label_json = json.dumps(labels).replace("{", "{{").replace("}", "}}")
    query = request.query_params
    hidden = {
        "source": query.get("source") or "public_form",
        "channel": query.get("channel") or "website",
        "campaign": query.get("campaign") or "",
        "utm_source": query.get("utm_source") or query.get("channel") or "",
        "utm_medium": query.get("utm_medium") or "social",
        "utm_campaign": query.get("utm_campaign") or query.get("campaign") or "",
        "ad": query.get("ad") or "",
        "publication": query.get("publication") or "",
    }
    hidden_html = "".join(
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value)}">' for name, value in hidden.items()
    )
    title = title.replace("{", "{{").replace("}", "}}")
    hidden_html = hidden_html.replace("{", "{{").replace("}", "}}")
    inputs = inputs.replace("{", "{{").replace("}", "}}")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0d1118;color:#eef2fa;margin:0}}
main{{max-width:32rem;margin:0 auto;padding:2rem 1.25rem 3rem}}
h1{{font-size:1.6rem;margin:0 0 .5rem}}
p{{line-height:1.5}}
label{{display:block;margin:1rem 0 .35rem}}
input,textarea,select{{width:100%;box-sizing:border-box;padding:.7rem;border:1px solid #293346;border-radius:8px;background:#101722;color:#eef2fa}}
button{{margin-top:1.25rem;width:100%;padding:.8rem;border:0;border-radius:8px;background:#99a5ff;color:#101722;font-weight:650}}
.row{{display:flex;gap:.75rem}}
.row label{{flex:1}}
.check{{display:flex;gap:.6rem;align-items:flex-start}}
.check input{{width:auto;margin-top:.2rem}}
#status{{min-height:1.4rem}}
</style></head><body><main>
<h1>{title}</h1>
<p>Share a few details and what you want. If the request is eligible, it becomes a lead for the team to continue.</p>
<form id="agrayian-form">
{hidden_html}
{inputs}
<button type="submit">Send my interest</button>
<p id="status"></p>
</form>
<p>A name, email, description, and permission to be contacted are required before this becomes a lead.</p>
</main>
<script>
document.getElementById("agrayian-form").addEventListener("submit", async (event) => {{
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  const labels = {label_json};
  const extras = [];
  for (const key of Object.keys(data)) {{
    if (!key.startsWith("custom_")) continue;
    const value = String(data[key] || "").trim();
    if (value) extras.push((labels[key] || "Note") + ": " + value);
    delete data[key];
  }}
  if (extras.length) data.request_note = [data.request_note, extras.join("\\n")].filter(Boolean).join("\\n");
  data.consent_email = data.consent_email === "true";
  const response = await fetch({endpoint}, {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify(data)
  }});
  const body = await response.json().catch(() => ({{}}));
  const payload = body.data || {{}};
  const status = document.getElementById("status");
  if (response.ok && payload.lead) status.textContent = "Thank you. Your interest is with the team.";
  else if (response.ok && payload.capture && payload.capture.status === "duplicate_review") status.textContent = "We already have this email. The team will review it.";
  else if (response.ok) status.textContent = "We saved this for review. A name, email, what you want, and permission to be contacted are required before it becomes a lead.";
  else status.textContent = "Could not submit.";
}});
</script>
</body></html>"""
    return HTMLResponse(page)


@router.get("/media/{token}")
def public_media(token: str, request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    enforce_rate_limit(key=f"public-media:{request.client.host if request.client else 'unknown'}", limit=120, window_seconds=60)
    data, content_type = read_social_image(db, token)
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/forms/{token}/meta", response_model=Envelope[dict])
def public_form_meta(token: str, request: Request, db: Annotated[Session, Depends(get_db)]) -> Envelope[dict]:
    enforce_rate_limit(key=f"public-form-meta:{request.client.host if request.client else 'unknown'}", limit=60, window_seconds=60)
    key = resolve_form_key(db, token)
    return Envelope(data={"name": key.name, "fields": loads_form_fields(key.schema_json)})


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
    if not interest_is_eligible(payload):
        capture_row = hold_interest(db, tenant_id=key.tenant_id, actor_id=actor.id, payload=payload)
        db.commit()
        db.refresh(capture_row)
        return Envelope(
            data=CaptureResult(
                capture=CaptureOut.model_validate(capture_row),
                lead=None,
                reviews_opened=0,
            )
        )
    capture_row, lead, reviews = capture_inbound(
        db,
        tenant_id=key.tenant_id,
        actor_id=actor.id,
        payload=payload,
    )
    db.commit()
    notify_outbox()
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
