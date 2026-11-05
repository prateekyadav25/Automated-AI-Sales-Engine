"""Extra fictional records so a demo walkthrough is not a row of empty pages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import AIApproval, AIRecommendation
from app.models.autonomy import AutonomousRun, EntityAutomationState
from app.models.content import ContentDraft, SellerProfile
from app.models.crm import Account, Activity, Contact, Customer, Lead, LeadScore, Opportunity, Task
from app.models.identity import DomainEvent
from app.models.lifecycle import Conversation, MeetingRecord, Product
from app.models.post_sale import ExpansionRecommendation
from app.models.social import SocialPost
from app.services.lifecycle import score_deal

SHOWROOM_DRAFTS = (
    (
        "linkedin",
        "post",
        "Governed AI does not start with a bigger model",
        "Meridian's CIO asked who owns model risk before she asked about features. That is the conversation worth posting.",
        "Book a working session",
    ),
    (
        "facebook",
        "post",
        "One line, two weeks, a real plant",
        "ForgeLine does not want a platform tour. They want predictive quality on one production line.",
        "See how the pilot is scoped",
    ),
    (
        "instagram",
        "post",
        "The pipeline is a set of decisions, not a chart",
        "Proposal, discovery, negotiation, and one customer already live. Each one has a next step or it shows up as a stall.",
        "Open the workspace",
    ),
)
SHOWROOM_POST = (
    "Banks are staffing model risk before they buy another copilot. Worth a conversation with the CIO, not a feature list."
)


def seed_showroom(db: Session, *, tenant_id, actor_id, owner_id) -> None:
    accounts = {
        row.name: row
        for row in db.scalars(select(Account).where(Account.tenant_id == tenant_id, Account.deleted_at.is_(None))).all()
    }
    meridian = accounts.get("Meridian Bank")
    forge = accounts.get("ForgeLine Manufacturing")
    harbor = accounts.get("Harbor Retail Group")
    nimbus = accounts.get("Nimbus Health Systems")
    vertex = accounts.get("Vertex Cloud Technologies")
    if meridian is None:
        return

    _activities(db, tenant_id, actor_id, meridian, forge, harbor, vertex)
    _tasks(db, tenant_id, actor_id, owner_id, meridian, harbor, vertex)
    _deal(db, tenant_id, actor_id, owner_id, nimbus)
    _conversation(db, tenant_id, actor_id, forge)
    _content(db, tenant_id, actor_id)
    _today_board(db, tenant_id=tenant_id, actor_id=actor_id, owner_id=owner_id, accounts=accounts)


def _activities(db, tenant_id, actor_id, meridian, forge, harbor, vertex) -> None:
    now = datetime.now(UTC)
    rows = [
        (
            "Logged a call with Lina Kapoor",
            "call",
            "account",
            str(meridian.id),
            "Lina wants the model-risk workshop on Thursday. She asked for the proposal outline, not a revised price.",
            now - timedelta(days=1, hours=3),
        ),
        (
            "ForgeLine asked for a two-week pilot scope",
            "meeting",
            "account",
            str(forge.id) if forge else str(meridian.id),
            "Omar Haddad will bring the plant manager. Scope stays predictive quality on one line.",
            now - timedelta(days=2, hours=5),
        ),
        (
            "Harbor next step is still open",
            "note",
            "account",
            str(harbor.id) if harbor else str(meridian.id),
            "The qualification call slipped. A task is open to put a date back on the opportunity.",
            now - timedelta(hours=6),
        ),
        (
            "Vertex pilot agenda drafted",
            "email",
            "account",
            str(vertex.id) if vertex else str(meridian.id),
            "Draft is saved in the workspace. It has not been sent.",
            now - timedelta(days=3),
        ),
    ]
    for title, kind, entity_type, entity_id, body, when in rows:
        exists = db.scalar(select(Activity).where(Activity.tenant_id == tenant_id, Activity.title == title))
        if exists is not None:
            continue
        db.add(
            Activity(
                tenant_id=tenant_id,
                created_by=actor_id,
                entity_type=entity_type,
                entity_id=entity_id,
                activity_type=kind,
                title=title,
                body=body,
                actor_type="human",
                created_at=when,
            )
        )


def _tasks(db, tenant_id, actor_id, owner_id, meridian, harbor, vertex) -> None:
    now = datetime.now(UTC)
    specs = [
        (
            "Confirm Thursday's model-risk workshop",
            "Send Lina the agenda after she replies. Do not change the proposal amount.",
            "high",
            now + timedelta(days=1),
            "account",
            str(meridian.id),
        ),
        (
            "Put a close date back on Harbor",
            "The personalization deal has an empty next step and a slipped date.",
            "high",
            now - timedelta(days=1),
            "account",
            str(harbor.id) if harbor else str(meridian.id),
        ),
        (
            "Prepare the Vertex demo environment",
            "Use the copilot pilot scope. No live dial.",
            "medium",
            now + timedelta(days=3),
            "account",
            str(vertex.id) if vertex else str(meridian.id),
        ),
    ]
    for title, description, priority, due_at, entity_type, entity_id in specs:
        exists = db.scalar(select(Task).where(Task.tenant_id == tenant_id, Task.title == title))
        if exists is not None:
            continue
        db.add(
            Task(
                tenant_id=tenant_id,
                created_by=actor_id,
                owner_id=owner_id,
                title=title,
                description=description,
                status="open",
                priority=priority,
                due_at=due_at,
                entity_type=entity_type,
                entity_id=entity_id,
                source="human",
            )
        )


def _deal(db, tenant_id, actor_id, owner_id, nimbus) -> None:
    if nimbus is None:
        return
    name = "Nimbus Clinical Copilot"
    exists = db.scalar(select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.name == name))
    if exists is not None:
        return
    db.add(
        Opportunity(
            tenant_id=tenant_id,
            created_by=actor_id,
            owner_id=owner_id,
            account_id=nimbus.id,
            name=name,
            stage="negotiation",
            amount=Decimal("310000"),
            probability=70,
            expected_close=(datetime.now(UTC) + timedelta(days=21)).date(),
            next_step="Security review with Meera Das",
        )
    )
    db.flush()
    created = db.scalar(select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.name == name))
    if created is not None:
        score_deal(db, tenant_id, created)


def _conversation(db, tenant_id, actor_id, forge) -> None:
    subject = "ForgeLine pilot scope"
    exists = db.scalar(select(Conversation).where(Conversation.tenant_id == tenant_id, Conversation.subject == subject))
    if exists is not None or forge is None:
        return
    contact = db.scalar(select(Contact).where(Contact.tenant_id == tenant_id, Contact.email.ilike("%omar.haddad%")))
    db.add(
        Conversation(
            tenant_id=tenant_id,
            created_by=actor_id,
            channel="email",
            account_id=forge.id,
            contact_id=contact.id if contact else None,
            subject=subject,
            status="open",
            outcome="awaiting_reply",
            sentiment="neutral",
            consent=True,
            provider="human",
            is_mock=False,
            transcript="Omar asked which production line the pilot would cover. Reply is still a draft.",
            summary="Waiting on the plant manager before a date is promised.",
        )
    )


def _content(db, tenant_id, actor_id) -> None:
    profile = db.scalar(select(SellerProfile).where(SellerProfile.tenant_id == tenant_id, SellerProfile.deleted_at.is_(None)))
    if profile is None:
        db.add(
            SellerProfile(
                tenant_id=tenant_id,
                created_by=actor_id,
                company_name="AGRAYIAN AI Labs",
                summary="We help enterprise teams adopt AI with governance, from the first account through renewal.",
                audience="CIOs, CTOs, and heads of data at banks, hospitals, and manufacturers.",
                website="https://agrayianailabs.com",
                proof="Delivery is governed. We do not claim regulatory approval.",
                capture_url="https://revanzas.demo.agrayianailabs.com",
            )
        )
    product = db.scalar(select(Product).where(Product.tenant_id == tenant_id, Product.sku == "CORE"))
    for channel, kind, headline, body, cta in SHOWROOM_DRAFTS:
        exists = db.scalar(
            select(ContentDraft).where(ContentDraft.tenant_id == tenant_id, ContentDraft.headline == headline)
        )
        if exists is not None:
            continue
        db.add(
            ContentDraft(
                tenant_id=tenant_id,
                created_by=actor_id,
                product_id=product.id if product else None,
                channel=channel,
                kind=kind,
                headline=headline,
                body=body,
                cta=cta,
                destination_url="https://revanzas.demo.agrayianailabs.com",
                status="draft",
                is_mock=False,
            )
        )
    posted = db.scalar(select(SocialPost).where(SocialPost.tenant_id == tenant_id, SocialPost.body == SHOWROOM_POST))
    if posted is None:
        db.add(
            SocialPost(
                tenant_id=tenant_id,
                created_by=actor_id,
                channel="linkedin",
                body=SHOWROOM_POST,
                link_url="https://revanzas.demo.agrayianailabs.com",
                status="draft",
                is_mock=False,
            )
        )


def _stamp(row, when: datetime) -> None:
    row.created_at = when


def _today_board(db: Session, *, tenant_id, actor_id, owner_id, accounts: dict[str, Account]) -> None:
    """Fill the Autopilot counters. Dates move forward each time the demo seed runs."""
    now = datetime.now(UTC)
    meridian = accounts["Meridian Bank"]
    people = [
        ("Neha", "Seth", "Head of Model Risk", meridian, "DISCOVERED", 82),
        ("Rahul", "Menon", "Data Platform Lead", meridian, "ENRICHED", 76),
        ("Sara", "Iqbal", "Plant IT Manager", accounts.get("ForgeLine Manufacturing") or meridian, "SCORED", 71),
        ("Daniel", "Cho", "Procurement Lead", accounts.get("Harbor Retail Group") or meridian, "QUALIFIED", 88),
        ("Priya", "Raman", "Clinical Operations", accounts.get("Nimbus Health Systems") or meridian, "", 64),
        ("Tom", "Adler", "Platform Director", accounts.get("Vertex Cloud Technologies") or meridian, "", 58),
    ]
    leads: list[Lead] = []
    for index, (first, last, title, account, state, score) in enumerate(people, start=1):
        email = f"demo.board.{index}@{account.domain}"
        lead = db.scalar(select(Lead).where(Lead.tenant_id == tenant_id, Lead.email == email))
        if lead is None:
            lead = Lead(
                tenant_id=tenant_id,
                created_by=actor_id,
                account_id=account.id,
                first_name=first,
                last_name=last,
                email=email,
                company_name=account.name,
                title=title,
                source="ai_discovery",
                channel="discovery",
                status="qualified" if state == "QUALIFIED" else "new",
                consent_email=True,
                intent_score=score,
                engagement_score=max(score - 15, 0),
                has_buying_trigger=score >= 70,
            )
            db.add(lead)
            db.flush()
        lead.source = "ai_discovery"
        _stamp(lead, now - timedelta(hours=index))
        leads.append(lead)
        if state:
            _automation_state(db, tenant_id, actor_id, "lead", str(lead.id), state)
        scored = db.scalar(
            select(LeadScore).where(
                LeadScore.tenant_id == tenant_id, LeadScore.lead_id == lead.id, LeadScore.version == "demo-board"
            )
        )
        if scored is None:
            scored = LeadScore(
                tenant_id=tenant_id,
                created_by=actor_id,
                lead_id=lead.id,
                total=score,
                icp_fit=20,
                intent=min(score, 25),
                engagement=15,
                persona=10,
                company_potential=10,
                buying_trigger=8 if score >= 70 else 0,
                timing=5,
                reasons="Discovery match for the enterprise AI transformation ICP.",
                version="demo-board",
                confidence=80,
            )
            db.add(scored)
        scored.total = score
        _stamp(scored, now - timedelta(hours=index))

    for index, event_type in enumerate(["lead.enriched"] * 4 + ["lead.qualified"] * 3, start=1):
        lead = leads[index - 1] if index <= 4 else leads[index - 5]
        _event(db, tenant_id, event_type, "lead", str(lead.id), now - timedelta(minutes=20 + index))
    _event(db, tenant_id, "renewal.prepared", "account", str(meridian.id), now - timedelta(minutes=40))
    _event(db, tenant_id, "expansion.detected", "account", str(meridian.id), now - timedelta(minutes=50))

    for index, title in enumerate(
        ["Meridian model-risk research", "ForgeLine line-level pilot research", "Nimbus security review research"],
        start=1,
    ):
        row = db.scalar(select(AIRecommendation).where(AIRecommendation.tenant_id == tenant_id, AIRecommendation.title == title))
        if row is None:
            row = AIRecommendation(
                tenant_id=tenant_id,
                created_by=actor_id,
                entity_type="account",
                entity_id=str(meridian.id),
                kind="research",
                title=title,
                body="Prepared from the account record. No external claim was added.",
                status="ready",
            )
            db.add(row)
        _stamp(row, now - timedelta(hours=index))

    for index, title in enumerate(["Meridian intro draft", "ForgeLine pilot follow-up"], start=1):
        key = f"demo-board-send-{index}"
        row = db.scalar(select(AIApproval).where(AIApproval.tenant_id == tenant_id, AIApproval.idempotency_key == key))
        if row is None:
            row = AIApproval(
                tenant_id=tenant_id,
                created_by=actor_id,
                action_level=1,
                action_type="email.send",
                title=title,
                payload_json="{}",
                status="rejected",
                decided_by=actor_id,
                decision_note="Kept as a prepared draft. Nothing was sent.",
                entity_type="account",
                entity_id=str(meridian.id),
                idempotency_key=key,
            )
            db.add(row)
        row.status = "rejected"
        _stamp(row, now - timedelta(hours=index))

    for index, title, account_name in (
        (1, "Meridian economic-buyer review", "Meridian Bank"),
        (2, "ForgeLine plant walkthrough", "ForgeLine Manufacturing"),
    ):
        account = accounts.get(account_name) or meridian
        event_id = f"demo-board-meeting-{index}"
        row = db.scalar(
            select(MeetingRecord).where(
                MeetingRecord.tenant_id == tenant_id,
                MeetingRecord.provider == "human",
                MeetingRecord.provider_event_id == event_id,
            )
        )
        if row is None:
            row = MeetingRecord(
                tenant_id=tenant_id,
                created_by=actor_id,
                account_id=account.id,
                title=title,
                occurred_at=now + timedelta(days=index + 1),
                summary="Booked on the calendar. No call was placed.",
                next_steps="Confirm the attendee list.",
                provider="human",
                status="booked",
                provider_event_id=event_id,
                owner_id=owner_id,
                start_at=now + timedelta(days=index + 1),
            )
            db.add(row)
        row.status = "booked"
        _stamp(row, now - timedelta(hours=index))

    for name, account_name, amount in (
        ("Northwind Copilot Review", "Northwind Enterprise Holdings", Decimal("275000")),
        ("Helios Success Desk", "Helios Public Works", Decimal("36000")),
    ):
        account = accounts.get(account_name)
        if account is None:
            continue
        row = db.scalar(select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.name == name))
        if row is None:
            row = Opportunity(
                tenant_id=tenant_id,
                created_by=actor_id,
                owner_id=owner_id,
                account_id=account.id,
                name=name,
                stage="discovery",
                amount=amount,
                probability=30,
                expected_close=(now + timedelta(days=30)).date(),
                next_step="Confirm the buying group",
            )
            db.add(row)
        _stamp(row, now - timedelta(hours=2))

    vertex = accounts.get("Vertex Cloud Technologies")
    if vertex is not None:
        customer = db.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id, Customer.account_id == vertex.id, Customer.deleted_at.is_(None)
            )
        )
        if customer is None:
            customer = Customer(
                tenant_id=tenant_id,
                created_by=actor_id,
                account_id=vertex.id,
                status="live",
                arr=Decimal("95000"),
                lifecycle_state="AT_RISK",
                owner_id=owner_id,
                health_trend="declining",
            )
            db.add(customer)
            db.flush()
        _automation_state(db, tenant_id, actor_id, "customer", str(customer.id), "AT_RISK")
        if customer.lifecycle_state not in {"AT_RISK", "RENEWAL_IN_PROGRESS"}:
            customer.lifecycle_state = "AT_RISK"
        product = db.scalar(select(Product).where(Product.tenant_id == tenant_id, Product.sku == "GOV"))
        expansion = db.scalar(
            select(ExpansionRecommendation).where(
                ExpansionRecommendation.tenant_id == tenant_id, ExpansionRecommendation.title == "Vertex governance pack"
            )
        )
        if expansion is None:
            db.add(
                ExpansionRecommendation(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    customer_id=customer.id,
                    account_id=vertex.id,
                    product_id=product.id if product else None,
                    kind="expansion",
                    title="Vertex governance pack",
                    reason="Usage of the pilot is concentrated in one team. Governance pack is the next conversation.",
                    confidence=72,
                    amount=Decimal("48000"),
                    status="open",
                    source_fingerprint="demo-board",
                )
            )

    helios = accounts.get("Helios Public Works")
    if helios is not None:
        helios_customer = db.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id, Customer.account_id == helios.id, Customer.deleted_at.is_(None)
            )
        )
        if helios_customer is not None:
            _automation_state(db, tenant_id, actor_id, "customer", str(helios_customer.id), "NEW_CUSTOMER")
            desk = db.scalar(select(Product).where(Product.tenant_id == tenant_id, Product.sku == "CS"))
            second = db.scalar(
                select(ExpansionRecommendation).where(
                    ExpansionRecommendation.tenant_id == tenant_id, ExpansionRecommendation.title == "Helios success desk"
                )
            )
            if second is None and desk is not None:
                db.add(
                    ExpansionRecommendation(
                        tenant_id=tenant_id,
                        created_by=actor_id,
                        customer_id=helios_customer.id,
                        account_id=helios.id,
                        product_id=desk.id,
                        kind="cross_sell",
                        title="Helios success desk",
                        reason="Onboarding is underway. Success desk keeps the kickoff from slipping.",
                        confidence=66,
                        amount=Decimal("36000"),
                        status="open",
                        source_fingerprint="demo-board",
                    )
                )
        _automation_state(db, tenant_id, actor_id, "account", str(helios.id), "RENEWED")

    _automation_state(db, tenant_id, actor_id, "account", str(meridian.id), "RESEARCHING")
    forge = accounts.get("ForgeLine Manufacturing")
    if forge is not None:
        _automation_state(db, tenant_id, actor_id, "account", str(forge.id), "MEETING_SCHEDULED")
    nimbus = accounts.get("Nimbus Health Systems")
    if nimbus is not None:
        _automation_state(db, tenant_id, actor_id, "account", str(nimbus.id), "EXPANSION")

    run = db.scalar(
        select(AutonomousRun).where(AutonomousRun.tenant_id == tenant_id, AutonomousRun.correlation_id == "demo-board")
    )
    if run is None:
        run = AutonomousRun(
            tenant_id=tenant_id,
            created_by=actor_id,
            status="succeeded",
            trigger="schedule",
            workflow="cycle",
            correlation_id="demo-board",
            summary="Scored new discovery, prepared two drafts, and booked two meetings.",
            finished_at=now,
        )
        db.add(run)
    run.status = "succeeded"
    run.finished_at = now
    _stamp(run, now - timedelta(minutes=12))


def _automation_state(db: Session, tenant_id, actor_id, entity_type: str, entity_id: str, state: str) -> None:
    row = db.scalar(
        select(EntityAutomationState).where(
            EntityAutomationState.tenant_id == tenant_id,
            EntityAutomationState.entity_type == entity_type,
            EntityAutomationState.entity_id == entity_id,
        )
    )
    if row is None:
        db.add(
            EntityAutomationState(
                tenant_id=tenant_id,
                created_by=actor_id,
                entity_type=entity_type,
                entity_id=entity_id,
                state=state,
                last_action="demo-board",
                paused_at=None,
            )
        )
        return
    if row.last_action == "demo-board":
        row.state = state
        row.paused_at = None


def _event(db: Session, tenant_id, event_type: str, entity_type: str, entity_id: str, when: datetime) -> None:
    from app.services.correlation import bound_correlation_id

    key = bound_correlation_id(f"demo-board:{event_type}:{entity_id}")
    row = db.scalar(select(DomainEvent).where(DomainEvent.tenant_id == tenant_id, DomainEvent.correlation_id == key))
    if row is None:
        row = DomainEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_json="{}",
            correlation_id=key,
            processed_at=when,
        )
        db.add(row)
    row.event_type = event_type
    _stamp(row, when)
