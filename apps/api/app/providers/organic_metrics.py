"""LinkedIn share statistics, using the same versioned REST contract as posting.

Facebook and Instagram insights are a different contract and are not read here.
A missing field stays missing. A returned zero stays zero.
"""

from __future__ import annotations

from urllib.parse import quote

from app.providers.social import LINKEDIN_VERSION

LINKEDIN_SHARE_STATS_URL = "https://api.linkedin.com/rest/organizationalEntityShareStatistics"
SOURCE = "linkedin.organizationalEntityShareStatistics"

METRIC_FIELDS = {
    "impressions": ("impressionCount", "Times LinkedIn displayed the share."),
    "clicks": ("clickCount", "Clicks LinkedIn recorded on the share."),
    "likes": ("likeCount", "Reactions LinkedIn recorded on the share."),
    "comments": ("commentCount", "Comments LinkedIn recorded on the share."),
    "shares": ("shareCount", "Reshares LinkedIn recorded."),
    "unique_impressions": ("uniqueImpressionsCount", "Unique viewers LinkedIn reported. This field is often omitted."),
}

UNSUPPORTED_CHANNELS = {
    "facebook": "Facebook page insights are not read by the LinkedIn statistics adapter.",
    "instagram": "Instagram media insights need instagram_manage_insights and are not read by this adapter.",
}


def linkedin_statistics_url(organization_urn: str, share_urn: str) -> str:
    organization = quote(organization_urn, safe="")
    share = quote(share_urn, safe="")
    return (
        f"{LINKEDIN_SHARE_STATS_URL}?q=organizationalEntity"
        f"&organizationalEntity={organization}&shares=List({share})"
    )


def read_linkedin_share_statistics(client, *, token: str, organization_urn: str, share_urn: str) -> dict:
    """Read one share. `client` is httpx-shaped so tests can pass a fake."""
    url = linkedin_statistics_url(organization_urn, share_urn)
    try:
        response = client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Linkedin-Version": LINKEDIN_VERSION,
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )
    except Exception as exc:
        return {"ok": False, "status": "failed", "error": f"LinkedIn metrics request failed: {exc.__class__.__name__}.", "metrics": []}
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code == 401:
        return {"ok": False, "status": "failed", "error": "LinkedIn credentials are expired or unauthorized.", "metrics": []}
    if status_code == 403:
        return {
            "ok": False,
            "status": "failed",
            "error": "LinkedIn did not grant permission to read share statistics. The organization needs an analytics permission such as r_organization_social.",
            "metrics": [],
        }
    if status_code == 429:
        return {"ok": False, "status": "failed", "error": "LinkedIn rate limited the metrics read.", "metrics": []}
    if status_code >= 400:
        return {"ok": False, "status": "failed", "error": f"LinkedIn refused the metrics read ({status_code}).", "metrics": []}
    try:
        payload = response.json() or {}
    except Exception:
        return {"ok": False, "status": "failed", "error": "LinkedIn metrics response was not JSON.", "metrics": []}
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list) or not elements:
        return {
            "ok": True,
            "status": "unavailable",
            "error": "LinkedIn returned no share statistics.",
            "metrics": _blank("unavailable", "LinkedIn returned no share statistics."),
            "period_start": "",
            "period_end": "",
        }
    element = elements[0] if isinstance(elements[0], dict) else {}
    totals = element.get("totalShareStatistics") if isinstance(element.get("totalShareStatistics"), dict) else {}
    period = element.get("timeRange") if isinstance(element.get("timeRange"), dict) else {}
    return {
        "ok": True,
        "status": "recorded",
        "error": "",
        "metrics": _values(totals),
        "period_start": str(period.get("start") or ""),
        "period_end": str(period.get("end") or ""),
    }


def _values(totals: dict) -> list[dict]:
    rows: list[dict] = []
    for name, (field, definition) in METRIC_FIELDS.items():
        if field not in totals:
            rows.append({"metric_name": name, "definition": definition, "status": "unavailable", "value": None, "error": f"LinkedIn omitted {field}."})
            continue
        raw = totals.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int):
            rows.append({"metric_name": name, "definition": definition, "status": "unavailable", "value": None, "error": f"LinkedIn {field} was not an integer."})
            continue
        if raw < 0:
            rows.append({"metric_name": name, "definition": definition, "status": "unavailable", "value": None, "error": f"LinkedIn {field} was negative."})
            continue
        rows.append({
            "metric_name": name,
            "definition": definition,
            "status": "zero" if raw == 0 else "recorded",
            "value": raw,
            "error": "",
        })
    return rows


def _blank(status: str, error: str) -> list[dict]:
    return [
        {"metric_name": name, "definition": definition, "status": status, "value": None, "error": error}
        for name, (_field, definition) in METRIC_FIELDS.items()
    ]
