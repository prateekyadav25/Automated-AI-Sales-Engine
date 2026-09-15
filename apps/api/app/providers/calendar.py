import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings


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
class CalendarEventResult:
    ok: bool
    provider: str
    is_mock: bool
    provider_event_id: str = ""
    reason: str = ""
    retryable: bool = False


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

    def get_availability(self, *, calendar_id: str, start: datetime, end: datetime) -> list[BusyPeriod]:
        poster = self.http_post or httpx.post
        body = {
            "timeMin": start.astimezone(UTC).isoformat(),
            "timeMax": end.astimezone(UTC).isoformat(),
            "items": [{"id": calendar_id or "primary"}],
        }
        try:
            response = poster(
                "https://www.googleapis.com/calendar/v3/freeBusy",
                headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
                content=json.dumps(body),
                timeout=20.0,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_failure_at = datetime.now(UTC)
            self.last_error = str(exc)[:400]
            return []
        if getattr(response, "status_code", 200) >= 400:
            self.last_failure_at = datetime.now(UTC)
            self.last_error = f"Calendar freeBusy {response.status_code}"
            return []
        payload = response.json() if hasattr(response, "json") else {}
        calendars = payload.get("calendars") or {}
        busy = []
        for calendar in calendars.values():
            for period in calendar.get("busy") or []:
                busy.append(
                    BusyPeriod(
                        start=datetime.fromisoformat(period["start"].replace("Z", "+00:00")),
                        end=datetime.fromisoformat(period["end"].replace("Z", "+00:00")),
                    )
                )
        self.last_success_at = datetime.now(UTC)
        return busy

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
        poster = self.http_post or httpx.post
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
        return CalendarEventResult(
            ok=True,
            provider="google-calendar",
            is_mock=False,
            provider_event_id=str(data.get("id") or f"gcal-{uuid4()}"),
            reason="Google Calendar accepted the event.",
        )

    def reschedule(self, *, provider_event_id: str, start: datetime, end: datetime, timezone: str) -> CalendarEventResult:
        patcher = self.http_patch or httpx.patch
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
        deleter = self.http_delete or httpx.delete
        response = deleter(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{provider_event_id}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=20.0,
        )
        if getattr(response, "status_code", 200) >= 400:
            return CalendarEventResult(ok=False, provider="google-calendar", is_mock=False, reason=f"Calendar delete {response.status_code}")
        return CalendarEventResult(ok=True, provider="google-calendar", is_mock=False, provider_event_id=provider_event_id, reason="Cancelled.")


def get_calendar_provider(db: Session | None = None, tenant_id: UUID | None = None) -> CalendarProvider:
    settings = get_settings()
    mode = (settings.calendar_provider or "mock").strip().lower()
    if mode in {"microsoft", "outlook"}:
        return MicrosoftCalendarProvider()
    if mode == "google":
        if db is None or tenant_id is None:
            return DisconnectedGoogleCalendarProvider()
        # Circular: provider_accounts builds a live Calendar client from this module.
        from app.services.provider_accounts import calendar_provider_for_tenant

        return calendar_provider_for_tenant(db, tenant_id)
    return MockCalendarProvider()


def next_working_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(UTC)
    start = current.replace(minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=5)
