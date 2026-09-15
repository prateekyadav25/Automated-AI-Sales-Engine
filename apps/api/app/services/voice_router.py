from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.identity import Tenant
from app.providers.voice import TranscriptIngest, VoiceHealth, VoiceProvider, VoiceSession
from app.providers.voice import get_voice_provider as get_process_voice_provider
from app.providers.voice_conversation import (
    HumanHandoffConversation,
    MockConversationProvider,
    NotConfiguredConversationProvider,
    SelfHostedConversation,
    VapiConversationProvider,
    VoiceConversationProvider,
)
from app.providers.voice_telephony import (
    ExotelTelephonyProvider,
    MockTelephonyProvider,
    NotConfiguredTelephonyProvider,
    TwilioTelephonyProvider,
    VoiceTelephonyProvider,
    telephony_status_callback,
)
from app.services.autopilot_settings import get_or_create_settings
from app.services.provider_resolve import resolve_channel
from app.services.voice_scripts import current_published_body
from app.services.webhook_routes import demo_routing_token, ensure_route


def destination_region(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("91") or (phone or "").strip().startswith("+91"):
        return "IN"
    return "INTL"


def choose_carrier(*, phone: str, override: str = "") -> str:
    if override in {"exotel", "twilio", "mock"}:
        return override
    return "exotel" if destination_region(phone) == "IN" else "twilio"


def _telephony_from_resolved(kind: str, resolved) -> VoiceTelephonyProvider:
    if resolved.mode == "MOCK":
        return MockTelephonyProvider()
    if resolved.mode != "LIVE":
        return NotConfiguredTelephonyProvider(kind)
    secrets = resolved.secrets
    if kind == "exotel":
        sid = secrets.get("sid") or secrets.get("account_id") or ""
        if not (sid and secrets.get("api_key") and secrets.get("access_token") and secrets.get("caller_id")):
            return NotConfiguredTelephonyProvider("exotel")
        return ExotelTelephonyProvider(
            sid=sid,
            api_key=secrets.get("api_key") or "",
            api_token=secrets.get("access_token") or "",
            caller_id=secrets.get("caller_id") or "",
            subdomain=secrets.get("subdomain") or "api.exotel.com",
        )
    if kind == "twilio":
        if not (secrets.get("account_sid") and secrets.get("access_token") and secrets.get("from_number")):
            return NotConfiguredTelephonyProvider("twilio")
        return TwilioTelephonyProvider(
            account_sid=secrets.get("account_sid") or "",
            auth_token=secrets.get("access_token") or "",
            from_number=secrets.get("from_number") or "",
            twiml_url=secrets.get("twiml_url") or get_settings().twilio_twiml_url,
        )
    return MockTelephonyProvider()


def _conversation_from_resolved(kind: str, resolved) -> VoiceConversationProvider:
    if kind == "human":
        return HumanHandoffConversation(dest_number=resolved.secrets.get("from_number") or "")
    if kind == "self":
        return SelfHostedConversation()
    if resolved.mode == "MOCK":
        return MockConversationProvider()
    if resolved.mode != "LIVE":
        return NotConfiguredConversationProvider(kind)
    if kind == "vapi":
        if not resolved.secrets.get("access_token"):
            return NotConfiguredConversationProvider("vapi")
        return VapiConversationProvider(
            api_key=resolved.secrets.get("access_token") or "",
            assistant_id=resolved.secrets.get("assistant_id") or "",
            phone_number_id=resolved.secrets.get("phone_number_id") or "",
        )
    return MockConversationProvider()


class VoiceRouter:
    """Composes independent telephony and conversation providers. Implements VoiceProvider for Autopilot."""

    def __init__(
        self,
        *,
        telephony: VoiceTelephonyProvider,
        conversation: VoiceConversationProvider,
        carrier: str,
        conversation_name: str,
        region: str,
        status_callback: str = "",
        script: str = "",
    ) -> None:
        self.telephony = telephony
        self.conversation = conversation
        self.carrier = carrier
        self.conversation_name = conversation_name
        self.region = region
        self.status_callback = status_callback
        self.script = script

    def health(self) -> VoiceHealth:
        tel = self.telephony.health()
        conv = self.conversation.health()
        connected = tel.connected
        reason = f"carrier={self.carrier} ({tel.reason}) conversation={self.conversation_name} ({conv.reason})"
        return VoiceHealth(provider=self.carrier, is_mock=tel.is_mock, connected=connected, reason=reason)

    def start_session(self, *, to_number: str, from_label: str = "") -> VoiceSession:
        session = self.telephony.dial(
            to_number=to_number,
            from_label=from_label,
            status_callback=self.status_callback,
            record=True,
            announcement=self.script[:240] if self.script else "",
        )
        if session.ok and session.session_id:
            attached = self.conversation.attach(session_id=session.session_id, to_number=to_number, script=self.script)
            if attached.provider == "vapi" and attached.ok and attached.session_id:
                return VoiceSession(
                    ok=True,
                    session_id=session.session_id,
                    provider=self.carrier,
                    is_mock=False,
                    call_status=session.call_status or "QUEUED",
                    reason=f"conversation={attached.provider}:{attached.session_id}",
                )
        return session

    def ingest_transcript(self, *, session_id: str, transcript: str) -> TranscriptIngest:
        return self.conversation.ingest_transcript(session_id=session_id, transcript=transcript)


def compose_voice_provider(db: Session, tenant_id: UUID, destination: str = "") -> VoiceProvider:
    settings_row = get_or_create_settings(db, tenant_id=tenant_id)
    carrier = choose_carrier(phone=destination, override=(settings_row.voice_telephony_override or "").strip().lower())
    conversation_name = (settings_row.voice_conversation_provider or get_settings().voice_conversation_provider or "vapi").strip().lower()
    tel_resolved = resolve_channel(db, tenant_id, carrier if carrier in {"exotel", "twilio"} else "twilio")
    conv_resolved = resolve_channel(db, tenant_id, "vapi" if conversation_name == "vapi" else conversation_name)
    telephony = _telephony_from_resolved(carrier, tel_resolved)
    conversation = _conversation_from_resolved(conversation_name, conv_resolved)
    callback = ""
    if tel_resolved.mode == "LIVE":
        tenant = db.get(Tenant, tenant_id)
        known = demo_routing_token(tenant.slug, carrier) if tenant and tenant.slug else None
        token = ensure_route(db, tenant_id=tenant_id, provider=carrier, raw_token=known)
        if token:
            callback = telephony_status_callback(carrier, token)
    script, _version_id = current_published_body(db, tenant_id)
    return VoiceRouter(
        telephony=telephony,
        conversation=conversation,
        carrier=carrier,
        conversation_name=conversation_name,
        region=destination_region(destination),
        status_callback=callback,
        script=script,
    )


def get_voice_provider(db: Session | None = None, tenant_id: UUID | None = None, destination: str = "") -> VoiceProvider:
    if db is not None and tenant_id is not None:
        return compose_voice_provider(db, tenant_id, destination)
    return get_process_voice_provider()
