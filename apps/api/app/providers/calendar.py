"""Google Calendar API v3 adapter.

Checked against the Calendar API events resource and events.insert on
2026-10-28. conferenceDataVersion defaults to 0, which drops conference
data, so Meet creation sends version 1. A client-chosen event id is the
documented way to address one event again. Google does not promise that an
id collision is visible at insert time, so an unknown insert is read back
with events.get and is not inserted again. Reusing a conference requestId
on the same event ignores the new conference request. It does not stop a
second event. sendUpdates is sent explicitly. The documented default is
false, and some mail can still be sent when the value is none. hangoutLink,
conferenceId, and the event id are different fields. calendar.events does
not prove freeBusy access. A Gmail token is not a calendar grant. Live
create, freeBusy, and Meet delivery were not called from this milestone.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
NO_LIVE_CALENDAR = "This booking does not open a live Google client. Nothing was created."
MEET_SOLUTION = "hangoutsMeet"


@dataclass(frozen=True)
class CalendarHealth:
    provider: str
    is_mock: bool
    connected: bool
    reason: str
    state: str = "MOCK"
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error_summary: str = ""


@dataclass(frozen=True)
class BusyPeriod:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class AvailabilityRead:
    ok: bool
    busy: list[BusyPeriod]
    reason: str = ""
    retrieved_at: datetime | None = None


@dataclass(frozen=True)
class CalendarEventResult:
    ok: bool
    provider: str
    is_mock: bool
    provider_event_id: str = ""
    reason: str = ""
    retryable: bool = False
    conference_id: str = ""
    join_url: str = ""
    conference_status: str = ""
    unknown: bool = False
    http_status: int = 0
    calendar_id: str = ""


class CalendarProvider(Protocol):
    def health(self) -> CalendarHealth: ...

    def get_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> list[BusyPeriod]: ...

    def create_event(
        self,
        *,
        title: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        timezone: str,
        description: str = "",
    ) -> CalendarEventResult: ...

    def reschedule(self, *, provider_event_id: str, start: datetime, end: datetime, timezone: str) -> CalendarEventResult: ...

    def cancel(self, *, provider_event_id: str) -> CalendarEventResult: ...


class MockCalendarProvider:
    busy: list[BusyPeriod] = []

    def health(self) -> CalendarHealth:
        return CalendarHealth(
            provider="mock-calendar",
            is_mock=True,
            connected=True,
            reason="Labeled mock. Booking persists a local event id. Live Google Calendar is not configured.",
            state="MOCK",
        )

    def get_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> list[BusyPeriod]:
        _ = calendar_id, start, end
        return list(self.busy)

    def read_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> AvailabilityRead:
        _ = calendar_id
        return AvailabilityRead(ok=True, busy=list(self.busy), reason="Mock availability. No live calendar was read.", retrieved_at=datetime.now(UTC))

    def create_event(
        self,
        *,
        title: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        timezone: str,
        description: str = "",
    ) -> CalendarEventResult:
        _ = title, start, end, attendees, timezone, description
        return CalendarEventResult(
            ok=True,
            provider="mock-calendar",
            is_mock=True,
            provider_event_id=f"mock-cal-{uuid4()}",
            reason="Mock calendar event stored. No live calendar was contacted.",
        )

    def reschedule(self, *, provider_event_id: str, start: datetime, end: datetime, timezone: str) -> CalendarEventResult:
        _ = start, end, timezone
        return CalendarEventResult(
            ok=True,
            provider="mock-calendar",
            is_mock=True,
            provider_event_id=provider_event_id,
            reason="Mock calendar event rescheduled.",
        )

    def cancel(self, *, provider_event_id: str) -> CalendarEventResult:
        return CalendarEventResult(
            ok=True,
            provider="mock-calendar",
            is_mock=True,
            provider_event_id=provider_event_id,
            reason="Mock calendar event cancelled.",
        )


class DisconnectedGoogleCalendarProvider:
    def health(self) -> CalendarHealth:
        return CalendarHealth(
            provider="google-calendar",
            is_mock=False,
            connected=False,
            reason="CALENDAR_PROVIDER is google but no connected account with calendar scopes exists.",
            state="NOT_CONFIGURED",
        )

    def get_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> list[BusyPeriod]:
        _ = calendar_id, start, end
        return []

    def read_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> AvailabilityRead:
        _ = calendar_id, start, end
        return AvailabilityRead(ok=False, busy=[], reason=self.health().reason)

    def create_event(
        self,
        *,
        title: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        timezone: str,
        description: str = "",
    ) -> CalendarEventResult:
        _ = title, start, end, attendees, timezone, description
        return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason="BLOCKED BY CONFIGURATION")

    def reschedule(self, *, provider_event_id: str, start: datetime, end: datetime, timezone: str) -> CalendarEventResult:
        return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason="BLOCKED BY CONFIGURATION")

    def cancel(self, *, provider_event_id: str) -> CalendarEventResult:
        return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason="BLOCKED BY CONFIGURATION")


class MicrosoftCalendarProvider:
    def health(self) -> CalendarHealth:
        return CalendarHealth(
            provider="microsoft-calendar",
            is_mock=False,
            connected=False,
            reason="Microsoft Calendar is a protocol stub in this batch.",
            state="NOT_CONFIGURED",
        )

    def get_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> list[BusyPeriod]:
        return []

    def create_event(
        self,
        *,
        title: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        timezone: str,
        description: str = "",
    ) -> CalendarEventResult:
        return CalendarEventResult(ok=False, provider="microsoft-calendar", is_mock=False, reason="Microsoft Calendar is not implemented.")

    def reschedule(self, *, provider_event_id: str, start: datetime, end: datetime, timezone: str) -> CalendarEventResult:
        return CalendarEventResult(ok=False, provider="microsoft-calendar", is_mock=False, reason="Microsoft Calendar is not implemented.")

    def cancel(self, *, provider_event_id: str) -> CalendarEventResult:
        return CalendarEventResult(ok=False, provider="microsoft-calendar", is_mock=False, reason="Microsoft Calendar is not implemented.")


@dataclass
class GoogleCalendarProvider:
    access_token: str
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str = ""
    http_post: object | None = None
    http_get: object | None = None
    http_patch: object | None = None
    http_delete: object | None = None

    def health(self) -> CalendarHealth:
        connected = bool(self.access_token)
        return CalendarHealth(
            provider="google-calendar",
            is_mock=False,
            connected=connected,
            reason="Google Calendar token present." if connected else "Google Calendar access token is missing.",
            state="CONNECTED" if connected else "NOT_CONFIGURED",
            last_success_at=self.last_success_at,
            last_failure_at=self.last_failure_at,
            last_error_summary=self.last_error,
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def read_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> AvailabilityRead:
        if self.http_post is None:
            return AvailabilityRead(ok=False, busy=[], reason=NO_LIVE_CALENDAR)
        target = calendar_id or "primary"
        body = {
            "timeMin": start.astimezone(UTC).isoformat(),
            "timeMax": end.astimezone(UTC).isoformat(),
            "items": [{"id": target}],
        }
        try:
            response = self.http_post(
                f"{CALENDAR_API}/freeBusy",
                headers=self._headers(),
                content=json.dumps(body),
                timeout=20.0,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_failure_at = datetime.now(UTC)
            self.last_error = str(exc)[:400]
            return AvailabilityRead(ok=False, busy=[], reason="Availability could not be read.")
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 429:
            return AvailabilityRead(ok=False, busy=[], reason="Calendar availability was rate limited.")
        if status_code in {401, 403}:
            return AvailabilityRead(ok=False, busy=[], reason="Calendar availability permission was refused.")
        if status_code >= 400 or status_code == 0:
            return AvailabilityRead(ok=False, busy=[], reason="Availability could not be read.")
        payload = response.json() if hasattr(response, "json") else {}
        calendars = payload.get("calendars") if isinstance(payload, dict) else None
        if not isinstance(calendars, dict) or target not in calendars:
            return AvailabilityRead(ok=False, busy=[], reason="Availability response did not include the selected calendar.")
        calendar = calendars[target] or {}
        if calendar.get("errors"):
            return AvailabilityRead(ok=False, busy=[], reason="The selected calendar did not return availability.")
        busy: list[BusyPeriod] = []
        for period in calendar.get("busy") or []:
            busy.append(
                BusyPeriod(
                    start=datetime.fromisoformat(str(period["start"]).replace("Z", "+00:00")),
                    end=datetime.fromisoformat(str(period["end"]).replace("Z", "+00:00")),
                )
            )
        self.last_success_at = datetime.now(UTC)
        return AvailabilityRead(ok=True, busy=busy, retrieved_at=datetime.now(UTC))

    def get_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> list[BusyPeriod]:
        reading = self.read_availability(calendar_id=calendar_id, start=start, end=end)
        return reading.busy if reading.ok else []

    def create_meet_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        request_id: str,
        title: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        timezone: str,
        description: str = "",
        send_updates: str = "none",
    ) -> CalendarEventResult:
        if self.http_post is None:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=NO_LIVE_CALENDAR, calendar_id=calendar_id)
        updates = send_updates if send_updates in {"none", "all", "externalOnly"} else "none"
        target = quote(calendar_id or "primary", safe="")
        payload = {
            "id": event_id,
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
            "attendees": [{"email": email} for email in attendees if email],
            "conferenceData": {
                "createRequest": {
                    "requestId": request_id,
                    "conferenceSolutionKey": {"type": MEET_SOLUTION},
                }
            },
        }
        url = f"{CALENDAR_API}/calendars/{target}/events?conferenceDataVersion=1&sendUpdates={updates}"
        try:
            response = self.http_post(url, headers=self._headers(), content=json.dumps(payload), timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            self.last_failure_at = datetime.now(UTC)
            self.last_error = str(exc)[:400]
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=True,
                reason="Calendar create did not return a result.",
                unknown=True,
                calendar_id=calendar_id,
            )
        return _meet_result(response, calendar_id=calendar_id, fallback_event_id="")

    def get_event(self, *, calendar_id: str, event_id: str) -> CalendarEventResult:
        if self.http_get is None:
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=False,
                reason="The calendar event could not be read back.",
                unknown=True,
                calendar_id=calendar_id,
            )
        target = quote(calendar_id or "primary", safe="")
        event = quote(event_id, safe="")
        url = f"{CALENDAR_API}/calendars/{target}/events/{event}"
        try:
            response = self.http_get(url, headers=self._headers(), timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)[:400]
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=True,
                reason="Calendar read did not return a result.",
                unknown=True,
                calendar_id=calendar_id,
            )
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 404:
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=True,
                reason="The calendar event was not found.",
                http_status=404,
                calendar_id=calendar_id,
            )
        return _meet_result(response, calendar_id=calendar_id, fallback_event_id="")

    def reschedule_meet(
        self,
        *,
        calendar_id: str,
        event_id: str,
        start: datetime,
        end: datetime,
        timezone: str,
        send_updates: str = "none",
    ) -> CalendarEventResult:
        if self.http_patch is None:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=NO_LIVE_CALENDAR, calendar_id=calendar_id)
        updates = send_updates if send_updates in {"none", "all", "externalOnly"} else "none"
        target = quote(calendar_id or "primary", safe="")
        event = quote(event_id, safe="")
        payload = {
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        }
        url = f"{CALENDAR_API}/calendars/{target}/events/{event}?conferenceDataVersion=1&sendUpdates={updates}"
        try:
            response = self.http_patch(url, headers=self._headers(), content=json.dumps(payload), timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)[:400]
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=True,
                reason="Calendar update did not return a result.",
                unknown=True,
                provider_event_id=event_id,
                calendar_id=calendar_id,
            )
        return _meet_result(response, calendar_id=calendar_id, fallback_event_id=event_id)

    def cancel_meet(self, *, calendar_id: str, event_id: str, send_updates: str = "none") -> CalendarEventResult:
        if self.http_delete is None:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=NO_LIVE_CALENDAR, calendar_id=calendar_id)
        updates = send_updates if send_updates in {"none", "all", "externalOnly"} else "none"
        target = quote(calendar_id or "primary", safe="")
        event = quote(event_id, safe="")
        url = f"{CALENDAR_API}/calendars/{target}/events/{event}?sendUpdates={updates}"
        try:
            response = self.http_delete(url, headers=self._headers(), timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)[:400]
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=True,
                reason="Calendar cancel did not return a result.",
                unknown=True,
                provider_event_id=event_id,
                calendar_id=calendar_id,
            )
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code in {200, 204}:
            return CalendarEventResult(
                ok=True,
                provider="google-calendar",
                is_mock=True,
                provider_event_id=event_id,
                reason="Google Calendar cancelled the event.",
                http_status=status_code,
                calendar_id=calendar_id,
            )
        if status_code == 404:
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=True,
                provider_event_id=event_id,
                reason="The calendar event was not found.",
                http_status=404,
                calendar_id=calendar_id,
            )
        return _meet_result(response, calendar_id=calendar_id, fallback_event_id=event_id)

    def create_event(
        self,
        *,
        title: str,
        start: datetime,
        end: datetime,
        attendees: list[str],
        timezone: str,
        description: str = "",
    ) -> CalendarEventResult:
        if self.http_post is None:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=NO_LIVE_CALENDAR)
        poster = self.http_post
        payload = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
            "attendees": [{"email": email} for email in attendees if email],
        }
        try:
            response = poster(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
                content=json.dumps(payload),
                timeout=20.0,
            )
        except Exception as exc:  # noqa: BLE001
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=str(exc)[:400], retryable=True)
        if getattr(response, "status_code", 200) >= 400:
            retryable = getattr(response, "status_code", 500) >= 500 or getattr(response, "status_code", 0) == 429
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=False,
                reason=f"Calendar create {response.status_code}",
                retryable=retryable,
            )
        data = response.json() if hasattr(response, "json") else {}
        event_id = str(data.get("id") or "")
        if not event_id:
            return CalendarEventResult(
                ok=False,
                provider="google-calendar",
                is_mock=True,
                reason="Calendar create returned no event id.",
                unknown=True,
                http_status=int(getattr(response, "status_code", 0) or 0),
            )
        return CalendarEventResult(
            ok=True,
            provider="google-calendar",
            is_mock=True,
            provider_event_id=event_id,
            reason="Google Calendar accepted the event.",
            http_status=int(getattr(response, "status_code", 0) or 0),
        )

    def reschedule(self, *, provider_event_id: str, start: datetime, end: datetime, timezone: str) -> CalendarEventResult:
        if self.http_patch is None:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=NO_LIVE_CALENDAR)
        patcher = self.http_patch
        payload = {
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        }
        response = patcher(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{provider_event_id}",
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
            content=json.dumps(payload),
            timeout=20.0,
        )
        if getattr(response, "status_code", 200) >= 400:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=f"Calendar patch {response.status_code}")
        return CalendarEventResult(ok=True, provider="google-calendar", is_mock=False, provider_event_id=provider_event_id, reason="Rescheduled.")

    def cancel(self, *, provider_event_id: str) -> CalendarEventResult:
        if self.http_delete is None:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=NO_LIVE_CALENDAR)
        deleter = self.http_delete
        response = deleter(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{provider_event_id}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=20.0,
        )
        if getattr(response, "status_code", 200) >= 400:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=f"Calendar delete {response.status_code}")
        return CalendarEventResult(ok=True, provider="google-calendar", is_mock=False, provider_event_id=provider_event_id, reason="Cancelled.")


def _meet_result(response: object, *, calendar_id: str, fallback_event_id: str) -> CalendarEventResult:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code in {401, 403}:
        return CalendarEventResult(
            ok=False,
            provider="google-calendar",
            is_mock=True,
            reason="Calendar permission was refused.",
            http_status=status_code,
            calendar_id=calendar_id,
        )
    if status_code == 429:
        return CalendarEventResult(
            ok=False,
            provider="google-calendar",
            is_mock=True,
            reason="Calendar request was rate limited.",
            http_status=status_code,
            calendar_id=calendar_id,
        )
    if status_code == 409 or status_code >= 500 or status_code == 0:
        return CalendarEventResult(
            ok=False,
            provider="google-calendar",
            is_mock=True,
            reason="Calendar create did not return a confirmed event.",
            unknown=True,
            http_status=status_code,
            provider_event_id=fallback_event_id,
            calendar_id=calendar_id,
        )
    if status_code >= 400:
        return CalendarEventResult(
            ok=False,
            provider="google-calendar",
            is_mock=True,
            reason=f"Calendar request failed ({status_code}).",
            http_status=status_code,
            calendar_id=calendar_id,
        )
    data = response.json() if hasattr(response, "json") else {}
    if not isinstance(data, dict):
        data = {}
    event_id = str(data.get("id") or "")
    conference = data.get("conferenceData") if isinstance(data.get("conferenceData"), dict) else {}
    conference_id = str(conference.get("conferenceId") or "")
    request = conference.get("createRequest") if isinstance(conference.get("createRequest"), dict) else {}
    request_status = request.get("status") if isinstance(request.get("status"), dict) else {}
    conference_status = str(request_status.get("statusCode") or "")
    join_url = ""
    for point in conference.get("entryPoints") or []:
        if isinstance(point, dict) and point.get("entryPointType") == "video" and point.get("uri"):
            join_url = str(point["uri"])
            break
    if not join_url and data.get("hangoutLink"):
        join_url = str(data["hangoutLink"])
    if not event_id:
        return CalendarEventResult(
            ok=False,
            provider="google-calendar",
            is_mock=True,
            reason="Calendar response had no event id.",
            unknown=True,
            http_status=status_code,
            calendar_id=calendar_id,
        )
    if not conference_status and join_url and conference_id:
        conference_status = "success"
    completed = conference_status == "success" and bool(join_url)
    reason = "Google Calendar returned the event."
    if conference_status == "pending":
        reason = "The event exists and the Meet conference is still pending."
    elif conference_status == "failure":
        reason = "The event exists and Meet conference creation failed."
    elif not completed:
        reason = "The event exists without a usable Meet conference."
    return CalendarEventResult(
        ok=completed,
        provider="google-calendar",
        is_mock=True,
        provider_event_id=event_id,
        conference_id=conference_id,
        join_url=join_url,
        conference_status=conference_status,
        reason=reason,
        http_status=status_code,
        calendar_id=calendar_id,
    )


def get_calendar_provider(
    db: Session | None = None, tenant_id: UUID | None = None, *, refresh: bool = True
) -> CalendarProvider:
    settings = get_settings()
    mode = (settings.calendar_provider or "mock").strip().lower()
    if mode in {"microsoft", "outlook"}:
        return MicrosoftCalendarProvider()
    if mode == "google":
        if db is None or tenant_id is None:
            return DisconnectedGoogleCalendarProvider()
        # Circular: provider_accounts builds a live Calendar client from this module.
        from app.services.provider_accounts import calendar_provider_for_tenant

        return calendar_provider_for_tenant(db, tenant_id, refresh=refresh)
    return MockCalendarProvider()


def next_working_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(UTC)
    start = current.replace(minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=5)
