"""Store LinkedIn share statistics without turning a missing field into zero.

Collection is idempotent for one reporting period. A failed reread does not
replace a stored number with zero and does not add the two readings together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.assessment import AssessmentDecision
from app.models.crm import Lead, Opportunity
from app.models.lifecycle import MeetingRecord
from app.models.operating_plan import CreativeVersion, OperatingPlan
from app.models.organic import ContentRecommendation, OrganicMetricObservation
from app.models.social import SocialPost
from app.providers.organic_metrics import METRIC_FIELDS, SOURCE, UNSUPPORTED_CHANNELS, read_linkedin_share_statistics
from app.providers.social import linkedin_author_urn
from app.services.demo_guard import organic_metrics_block

_GOOD = {"recorded", "zero"}
SAMPLE_MINIMUM = 100


def collect_linkedin_metrics(
    db: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    client=None,
    token: str = "",
    organization_urn: str = "",
    provenance: str = "live",
) -> dict:
    """Read metrics for published LinkedIn posts. A missing client on DEMO does not call out."""
    if client is None:
        blocked = organic_metrics_block(db, tenant_id)
        if blocked:
            return {"stored": 0, "http_calls": 0, "blocked": blocked, "detail": blocked}
    versions = db.scalars(
        select(CreativeVersion).where(
            CreativeVersion.tenant_id == tenant_id,
            CreativeVersion.deleted_at.is_(None),
            CreativeVersion.status == "published",
        )
    ).all()
    stored = 0
    http_calls = 0
    for version in versions:
        if version.channel != "linkedin":
            stored += _unsupported(db, tenant_id, actor_id, version)
            continue
        post = db.get(SocialPost, version.social_post_id) if version.social_post_id else None
        provider_id = "" if version.outcome == "mock" or (post is not None and post.is_mock) else (version.provider_ref or "")
        if not provider_id:
            stored += _remember(
                db,
                tenant_id=tenant_id,
                actor_id=actor_id,
                version=version,
                provider="linkedin",
                provider_post_id="",
                metrics=[
                    {
                        "metric_name": name,
                        "definition": definition,
                        "status": "unavailable",
                        "value": None,
                        "error": "No provider post id is stored. Metrics were not invented for a mock or unconfirmed post.",
                    }
                    for name, (_field, definition) in METRIC_FIELDS.items()
                ],
                period_start="",
                period_end="",
                provenance="mock" if version.outcome == "mock" or (post is not None and post.is_mock) else "unavailable",
                source=SOURCE,
            )
            continue
        if client is None:
            return {"stored": stored, "http_calls": 0, "blocked": "No metrics client was provided.", "detail": "The live metrics client was not created."}
        http_calls += 1
        reading = read_linkedin_share_statistics(
            client,
            token=token,
            organization_urn=organization_urn,
            share_urn=provider_id,
        )
        metrics = reading.get("metrics") or []
        if not reading.get("ok"):
            metrics = [
                {
                    "metric_name": name,
                    "definition": definition,
                    "status": "failed",
                    "value": None,
                    "error": str(reading.get("error") or "The metrics read failed."),
                }
                for name, (_field, definition) in METRIC_FIELDS.items()
            ]
        stored += _remember(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            version=version,
            provider="linkedin",
            provider_post_id=provider_id,
            metrics=metrics,
            period_start=str(reading.get("period_start") or ""),
            period_end=str(reading.get("period_end") or ""),
            provenance=provenance,
            source=SOURCE,
        )
    return {"stored": stored, "http_calls": http_calls, "blocked": "", "detail": "Metric observations were stored without adding cumulative totals."}


def collect_due_organic_metrics(db: Session, tenant_id: UUID | None = None) -> int:
    """Worker entry. A prepared or missing DEMO scope never opens the LinkedIn client.

    Postgres calls pass one tenant after that tenant's row-level context is set.
    """
    published = select(CreativeVersion.tenant_id).where(
        CreativeVersion.status == "published",
        CreativeVersion.deleted_at.is_(None),
    )
    if tenant_id is not None:
        published = published.where(CreativeVersion.tenant_id == tenant_id)
    tenant_ids = set(db.scalars(published).all())
    total = 0
    for tenant_id in tenant_ids:
        if organic_metrics_block(db, tenant_id):
            result = collect_linkedin_metrics(db, tenant_id=tenant_id, actor_id=None, client=None)
            total += int(result.get("stored") or 0)
            continue
        client, token, organization = live_linkedin_client()
        if client is None:
            continue
        try:
            result = collect_linkedin_metrics(
                db,
                tenant_id=tenant_id,
                actor_id=None,
                client=client,
                token=token,
                organization_urn=organization,
                provenance="live",
            )
            total += int(result.get("stored") or 0)
        finally:
            client.close()
    return total


def live_linkedin_client():
    """The real client. The worker calls this only after the DEMO gate allows it."""
    settings = get_settings()
    token = (settings.linkedin_post_access_token or "").strip()
    organization = linkedin_author_urn(settings.linkedin_organization_id or "")
    if not token or not (settings.linkedin_organization_id or "").strip():
        return None, "", ""
    return httpx.Client(timeout=30.0), token, organization


def prepare_recommendation(db: Session, *, tenant_id: UUID, actor_id: UUID | None, plan: OperatingPlan) -> dict:
    rows = _plan_observations(db, tenant_id, plan.id)
    impressions = [row for row in rows if row.metric_name == "impressions" and row.status in _GOOD and row.value_number is not None]
    if not impressions:
        text = "No provider impression observation is stored."
        return _save_recommendation(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            plan=plan,
            observation=text,
            sample_size=0,
            limitation="Missing metrics are not treated as zero, and mock posts do not supply a sample.",
            proposed_change="Wait for a provider reading before changing the content.",
            verdict="insufficient_evidence",
        )
    latest = max(impressions, key=lambda row: row.retrieved_at)
    sample = int(latest.value_number or 0)
    if sample < SAMPLE_MINIMUM:
        return _save_recommendation(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            plan=plan,
            observation=f"The latest LinkedIn impression reading is {sample}.",
            sample_size=sample,
            limitation=f"A recommendation needs at least {SAMPLE_MINIMUM} impressions from one reading. Readings were not added together.",
            proposed_change="Keep the approved post. Do not change the cadence or the copy from this sample.",
            verdict="insufficient_evidence",
        )
    return _save_recommendation(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        plan=plan,
        observation=f"The latest LinkedIn impression reading is {sample}.",
        sample_size=sample,
        limitation="This is one provider reading for one post. It does not identify which anonymous viewers became leads.",
        proposed_change="Review the post against the stored product facts before writing another version. Nothing was changed.",
        verdict="proposal_only",
    )


def latest_recommendation(db: Session, tenant_id: UUID, plan_id: UUID) -> dict:
    row = db.scalar(
        select(ContentRecommendation)
        .where(
            ContentRecommendation.tenant_id == tenant_id,
            ContentRecommendation.plan_id == plan_id,
            ContentRecommendation.deleted_at.is_(None),
        )
        .order_by(ContentRecommendation.created_at.desc())
    )
    if row is None:
        return {
            "verdict": "insufficient_evidence",
            "observation": "No recommendation has been prepared.",
            "sample_size": 0,
            "limitation": "There is no stored provider sample.",
            "proposed_change": "Prepare a recommendation only after a provider reading is stored.",
        }
    return {
        "verdict": row.verdict,
        "observation": row.observation,
        "sample_size": row.sample_size,
        "limitation": row.limitation,
        "proposed_change": row.proposed_change,
    }


def metric_summary(db: Session, tenant_id: UUID, plan_id: UUID) -> dict:
    rows = _plan_observations(db, tenant_id, plan_id)
    impressions = None
    clicks = None
    freshness = ""
    errors: list[str] = []
    provenance = ""
    for row in rows:
        if row.error and row.status in {"failed", "unavailable", "unsupported"}:
            errors.append(row.error)
        if row.metric_name == "impressions" and row.status in _GOOD and row.value_number is not None:
            impressions = row.value_number
            freshness = row.retrieved_at.isoformat()
            provenance = row.provenance
        if row.metric_name == "clicks" and row.status in _GOOD and row.value_number is not None:
            clicks = row.value_number
    return {
        "impressions": impressions,
        "clicks": clicks,
        "freshness": freshness,
        "errors": list(dict.fromkeys(errors))[:4],
        "provenance": provenance,
        "mock_separated": provenance in {"mock", "fixture"},
    }


def sales_evidence(db: Session, tenant_id: UUID, plan: OperatingPlan, leads: list[Lead]) -> dict:
    lead_ids = [lead.id for lead in leads]
    qualified = 0
    if lead_ids:
        decisions = db.scalars(
            select(AssessmentDecision).where(
                AssessmentDecision.tenant_id == tenant_id,
                AssessmentDecision.lead_id.in_(lead_ids),
                AssessmentDecision.deleted_at.is_(None),
                AssessmentDecision.sales_qualified.is_(True),
            )
        ).all()
        qualified = len({row.lead_id for row in decisions})
    meetings = 0
    if lead_ids:
        meetings = len(
            db.scalars(
                select(MeetingRecord).where(
                    MeetingRecord.tenant_id == tenant_id,
                    MeetingRecord.lead_id.in_(lead_ids),
                    MeetingRecord.deleted_at.is_(None),
                )
            ).all()
        )
    account_ids = [lead.account_id for lead in leads if lead.account_id is not None]
    filters = [Opportunity.tenant_id == tenant_id, Opportunity.deleted_at.is_(None), Opportunity.stage == "closed_won"]
    won_rows = []
    if plan.campaign_id is not None or account_ids:
        clauses = []
        if plan.campaign_id is not None:
            clauses.append(Opportunity.campaign_id == plan.campaign_id)
        if account_ids:
            clauses.append(Opportunity.account_id.in_(account_ids))
        won_rows = list(
            db.scalars(select(Opportunity).where(*filters, or_(*clauses))).all()
        )
    amount = None
    if won_rows:
        amount = str(sum((row.amount or Decimal("0")) for row in won_rows))
    return {
        "attributed_enquiries": len(leads),
        "qualified_leads": qualified,
        "meetings": meetings,
        "won_deals": len(won_rows),
        "won_amount": amount,
        "detail": "Enquiries, meetings, and won deals come from stored records. Clicks were not turned into leads.",
    }


def _plan_observations(db: Session, tenant_id: UUID, plan_id: UUID) -> list[OrganicMetricObservation]:
    version_ids = db.scalars(
        select(CreativeVersion.id).where(
            CreativeVersion.tenant_id == tenant_id,
            CreativeVersion.plan_id == plan_id,
            CreativeVersion.deleted_at.is_(None),
        )
    ).all()
    if not version_ids:
        return []
    return list(
        db.scalars(
            select(OrganicMetricObservation).where(
                OrganicMetricObservation.tenant_id == tenant_id,
                OrganicMetricObservation.creative_version_id.in_(version_ids),
                OrganicMetricObservation.deleted_at.is_(None),
            )
        ).all()
    )


def _unsupported(db, tenant_id, actor_id, version: CreativeVersion) -> int:
    reason = UNSUPPORTED_CHANNELS.get(version.channel, f"{version.channel} metrics are not read by this adapter.")
    return _remember(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        version=version,
        provider=version.channel,
        provider_post_id=version.provider_ref or "",
        metrics=[{"metric_name": "impressions", "definition": reason, "status": "unsupported", "value": None, "error": reason}],
        period_start="",
        period_end="",
        provenance="unsupported",
        source=version.channel,
    )


def _remember(db, *, tenant_id, actor_id, version, provider, provider_post_id, metrics, period_start, period_end, provenance, source) -> int:
    count = 0
    now = datetime.now(UTC)
    for item in metrics:
        existing = db.scalar(
            select(OrganicMetricObservation).where(
                OrganicMetricObservation.tenant_id == tenant_id,
                OrganicMetricObservation.creative_version_id == version.id,
                OrganicMetricObservation.metric_name == item["metric_name"],
                OrganicMetricObservation.period_start == period_start,
                OrganicMetricObservation.period_end == period_end,
                OrganicMetricObservation.deleted_at.is_(None),
            )
        )
        status = str(item["status"])
        value = item.get("value")
        if existing is not None and existing.status in _GOOD and status not in _GOOD:
            existing.error = str(item.get("error") or existing.error)
            existing.retrieved_at = now
            count += 1
            continue
        if existing is None:
            existing = OrganicMetricObservation(
                tenant_id=tenant_id,
                created_by=actor_id,
                creative_version_id=version.id,
                social_post_id=version.social_post_id,
                provider=provider,
                provider_post_id=provider_post_id,
                metric_name=str(item["metric_name"]),
                definition=str(item.get("definition") or ""),
                value_number=value if isinstance(value, int) else None,
                status=status,
                retrieved_at=now,
                period_start=period_start,
                period_end=period_end,
                source=source,
                provenance=provenance,
                error=str(item.get("error") or ""),
            )
            db.add(existing)
        else:
            existing.value_number = value if isinstance(value, int) else None
            existing.status = status
            existing.definition = str(item.get("definition") or existing.definition)
            existing.retrieved_at = now
            existing.provenance = provenance
            existing.error = str(item.get("error") or "")
            existing.provider_post_id = provider_post_id
        count += 1
    db.flush()
    return count


def _save_recommendation(db, *, tenant_id, actor_id, plan, observation, sample_size, limitation, proposed_change, verdict) -> dict:
    row = ContentRecommendation(
        tenant_id=tenant_id,
        created_by=actor_id,
        plan_id=plan.id,
        observation=observation,
        sample_size=sample_size,
        limitation=limitation,
        proposed_change=proposed_change,
        verdict=verdict,
    )
    db.add(row)
    db.flush()
    return {
        "verdict": verdict,
        "observation": observation,
        "sample_size": sample_size,
        "limitation": limitation,
        "proposed_change": proposed_change,
    }
