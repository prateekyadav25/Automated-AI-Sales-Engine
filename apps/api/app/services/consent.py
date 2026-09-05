from fastapi import HTTPException, status

from app.models.crm import Contact, Lead


def assert_can_email(lead: Lead) -> None:
    if lead.opt_out:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead has opted out")
    if not lead.consent_email:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email consent is required")


def assert_can_dial(contact: Contact, *, consent: bool) -> None:
    if contact.opt_out:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Contact has opted out")
    if not consent:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Voice consent is required to request a dial")
    if not (contact.phone or "").strip():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Contact has no phone number")
