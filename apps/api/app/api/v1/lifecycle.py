from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.crm import Account, Customer, Lead, Opportunity, Renewal
from app.models.lifecycle import (
    AbmPlay,
    AdvocacyAsset,
    Campaign,
    CampaignMember,
    Conversation,
    DealInsight,
    ForecastSnapshot,
    HealthScore,
    MeetingRecord,
    ModelCard,
    OnboardingMilestone,
    OnboardingPlan,
    Playbook,
    Product,
    Quote,
    QuoteLine,
    Referral,
    Sequence,
    SequenceEnrollment,
    SequenceStep,
    WhitespaceCell,
)
from app.models.workflow import WorkflowRun
from app.schemas.common import Envelope, Meta
from app.schemas.crm import CustomerOut
from app.schemas.lifecycle import (
    AbmIn,
    AbmOut,
    AccountLifecycleOut,
    AdvocacyIn,
    AdvocacyOut,
    CampaignDetail,
    CampaignIn,
    CampaignLaunchOut,
    CampaignMemberIn,
    CampaignMemberOut,
    CampaignOut,
    ConversationIn,
    ConversationOut,
    DealInsightOut,
    EnrollIn,
    EnrollmentOut,
    ForecastOut,
    HealthOut,
    LifecycleOverview,
    MeetingExtractIn,
    MeetingIn,
    MeetingOut,
    MilestoneOut,
    ModelCardOut,
    PlaybookIn,
    PlaybookOut,
    PlaybookRunIn,
    ProductIn,
    ProductOut,
    QuoteIn,
    QuoteLineIn,
    QuoteLineOut,
    QuoteOut,
    ReferralIn,
    ReferralOut,
    RenewalOut,
    SequenceDetail,
    SequenceIn,
    SequenceOut,
    SequenceStepOut,
    SuccessRow,
    VoiceDialIn,
    VoiceDialOut,
    WhitespaceOut,
    WorkflowRunOut,
)
from app.services.ads import queue_campaign_launch
from app.services.audit import write_audit
from app.services.lifecycle import (
    build_forecast,
    create_quote,
    enroll_sequence,
    fill_whitespace,
    lifecycle_pulse,
    recompute_quote,
    record_conversation,
    run_playbook,
    score_deal,
    score_health,
)
from app.services.query import get_owned, paginate
from app.services.voice import extract_meeting_notes, queue_voice_dial

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


def _quote_out(db: Session, quote: Quote) -> QuoteOut:
    lines = db.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id, QuoteLine.deleted_at.is_(None))).all()
    payload = QuoteOut.model_validate(quote)
    payload.lines = [QuoteLineOut.model_validate(row) for row in lines]
    return payload


def _insight_out(db: Session, tenant_id, row: DealInsight) -> DealInsightOut:
    opp = db.scalar(select(Opportunity).where(Opportunity.id == row.opportunity_id, Opportunity.tenant_id == tenant_id))
    payload = DealInsightOut.model_validate(row)
    payload.opportunity_name = opp.name if opp else ""
    return payload


def _whitespace_out(db: Session, tenant_id, row) -> WhitespaceOut:
    account = db.scalar(select(Account).where(Account.id == row.account_id, Account.tenant_id == tenant_id))
    product = db.scalar(select(Product).where(Product.id == row.product_id, Product.tenant_id == tenant_id))
    payload = WhitespaceOut.model_validate(row)
    payload.account_name = account.name if account else ""
    payload.product_name = product.name if product else ""
    return payload


def _health_out(row: HealthScore | None) -> HealthOut | None:
    return HealthOut.model_validate(row) if row else None


@router.get("/overview", response_model=Envelope[LifecycleOverview])
def overview(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("command_center.read"))],
) -> Envelope[LifecycleOverview]:
    return Envelope(data=LifecycleOverview.model_validate(lifecycle_pulse(db, ctx.tenant_id)))


@router.get("/campaigns", response_model=Envelope[list[CampaignOut]])
def list_campaigns(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
    page: int = 1,
    page_size: int = 25,
) -> Envelope[list[CampaignOut]]:
    stmt = select(Campaign).where(Campaign.tenant_id == ctx.tenant_id, Campaign.deleted_at.is_(None)).order_by(Campaign.created_at.desc())
    rows, total = paginate(db, stmt, page, page_size)
    return Envelope(data=[CampaignOut.model_validate(row) for row in rows], meta=Meta(page=page, page_size=page_size, total=total))


@router.post("/campaigns", response_model=Envelope[CampaignOut])
def create_campaign(
    body: CampaignIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[CampaignOut]:
    row = Campaign(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    write_audit(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="campaign.create", entity_type="campaign", entity_id="pending", after=body.model_dump(), correlation_id=ctx.correlation_id)
    db.commit()
    db.refresh(row)
    return Envelope(data=CampaignOut.model_validate(row))


@router.post("/campaigns/{campaign_id}/launch", response_model=Envelope[CampaignLaunchOut])
def launch_campaign(
    campaign_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[CampaignLaunchOut]:
    campaign = get_owned(db, Campaign, ctx.tenant_id, campaign_id)
    approval = queue_campaign_launch(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        campaign=campaign,
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    return Envelope(
        data=CampaignLaunchOut(approval_id=approval.id, campaign_id=campaign.id, status=campaign.status)
    )


@router.get("/campaigns/{campaign_id}", response_model=Envelope[CampaignDetail])
def get_campaign(
    campaign_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
) -> Envelope[CampaignDetail]:
    row = get_owned(db, Campaign, ctx.tenant_id, campaign_id)
    members = db.scalars(select(CampaignMember).where(CampaignMember.campaign_id == row.id, CampaignMember.deleted_at.is_(None))).all()
    payload = CampaignDetail.model_validate(row)
    payload.members = [CampaignMemberOut.model_validate(item) for item in members]
    return Envelope(data=payload)


@router.post("/campaigns/{campaign_id}/members", response_model=Envelope[CampaignMemberOut])
def add_campaign_member(
    campaign_id: UUID,
    body: CampaignMemberIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[CampaignMemberOut]:
    campaign = get_owned(db, Campaign, ctx.tenant_id, campaign_id)
    if body.account_id:
        get_owned(db, Account, ctx.tenant_id, body.account_id)
    row = CampaignMember(tenant_id=ctx.tenant_id, created_by=ctx.user.id, campaign_id=campaign.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=CampaignMemberOut.model_validate(row))


@router.get("/abm", response_model=Envelope[list[AbmOut]])
def list_abm(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.read"))],
) -> Envelope[list[AbmOut]]:
    rows = db.scalars(select(AbmPlay).where(AbmPlay.tenant_id == ctx.tenant_id, AbmPlay.deleted_at.is_(None))).all()
    return Envelope(data=[AbmOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/abm", response_model=Envelope[AbmOut])
def create_abm(
    body: AbmIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("campaigns.write"))],
) -> Envelope[AbmOut]:
    get_owned(db, Account, ctx.tenant_id, body.account_id)
    row = AbmPlay(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=AbmOut.model_validate(row))


@router.get("/sequences", response_model=Envelope[list[SequenceOut]])
def list_sequences(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("sequences.read"))],
) -> Envelope[list[SequenceOut]]:
    rows = db.scalars(select(Sequence).where(Sequence.tenant_id == ctx.tenant_id, Sequence.deleted_at.is_(None))).all()
    return Envelope(data=[SequenceOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/sequences", response_model=Envelope[SequenceDetail])
def create_sequence(
    body: SequenceIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("sequences.write"))],
) -> Envelope[SequenceDetail]:
    payload = body.model_dump(exclude={"steps"})
    row = Sequence(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **payload)
    db.add(row)
    db.flush()
    for step in body.steps:
        db.add(SequenceStep(tenant_id=ctx.tenant_id, created_by=ctx.user.id, sequence_id=row.id, **step.model_dump()))
    write_audit(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="sequence.create", entity_type="sequence", entity_id=str(row.id), after=payload, correlation_id=ctx.correlation_id)
    db.commit()
    db.refresh(row)
    steps = db.scalars(select(SequenceStep).where(SequenceStep.sequence_id == row.id).order_by(SequenceStep.position.asc())).all()
    detail = SequenceDetail.model_validate(row)
    detail.steps = [SequenceStepOut.model_validate(item) for item in steps]
    return Envelope(data=detail)


@router.get("/sequences/{sequence_id}", response_model=Envelope[SequenceDetail])
def get_sequence(
    sequence_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("sequences.read"))],
) -> Envelope[SequenceDetail]:
    row = get_owned(db, Sequence, ctx.tenant_id, sequence_id)
    steps = db.scalars(select(SequenceStep).where(SequenceStep.sequence_id == row.id).order_by(SequenceStep.position.asc())).all()
    detail = SequenceDetail.model_validate(row)
    detail.steps = [SequenceStepOut.model_validate(item) for item in steps]
    return Envelope(data=detail)


@router.post("/sequences/{sequence_id}/enroll", response_model=Envelope[EnrollmentOut])
def enroll(
    sequence_id: UUID,
    body: EnrollIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("sequences.write"))],
) -> Envelope[EnrollmentOut]:
    sequence = get_owned(db, Sequence, ctx.tenant_id, sequence_id)
    lead = get_owned(db, Lead, ctx.tenant_id, body.lead_id)
    row = enroll_sequence(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, sequence=sequence, lead=lead)
    write_audit(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="sequence.enroll", entity_type="sequence_enrollment", entity_id=str(row.id), after=body.model_dump(), correlation_id=ctx.correlation_id)
    db.commit()
    db.refresh(row)
    return Envelope(data=EnrollmentOut.model_validate(row))


@router.get("/enrollments", response_model=Envelope[list[EnrollmentOut]])
def list_enrollments(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("sequences.read"))],
) -> Envelope[list[EnrollmentOut]]:
    rows = db.scalars(select(SequenceEnrollment).where(SequenceEnrollment.tenant_id == ctx.tenant_id, SequenceEnrollment.deleted_at.is_(None))).all()
    return Envelope(data=[EnrollmentOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.get("/conversations", response_model=Envelope[list[ConversationOut]])
def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
) -> Envelope[list[ConversationOut]]:
    rows = db.scalars(select(Conversation).where(Conversation.tenant_id == ctx.tenant_id, Conversation.deleted_at.is_(None)).order_by(Conversation.created_at.desc())).all()
    return Envelope(data=[ConversationOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/conversations", response_model=Envelope[ConversationOut])
def create_conversation(
    body: ConversationIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("conversations.write"))],
) -> Envelope[ConversationOut]:
    if body.account_id:
        get_owned(db, Account, ctx.tenant_id, body.account_id)
    row = record_conversation(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, payload=body.model_dump())
    write_audit(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="conversation.create", entity_type="conversation", entity_id="pending", after={"channel": body.channel}, correlation_id=ctx.correlation_id)
    db.commit()
    db.refresh(row)
    return Envelope(data=ConversationOut.model_validate(row))


@router.post("/conversations/dial", response_model=Envelope[VoiceDialOut])
def request_dial(
    body: VoiceDialIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("conversations.write"))],
) -> Envelope[VoiceDialOut]:
    approval = queue_voice_dial(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        contact_id=body.contact_id,
        consent=body.consent,
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    return Envelope(data=VoiceDialOut(approval_id=approval.id, status=approval.status))


@router.get("/meetings", response_model=Envelope[list[MeetingOut]])
def list_meetings(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("meetings.read"))],
) -> Envelope[list[MeetingOut]]:
    rows = db.scalars(select(MeetingRecord).where(MeetingRecord.tenant_id == ctx.tenant_id, MeetingRecord.deleted_at.is_(None)).order_by(MeetingRecord.created_at.desc())).all()
    return Envelope(data=[MeetingOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/meetings", response_model=Envelope[MeetingOut])
def create_meeting(
    body: MeetingIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("meetings.write"))],
) -> Envelope[MeetingOut]:
    if body.account_id:
        get_owned(db, Account, ctx.tenant_id, body.account_id)
    if body.opportunity_id:
        get_owned(db, Opportunity, ctx.tenant_id, body.opportunity_id)
    row = MeetingRecord(tenant_id=ctx.tenant_id, created_by=ctx.user.id, provider="human", is_mock=False, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=MeetingOut.model_validate(row))


@router.post("/meetings/extract", response_model=Envelope[MeetingOut])
def extract_meeting(
    body: MeetingExtractIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("meetings.write"))],
) -> Envelope[MeetingOut]:
    if body.account_id:
        get_owned(db, Account, ctx.tenant_id, body.account_id)
    if body.opportunity_id:
        get_owned(db, Opportunity, ctx.tenant_id, body.opportunity_id)
    row = extract_meeting_notes(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        transcript=body.transcript,
        title=body.title,
        account_id=body.account_id,
        opportunity_id=body.opportunity_id,
        correlation_id=ctx.correlation_id,
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=MeetingOut.model_validate(row))


@router.get("/deals", response_model=Envelope[list[DealInsightOut]])
def list_deals(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("deals.read"))],
) -> Envelope[list[DealInsightOut]]:
    rows = db.scalars(select(DealInsight).where(DealInsight.tenant_id == ctx.tenant_id, DealInsight.deleted_at.is_(None))).all()
    return Envelope(data=[_insight_out(db, ctx.tenant_id, row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/deals/rescore", response_model=Envelope[list[DealInsightOut]])
def rescore_deals(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("deals.read"))],
) -> Envelope[list[DealInsightOut]]:
    opps = db.scalars(
        select(Opportunity).where(
            Opportunity.tenant_id == ctx.tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.stage.notin_(["closed_won", "closed_lost"]),
        )
    ).all()
    rows = [score_deal(db, ctx.tenant_id, opp) for opp in opps]
    db.commit()
    return Envelope(data=[_insight_out(db, ctx.tenant_id, row) for row in rows], meta=Meta(total=len(rows)))


@router.get("/products", response_model=Envelope[list[ProductOut]])
def list_products(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("commercial.read"))],
) -> Envelope[list[ProductOut]]:
    rows = db.scalars(select(Product).where(Product.tenant_id == ctx.tenant_id, Product.deleted_at.is_(None))).all()
    return Envelope(data=[ProductOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/products", response_model=Envelope[ProductOut])
def create_product(
    body: ProductIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("commercial.write"))],
) -> Envelope[ProductOut]:
    row = Product(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=ProductOut.model_validate(row))


@router.get("/quotes", response_model=Envelope[list[QuoteOut]])
def list_quotes(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("commercial.read"))],
) -> Envelope[list[QuoteOut]]:
    rows = db.scalars(select(Quote).where(Quote.tenant_id == ctx.tenant_id, Quote.deleted_at.is_(None)).order_by(Quote.created_at.desc())).all()
    return Envelope(data=[_quote_out(db, row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/quotes", response_model=Envelope[QuoteOut])
def post_quote(
    body: QuoteIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("commercial.write"))],
) -> Envelope[QuoteOut]:
    opp = get_owned(db, Opportunity, ctx.tenant_id, body.opportunity_id)
    row = create_quote(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        opportunity=opp,
        discount_pct=body.discount_pct,
        tax_pct=body.tax_pct,
        lines=[line.model_dump() for line in body.lines],
    )
    write_audit(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="quote.create", entity_type="quote", entity_id=str(row.id), after={"total": str(row.total)}, correlation_id=ctx.correlation_id)
    db.commit()
    db.refresh(row)
    return Envelope(data=_quote_out(db, row))


@router.get("/quotes/{quote_id}", response_model=Envelope[QuoteOut])
def get_quote(
    quote_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("commercial.read"))],
) -> Envelope[QuoteOut]:
    return Envelope(data=_quote_out(db, get_owned(db, Quote, ctx.tenant_id, quote_id)))


@router.post("/quotes/{quote_id}/lines", response_model=Envelope[QuoteOut])
def add_quote_line(
    quote_id: UUID,
    body: QuoteLineIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("commercial.write"))],
) -> Envelope[QuoteOut]:
    quote = get_owned(db, Quote, ctx.tenant_id, quote_id)
    product = get_owned(db, Product, ctx.tenant_id, body.product_id)
    quantity = max(1, body.quantity)
    unit = body.unit_price if body.unit_price is not None else product.list_price
    db.add(
        QuoteLine(
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            quote_id=quote.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=unit,
            line_total=(unit * quantity).quantize(Decimal("0.01")),
        )
    )
    db.flush()
    recompute_quote(db, quote)
    db.commit()
    db.refresh(quote)
    return Envelope(data=_quote_out(db, quote))


@router.get("/forecast", response_model=Envelope[list[ForecastOut]])
def list_forecast(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("forecast.read"))],
) -> Envelope[list[ForecastOut]]:
    rows = db.scalars(select(ForecastSnapshot).where(ForecastSnapshot.tenant_id == ctx.tenant_id, ForecastSnapshot.deleted_at.is_(None)).order_by(ForecastSnapshot.created_at.desc())).all()
    return Envelope(data=[ForecastOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/forecast/refresh", response_model=Envelope[ForecastOut])
def refresh_forecast(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("forecast.read"))],
) -> Envelope[ForecastOut]:
    row = build_forecast(db, ctx.tenant_id, ctx.user.id)
    db.commit()
    db.refresh(row)
    return Envelope(data=ForecastOut.model_validate(row))


@router.get("/success", response_model=Envelope[list[SuccessRow]])
def list_success(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.read"))],
) -> Envelope[list[SuccessRow]]:
    customers = db.scalars(select(Customer).where(Customer.tenant_id == ctx.tenant_id, Customer.deleted_at.is_(None))).all()
    rows = []
    for customer in customers:
        account = get_owned(db, Account, ctx.tenant_id, customer.account_id)
        health = db.scalar(select(HealthScore).where(HealthScore.tenant_id == ctx.tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None)))
        plan = db.scalar(select(OnboardingPlan).where(OnboardingPlan.tenant_id == ctx.tenant_id, OnboardingPlan.customer_id == customer.id, OnboardingPlan.deleted_at.is_(None)))
        milestones = []
        if plan:
            milestones = db.scalars(select(OnboardingMilestone).where(OnboardingMilestone.plan_id == plan.id, OnboardingMilestone.deleted_at.is_(None))).all()
        renewal = db.scalar(select(Renewal).where(Renewal.tenant_id == ctx.tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None)))
        customer_out = CustomerOut.model_validate(customer)
        customer_out.account_name = account.name
        rows.append(
            SuccessRow(
                customer=customer_out,
                account_id=account.id,
                account_name=account.name,
                health=_health_out(health),
                onboarding_status=plan.status if plan else "",
                milestones=[MilestoneOut.model_validate(item) for item in milestones],
                renewal_date=renewal.renewal_date if renewal else None,
                arr=customer.arr,
            )
        )
    return Envelope(data=rows, meta=Meta(total=len(rows)))


@router.post("/success/health/{customer_id}", response_model=Envelope[HealthOut])
def rescore_health(
    customer_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.write"))],
) -> Envelope[HealthOut]:
    customer = get_owned(db, Customer, ctx.tenant_id, customer_id)
    row = score_health(db, ctx.tenant_id, customer)
    db.commit()
    db.refresh(row)
    return Envelope(data=HealthOut.model_validate(row))


@router.get("/renewals", response_model=Envelope[list[RenewalOut]])
def list_renewals(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.read"))],
) -> Envelope[list[RenewalOut]]:
    rows = db.scalars(select(Renewal).where(Renewal.tenant_id == ctx.tenant_id, Renewal.deleted_at.is_(None))).all()
    out = []
    for row in rows:
        account = db.scalar(select(Account).where(Account.id == row.account_id, Account.tenant_id == ctx.tenant_id))
        payload = RenewalOut.model_validate(row)
        payload.account_name = account.name if account else ""
        out.append(payload)
    return Envelope(data=out, meta=Meta(total=len(out)))


@router.get("/expansion", response_model=Envelope[list[WhitespaceOut]])
def list_expansion(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.read"))],
) -> Envelope[list[WhitespaceOut]]:
    rows = db.scalars(select(WhitespaceCell).where(WhitespaceCell.tenant_id == ctx.tenant_id, WhitespaceCell.deleted_at.is_(None))).all()
    return Envelope(data=[_whitespace_out(db, ctx.tenant_id, row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/expansion/refresh", response_model=Envelope[list[WhitespaceOut]])
def refresh_expansion(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("success.write"))],
) -> Envelope[list[WhitespaceOut]]:
    accounts = db.scalars(select(Account).where(Account.tenant_id == ctx.tenant_id, Account.deleted_at.is_(None))).all()
    products = db.scalars(select(Product).where(Product.tenant_id == ctx.tenant_id, Product.deleted_at.is_(None))).all()
    created = []
    for account in accounts:
        created.extend(fill_whitespace(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, account=account, products=products))
    db.commit()
    rows = db.scalars(select(WhitespaceCell).where(WhitespaceCell.tenant_id == ctx.tenant_id, WhitespaceCell.deleted_at.is_(None))).all()
    return Envelope(data=[_whitespace_out(db, ctx.tenant_id, row) for row in rows], meta=Meta(total=len(created)))


@router.get("/advocacy", response_model=Envelope[dict])
def list_advocacy(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("advocacy.read"))],
) -> Envelope[dict]:
    assets = db.scalars(select(AdvocacyAsset).where(AdvocacyAsset.tenant_id == ctx.tenant_id, AdvocacyAsset.deleted_at.is_(None))).all()
    referrals = db.scalars(select(Referral).where(Referral.tenant_id == ctx.tenant_id, Referral.deleted_at.is_(None))).all()
    return Envelope(
        data={
            "assets": [AdvocacyOut.model_validate(row) for row in assets],
            "referrals": [ReferralOut.model_validate(row) for row in referrals],
        }
    )


@router.post("/advocacy", response_model=Envelope[AdvocacyOut])
def create_advocacy(
    body: AdvocacyIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("advocacy.write"))],
) -> Envelope[AdvocacyOut]:
    get_owned(db, Account, ctx.tenant_id, body.account_id)
    row = AdvocacyAsset(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=AdvocacyOut.model_validate(row))


@router.post("/advocacy/referrals", response_model=Envelope[ReferralOut])
def create_referral(
    body: ReferralIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("advocacy.write"))],
) -> Envelope[ReferralOut]:
    get_owned(db, Account, ctx.tenant_id, body.referrer_account_id)
    row = Referral(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=ReferralOut.model_validate(row))


@router.get("/models", response_model=Envelope[list[ModelCardOut]])
def list_models(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("revops.read"))],
) -> Envelope[list[ModelCardOut]]:
    rows = db.scalars(select(ModelCard).where(ModelCard.tenant_id == ctx.tenant_id, ModelCard.deleted_at.is_(None))).all()
    return Envelope(data=[ModelCardOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.get("/playbooks", response_model=Envelope[list[PlaybookOut]])
def list_playbooks(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("revops.read"))],
) -> Envelope[list[PlaybookOut]]:
    rows = db.scalars(select(Playbook).where(Playbook.tenant_id == ctx.tenant_id, Playbook.deleted_at.is_(None))).all()
    return Envelope(data=[PlaybookOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/playbooks", response_model=Envelope[PlaybookOut])
def create_playbook(
    body: PlaybookIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("revops.write"))],
) -> Envelope[PlaybookOut]:
    row = Playbook(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=PlaybookOut.model_validate(row))


@router.post("/playbooks/{playbook_id}/run", response_model=Envelope[WorkflowRunOut])
def execute_playbook(
    playbook_id: UUID,
    body: PlaybookRunIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("revops.write"))],
) -> Envelope[WorkflowRunOut]:
    playbook = get_owned(db, Playbook, ctx.tenant_id, playbook_id)
    row = run_playbook(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, playbook=playbook, entity_type=body.entity_type, entity_id=body.entity_id)
    write_audit(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="playbook.run", entity_type="workflow_run", entity_id="pending", after=body.model_dump(), correlation_id=ctx.correlation_id)
    db.commit()
    db.refresh(row)
    return Envelope(data=WorkflowRunOut.model_validate(row))


@router.get("/playbooks/runs", response_model=Envelope[list[WorkflowRunOut]])
def list_playbook_runs(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("revops.read"))],
) -> Envelope[list[WorkflowRunOut]]:
    rows = db.scalars(select(WorkflowRun).where(WorkflowRun.tenant_id == ctx.tenant_id, WorkflowRun.deleted_at.is_(None)).order_by(WorkflowRun.created_at.desc())).all()
    return Envelope(data=[WorkflowRunOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.get("/accounts/{account_id}", response_model=Envelope[AccountLifecycleOut])
def account_lifecycle(
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("accounts.read"))],
) -> Envelope[AccountLifecycleOut]:
    account = get_owned(db, Account, ctx.tenant_id, account_id)
    meetings = db.scalars(select(MeetingRecord).where(MeetingRecord.tenant_id == ctx.tenant_id, MeetingRecord.account_id == account.id, MeetingRecord.deleted_at.is_(None))).all()
    opps = db.scalars(select(Opportunity).where(Opportunity.tenant_id == ctx.tenant_id, Opportunity.account_id == account.id, Opportunity.deleted_at.is_(None))).all()
    opp_ids = [row.id for row in opps]
    quotes = db.scalars(select(Quote).where(Quote.tenant_id == ctx.tenant_id, Quote.opportunity_id.in_(opp_ids), Quote.deleted_at.is_(None))).all() if opp_ids else []
    insights = db.scalars(select(DealInsight).where(DealInsight.tenant_id == ctx.tenant_id, DealInsight.opportunity_id.in_(opp_ids), DealInsight.deleted_at.is_(None))).all() if opp_ids else []
    whitespace = db.scalars(select(WhitespaceCell).where(WhitespaceCell.tenant_id == ctx.tenant_id, WhitespaceCell.account_id == account.id, WhitespaceCell.deleted_at.is_(None))).all()
    advocacy = db.scalars(select(AdvocacyAsset).where(AdvocacyAsset.tenant_id == ctx.tenant_id, AdvocacyAsset.account_id == account.id, AdvocacyAsset.deleted_at.is_(None))).all()
    customer = db.scalar(select(Customer).where(Customer.tenant_id == ctx.tenant_id, Customer.account_id == account.id, Customer.deleted_at.is_(None)))
    health = None
    renewal = None
    customer_out = None
    if customer:
        customer_out = CustomerOut.model_validate(customer)
        customer_out.account_name = account.name
        health_row = db.scalar(select(HealthScore).where(HealthScore.tenant_id == ctx.tenant_id, HealthScore.customer_id == customer.id, HealthScore.deleted_at.is_(None)))
        health = _health_out(health_row)
        renewal_row = db.scalar(select(Renewal).where(Renewal.tenant_id == ctx.tenant_id, Renewal.customer_id == customer.id, Renewal.deleted_at.is_(None)))
        if renewal_row:
            renewal = RenewalOut.model_validate(renewal_row)
            renewal.account_name = account.name
    return Envelope(
        data=AccountLifecycleOut(
            meetings=[MeetingOut.model_validate(row) for row in meetings],
            quotes=[_quote_out(db, row) for row in quotes],
            insights=[_insight_out(db, ctx.tenant_id, row) for row in insights],
            whitespace=[_whitespace_out(db, ctx.tenant_id, row) for row in whitespace],
            advocacy=[AdvocacyOut.model_validate(row) for row in advocacy],
            customer=customer_out,
            health=health,
            renewal=renewal,
        )
    )
