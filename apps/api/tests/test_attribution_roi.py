from decimal import Decimal

from fastapi.testclient import TestClient

from app.db.session import get_session
from app.models.crm import Account, Lead, Opportunity
from app.models.identity import User
from app.models.lifecycle import Campaign
from app.services.roi import campaign_attribution
from sqlalchemy import select
from tests.conftest import login


def test_campaign_spend_versus_closed_revenue(client: TestClient) -> None:
    login(client)
    db = get_session()
    try:
        user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
        campaign = Campaign(tenant_id=user.tenant_id, created_by=user.id, name="Paid search", channel="linkedin", status="launched", spent=Decimal("100"))
        db.add(campaign)
        db.flush()
        account = Account(tenant_id=user.tenant_id, created_by=user.id, name="Attributed Co")
        db.add(account)
        db.flush()
        lead = Lead(
            tenant_id=user.tenant_id,
            created_by=user.id,
            account_id=account.id,
            first_name="Ada",
            last_name="Lovelace",
            email="ada.attr@example.com",
            company_name="Attributed Co",
            campaign_id=campaign.id,
            ad_id="ad-9",
            utm_source="linkedin",
            utm_medium="paid",
            utm_campaign="q3",
        )
        db.add(lead)
        db.flush()
        opp = Opportunity(
            tenant_id=user.tenant_id,
            created_by=user.id,
            account_id=account.id,
            name="Attributed deal",
            stage="closed_won",
            amount=Decimal("400"),
            campaign_id=lead.campaign_id,
            ad_id=lead.ad_id,
            utm_source=lead.utm_source,
            utm_medium=lead.utm_medium,
            utm_campaign=lead.utm_campaign,
        )
        db.add(opp)
        db.commit()
        report = campaign_attribution(db, tenant_id=user.tenant_id)
        row = next(item for item in report["campaigns"] if item["campaign_id"] == str(campaign.id))
        assert row["spend"] == 100
        assert row["closed_won_revenue"] == 400
        assert row["roas"] == 4
    finally:
        db.close()
