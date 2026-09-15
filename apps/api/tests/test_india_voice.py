from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.crm import Contact
from app.services.consent import india_dial_block_reason
from app.services.voice_router import choose_carrier, destination_region


def test_destination_region_and_carrier() -> None:
    assert destination_region("+919876543210") == "IN"
    assert destination_region("+15551234567") == "INTL"
    assert choose_carrier(phone="+919876543210") == "exotel"
    assert choose_carrier(phone="+15551234567") == "twilio"
    assert choose_carrier(phone="+919876543210", override="twilio") == "twilio"


def test_india_ndnc_and_trai_gates() -> None:
    weekday = datetime(2026, 9, 11, 6, 30, tzinfo=ZoneInfo("UTC"))  # 12:00 IST Friday
    sunday = datetime(2026, 9, 13, 6, 30, tzinfo=ZoneInfo("UTC"))
    night = datetime(2026, 9, 11, 16, 30, tzinfo=ZoneInfo("UTC"))  # 22:00 IST
    blocked = Contact(first_name="A", last_name="B", phone="+919800000000", ndnc_status="DND", consent_voice=True, consent_recording=True)
    unknown = Contact(first_name="A", last_name="B", phone="+919800000000", ndnc_status="", consent_voice=True, consent_recording=True)
    clear = Contact(first_name="A", last_name="B", phone="+919800000000", ndnc_status="CLEAR", consent_voice=True, consent_recording=True)
    no_record = Contact(first_name="A", last_name="B", phone="+919800000000", ndnc_status="CLEAR", consent_voice=False, consent_recording=False)
    intl = Contact(first_name="A", last_name="B", phone="+15551230000", ndnc_status="", consent_voice=True)
    assert "NDNC" in (india_dial_block_reason(blocked, now=weekday) or "")
    assert "unknown" in (india_dial_block_reason(unknown, now=weekday) or "").lower()
    assert india_dial_block_reason(clear, now=weekday) is None
    assert "Recording-consent" in (india_dial_block_reason(no_record, now=weekday) or "")
    assert "Sunday" in (india_dial_block_reason(clear, now=sunday) or "")
    assert "10:00" in (india_dial_block_reason(clear, now=night) or "")
    assert india_dial_block_reason(intl, now=night) is None
