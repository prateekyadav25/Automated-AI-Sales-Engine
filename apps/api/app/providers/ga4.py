"""GA4 Data API runReport boundary for website traffic by source.

Contract: POST https://analyticsdata.googleapis.com/v1beta/properties/{id}:runReport
with OAuth scope analytics.readonly. Dimensions date, sessionSource,
sessionMedium, sessionCampaignName. Metrics sessions, totalUsers, keyEvents.
A metric GA4 omits stays null. The caller supplies the httpx-shaped client.
"""

from __future__ import annotations

from typing import Any

import httpx

RUN_REPORT = "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
DIMENSIONS = ("date", "sessionSource", "sessionMedium", "sessionCampaignName")
METRICS = ("sessions", "totalUsers", "keyEvents")


def _int(value: Any) -> int | None:
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def run_traffic_report(client: Any, *, token: str, property_id: str, start_date: str, end_date: str) -> dict:
    body = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": name} for name in DIMENSIONS],
        "metrics": [{"name": name} for name in METRICS],
        "limit": "10000",
    }
    try:
        response = client.post(
            RUN_REPORT.format(property_id=property_id),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
        )
    except (httpx.HTTPError, TimeoutError) as exc:
        return {"ok": False, "status": "failed", "error": f"GA4 request failed ({exc.__class__.__name__}).", "rows": []}
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code in {401, 403}:
        return {"ok": False, "status": "failed", "error": "GA4 refused the read. The Google connection needs analytics.readonly on this property.", "rows": []}
    if status_code == 429:
        return {"ok": False, "status": "failed", "error": "GA4 quota was exhausted. Nothing was stored.", "rows": []}
    if status_code >= 400:
        return {"ok": False, "status": "failed", "error": f"GA4 refused the report ({status_code}).", "rows": []}
    try:
        payload = response.json() or {}
    except (ValueError, TypeError):
        return {"ok": False, "status": "failed", "error": "GA4 response was not JSON.", "rows": []}
    headers = [str(item.get("name") or "") for item in payload.get("metricHeaders") or [] if isinstance(item, dict)]
    rows: list[dict] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        dims = [str((item or {}).get("value") or "") for item in row.get("dimensionValues") or []]
        values = [(item or {}).get("value") for item in row.get("metricValues") or []]
        if len(dims) != len(DIMENSIONS):
            continue
        by_name = {name: _int(values[index]) if index < len(values) else None for index, name in enumerate(headers)}
        day = dims[0]
        rows.append(
            {
                "day": f"{day[:4]}-{day[4:6]}-{day[6:8]}" if len(day) == 8 and day.isdigit() else day,
                "source": dims[1],
                "medium": dims[2],
                "campaign": dims[3],
                "sessions": by_name.get("sessions"),
                "total_users": by_name.get("totalUsers"),
                "key_events": by_name.get("keyEvents"),
            }
        )
    return {"ok": True, "status": "recorded" if rows else "unavailable", "error": "" if rows else "GA4 returned no rows for this range.", "rows": rows}
