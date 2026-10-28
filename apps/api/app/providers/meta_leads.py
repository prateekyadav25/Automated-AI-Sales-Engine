"""Meta native lead-form notifications and lead-detail retrieval.

Supported Graph version: v21.0, the same version already used for Meta
page publishing in this application (`META_GRAPH`). Official lead-ads
examples published through May 2026 also show v25.0 and v26.0. This
adapter does not call those newer versions and does not call
`has_lead_access`.

Notification contract, from Meta's Webhooks for Leads and Webhooks
Getting Started guides:

- GET verification uses `hub.mode=subscribe`, `hub.verify_token`, and
  `hub.challenge`. A match returns the challenge as plain text.
- POST notifications are HMAC-SHA256 of the raw body, keyed with the
  app secret, in `X-Hub-Signature-256` as `sha256=<hex>`.
- The Page object field is `leadgen`. Each change carries `leadgen_id`,
  `page_id`, `form_id`, `adgroup_id`, `ad_id`, and `created_time`.
- The notification does not include the person's answers. Those come
  from a separate GET `/{leadgen-id}`.

Lead-detail request fields are the retrieving-leads sample
(`created_time`, `id`, `ad_id`, `form_id`, `field_data`) plus `campaign_id`,
`adset_id`, and `custom_disclaimer_responses`. `field_data` entries are
`{name, values[]}`. A custom disclaimer entry is `{checkbox_key, is_checked}`.

Permissions required for a later live retrieval, and not granted by a
page posting token: `leads_retrieval`, `pages_manage_metadata`,
`pages_show_list`, `pages_read_engagement`, `pages_manage_ads`, and
`ads_management`. The token must belong to a person who can ADVERTISE
on the Page. This module never subscribes the Page, creates a form, or
reads `meta_page_access_token`.

LinkedIn Lead Sync, Google lead forms, comments, and direct messages
are not implemented here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.providers.social import META_GRAPH

LEAD_FIELDS = "created_time,id,ad_id,form_id,field_data,campaign_id,adset_id,custom_disclaimer_responses"
GRAPH_VERSION = "v21.0"
PERMISSION_CODES = {10, 190, 200, 294}
RATE_LIMIT_CODES = {4, 17, 32, 613}


class LeadHttp(Protocol):
    def get(self, url: str, params: dict) -> object: ...


@dataclass(frozen=True)
class LeadRead:
    kind: str
    payload: dict
    message: str = ""


def signatures_match(body: bytes, header: str | None, secret: str) -> bool:
    """True when the header is the app-secret HMAC of this exact body."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), digest)


def challenge_response(mode: str, token: str, challenge: str, expected: str) -> str:
    """Return the challenge, or an empty string when verification fails."""
    if mode != "subscribe" or not expected or not token or not challenge:
        return ""
    if not hmac.compare_digest(token, expected):
        return ""
    return challenge


def leadgen_changes(payload: dict) -> list[dict]:
    """Leadgen values from a Page notification. Other fields are ignored."""
    if payload.get("object") != "page":
        return []
    changes: list[dict] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("changes")
        if not isinstance(raw, list):
            continue
        for change in raw:
            if not isinstance(change, dict) or change.get("field") != "leadgen":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            lead_id = _text(value.get("leadgen_id"))
            if not lead_id:
                continue
            changes.append(
                {
                    "provider_lead_id": lead_id,
                    "page_id": _text(value.get("page_id") or entry.get("id")),
                    "form_id": _text(value.get("form_id")),
                    "ad_id": _supplied_id(value.get("ad_id")),
                    "adgroup_id": _supplied_id(value.get("adgroup_id")),
                    "created_time": value.get("created_time"),
                    "raw": {key: value.get(key) for key in value if key != "tenant_id"},
                }
            )
    return changes


def live_meta_lead_client(token: str) -> httpx.Client:
    """Open a Graph client. The caller has already chosen the lead token."""
    if not token.strip():
        raise RuntimeError(POSTING_TOKEN_MESSAGE)
    return httpx.Client(timeout=20.0)


POSTING_TOKEN_MESSAGE = "A Meta lead retrieval token is not configured. The posting token was not used."


def read_lead(client: LeadHttp, lead_id: str, token: str) -> LeadRead:
    """GET one lead. The token is the lead-retrieval token, not a posting token."""
    response = client.get(
        f"{META_GRAPH}/{lead_id}",
        params={"access_token": token, "fields": LEAD_FIELDS},
    )
    status = int(getattr(response, "status_code", 0) or 0)
    body = _json(response)
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = error.get("code")
    message = str(error.get("message") or "")
    if status == 429 or code in RATE_LIMIT_CODES:
        return LeadRead("rate_limited", body, message or "Meta rate limited the lead retrieval.")
    if status in {401, 403} or code in PERMISSION_CODES:
        return LeadRead("permission_denied", body, message or "Meta refused lead retrieval. The posting token was not used.")
    if status == 404 or (status < 400 and not _text(body.get("id"))):
        return LeadRead("unavailable", body, message or "Meta did not return this lead.")
    if status >= 400:
        return LeadRead("failed", body, message or f"Meta lead retrieval returned {status}.")
    return LeadRead("ok", body, "")


def field_values(detail: dict) -> dict[str, str]:
    """First value of each field_data entry. Missing values stay missing."""
    found: dict[str, str] = {}
    rows = detail.get("field_data")
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("name"))
        values = row.get("values")
        if not name or not isinstance(values, list) or not values:
            continue
        text = _text(values[0])
        if text:
            found[name] = text
    return found


def disclaimer_values(detail: dict) -> dict[str, str]:
    rows = detail.get("custom_disclaimer_responses")
    found: dict[str, str] = {}
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _text(row.get("checkbox_key"))
        if key:
            found[key] = _text(row.get("is_checked"))
    return found


def answered_at(value: object) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC).isoformat()
    return _text(value)


def _json(response: object) -> dict:
    reader = getattr(response, "json", None)
    if reader is None:
        return {}
    try:
        payload = reader()
    except Exception:  # noqa: BLE001 — a non-JSON error body is still a failed read
        return {}
    return payload if isinstance(payload, dict) else {}


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _supplied_id(value: object) -> str:
    text = _text(value)
    if text.casefold() in {"", "0", "null", "none"}:
        return ""
    return text


def dumps(payload: dict) -> str:
    return json.dumps(payload, default=str, sort_keys=True)
