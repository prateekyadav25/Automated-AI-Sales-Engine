from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.crm import Contact, Lead
from app.services.voice_router import destination_region


def email_block_reason(lead: Lead) -> str | None:
    if lead.opt_out:
        return "Lead has opted out"
    if not lead.consent_email:
        return "Email consent is required"
    return None


def assert_can_email(lead: Lead) -> None:
    reason = email_block_reason(lead)
    if reason == "Lead has opted out":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead has opted out")
    if reason == "Email consent is required":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email consent is required")
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)


def voice_block_reason(contact: Contact, *, consent: bool) -> str | None:
    if contact.opt_out:
        return "Contact has opted out"
    stored = bool(getattr(contact, "consent_voice", False))
    if not consent and not stored:
        return "Voice consent is required to request a dial"
    preferred = (getattr(contact, "preferred_channel", "EMAIL") or "EMAIL").upper()
    if preferred in {"EMAIL", "WHATSAPP", "NONE"} and not (consent or stored):
        return "Voice is not the preferred channel"
    if preferred == "NONE":
        return "Contact channel preference is NONE"
    if not (contact.phone or "").strip():
        return "Contact has no phone number"
    return None


def assert_can_dial(contact: Contact, *, consent: bool) -> None:
    reason = voice_block_reason(contact, consent=consent)
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)


def india_dial_block_reason(contact: Contact, *, now: datetime | None = None) -> str | None:
    phone = (contact.phone or "").strip()
    if destination_region(phone) != "IN":
        return None
    ndnc = (getattr(contact, "ndnc_status", "") or "").strip().upper()
    if ndnc in {"DND", "NDNC", "BLOCKED"}:
        return "Number is on NDNC/DND and cannot be dialed"
    if not ndnc or ndnc in {"UNKNOWN", ""}:
        provider = (get_settings().ndnc_provider or "local").strip().lower()
        if provider in {"", "not_configured"}:
            return "NDNC/DND scrubbing is not configured for India dials"
        if provider == "local" and ndnc != "CLEAR":
            return "NDNC/DND status is unknown. Scrub the number before an India dial"
    if not bool(getattr(contact, "consent_recording", False) or getattr(contact, "consent_voice", False)):
        return "Recording-consent announcement requires voice or recording consent for India dials"
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(ZoneInfo("Asia/Kolkata"))
    if local.weekday() == 6:
        return "TRAI calling window does not allow Sunday promotional dials"
    minutes = local.hour * 60 + local.minute
    if minutes < 10 * 60 or minutes >= 21 * 60:
        return "TRAI calling window is 10:00–21:00 IST"
    return None


def assert_can_dial_india(contact: Contact, *, now: datetime | None = None) -> None:
    reason = india_dial_block_reason(contact, now=now)
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)


def whatsapp_block_reason(lead: Lead | None = None, contact: Contact | None = None) -> str | None:
    target = contact or lead
    if target is None:
        return "No WhatsApp recipient"
    if getattr(target, "opt_out", False):
        return "Recipient has opted out"
    if not getattr(target, "consent_whatsapp", False):
        return "WhatsApp consent is required"
    return None


def assert_can_whatsapp(lead: Lead | None = None, contact: Contact | None = None) -> None:
    reason = whatsapp_block_reason(lead, contact)
    if reason:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
