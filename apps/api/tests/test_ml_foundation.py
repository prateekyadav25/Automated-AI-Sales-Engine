import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session
from app.models.identity import User
from app.models.lifecycle import MeetingRecord
from app.models.ml import ModelVersion
from app.models.signals import MLFeatureSnapshot
from app.services.ml.dataset import DatasetBuildError, build_dataset, validate_snapshot
from app.services.ml.evaluate import evaluate_matured
from app.services.ml.features import compute_features
from app.services.ml.governance import GovernanceError, promote, rollback_champion
from app.services.ml.labels import resolve_label
from app.services.ml.prediction import PredictionResult, persist_prediction
from app.services.ml.snapshots import record_feature_snapshot
from app.services.ml.train import TrainingRefused, train_candidate
from tests.conftest import login


def _tenant(db):
    user = db.scalar(select(User).where(User.email == "admin@agrayian.demo"))
    assert user is not None
    return user


def test_readiness_is_data_collection(client: TestClient) -> None:
    headers = login(client)
    response = client.get("/api/v1/ml/readiness", headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert len(rows) == 9
    assert all(row["recommended_status"] == "DATA_COLLECTION" for row in rows)
    lead = next(row for row in rows if row["task_key"] == "LEAD_CONVERSION")
    assert lead["minimum_rows"] >= 200
    assert "NOT ENOUGH" in lead["reason"] or lead["reason"] == "DATA COLLECTION"


def test_registry_has_no_trained_model(client: TestClient) -> None:
    headers = login(client)
    models = client.get("/api/v1/ml/models", headers=headers).json()["data"]
    trained = [row for row in models if row["algorithm"] != "rules"]
    assert trained == []
    cards = client.get("/api/v1/lifecycle/models", headers=headers).json()["data"]
    assert all(row.get("last_trained") is None for row in cards)
    assert all(row.get("metrics_json") is None for row in cards)


def test_train_refused_without_readiness(client: TestClient) -> None:
    headers = login(client)
    response = client.post(
        "/api/v1/ml/train",
        headers=headers,
        json={"task_key": "LEAD_CONVERSION", "dataset_version": "ds-0001"},
    )
    assert response.status_code == 400


def test_sales_rep_cannot_train_or_download(client: TestClient) -> None:
    headers = login(client, "seller@agrayian.demo")
    denied = client.get("/api/v1/ml/readiness", headers=headers)
    assert denied.status_code == 403
    models = client.get("/api/v1/ml/models", headers=login(client)).json()["data"]
    champion = next(row for row in models if row["task_key"] == "LEAD_CONVERSION")
    artifact = client.get(f"/api/v1/ml/models/{champion['id']}/artifact", headers=headers)
    assert artifact.status_code == 403


def test_rules_champion_artifact_is_not_downloadable(client: TestClient) -> None:
    headers = login(client)
    models = client.get("/api/v1/ml/models", headers=headers).json()["data"]
    champion = next(row for row in models if row["task_key"] == "LEAD_CONVERSION")
    artifact = client.get(f"/api/v1/ml/models/{champion['id']}/artifact", headers=headers)
    assert artifact.status_code == 404


def test_point_in_time_excludes_future_meetings(client: TestClient) -> None:
    headers = login(client)
    leads = client.get("/api/v1/leads", headers=headers).json()["data"]
    lead_id = leads[0]["id"]
    db = get_session()
    try:
        user = _tenant(db)
        as_of = datetime(2024, 6, 1, tzinfo=UTC)
        db.add(
            MeetingRecord(
                tenant_id=user.tenant_id,
                created_by=user.id,
                title="After prediction",
                lead_id=UUID(lead_id),
                occurred_at=datetime(2024, 6, 15, tzinfo=UTC),
                start_at=datetime(2024, 6, 15, tzinfo=UTC),
            )
        )
        db.flush()
        computed = compute_features(
            db,
            tenant_id=user.tenant_id,
            task_key="LEAD_CONVERSION",
            entity_type="lead",
            entity_id=lead_id,
            as_of=as_of,
        )
        assert computed.features["meetings_last_30d"] == 0
        db.rollback()
    finally:
        db.close()


def test_future_feature_rejected_by_dataset_builder() -> None:
    db = get_session()
    try:
        user = _tenant(db)
        as_of = datetime(2024, 6, 1, tzinfo=UTC)
        snap = record_feature_snapshot(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            entity_type="lead",
            entity_id="00000000-0000-0000-0000-000000000099",
            task_key="LEAD_CONVERSION",
            features={"lead_icp_score": 10},
            source_versions={"lead_icp_score": {"source": "lead_scores", "max_observed_at": "2024-06-15T00:00:00+00:00"}},
            as_of=as_of,
        )
        try:
            validate_snapshot(snap, "LEAD_CONVERSION")
            raise AssertionError("expected leakage failure")
        except DatasetBuildError as exc:
            assert "after prediction time" in str(exc)
        db.rollback()
    finally:
        db.close()


def test_forbidden_leakage_features_rejected() -> None:
    db = get_session()
    try:
        user = _tenant(db)
        snap = record_feature_snapshot(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            entity_type="opportunity",
            entity_id="00000000-0000-0000-0000-000000000098",
            task_key="OPPORTUNITY_WIN",
            features={"days_in_stage": 3, "closed_won_at": "2024-06-20"},
            as_of=datetime(2024, 6, 1, tzinfo=UTC),
        )
        try:
            validate_snapshot(snap, "OPPORTUNITY_WIN")
            raise AssertionError("expected forbidden feature")
        except DatasetBuildError as exc:
            assert "closed_won_at" in str(exc)
        db.rollback()
    finally:
        db.close()


def test_censored_labels_are_not_negative() -> None:
    db = get_session()
    try:
        user = _tenant(db)
        leads = db.scalars(select(MLFeatureSnapshot).limit(1)).all()
        _ = leads
        from app.models.crm import Lead

        lead = db.scalar(select(Lead).where(Lead.tenant_id == user.tenant_id, Lead.deleted_at.is_(None)))
        assert lead is not None
        resolved = resolve_label(
            db,
            tenant_id=user.tenant_id,
            task_key="LEAD_CONVERSION",
            entity_type="lead",
            entity_id=str(lead.id),
            as_of=datetime.now(UTC),
        )
        assert resolved.status in {"PENDING", "CENSORED"}
        assert resolved.value is None
    finally:
        db.close()


def test_dataset_fingerprint_reproducible(client: TestClient) -> None:
    headers = login(client)
    leads = client.get("/api/v1/leads", headers=headers).json()["data"]
    db = get_session()
    try:
        user = _tenant(db)
        as_of = datetime(2024, 1, 1, tzinfo=UTC)
        record_feature_snapshot(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            entity_type="lead",
            entity_id=leads[0]["id"],
            task_key="LEAD_CONVERSION",
            features={"lead_icp_score": 8, "lead_intent_score": 5, "emails_last_30d": 0, "meetings_last_30d": 0},
            source_versions={"lead_icp_score": {"source": "lead_scores", "max_observed_at": "2024-01-01T00:00:00+00:00"}},
            as_of=as_of,
        )
        first = build_dataset(db, tenant_id=user.tenant_id, actor_id=user.id, task_key="LEAD_CONVERSION")
        second = build_dataset(db, tenant_id=user.tenant_id, actor_id=user.id, task_key="LEAD_CONVERSION")
        assert first.fingerprint == second.fingerprint
        assert first.fingerprint
        assert first.censored_count + first.negative_count + first.positive_count == first.row_count
        db.commit()
    finally:
        db.close()
    listed = client.get("/api/v1/ml/datasets", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] >= 1


def test_shadow_prediction_and_active_ml_rejected(client: TestClient) -> None:
    headers = login(client)
    leads = client.get("/api/v1/leads", headers=headers).json()["data"]
    db = get_session()
    try:
        user = _tenant(db)
        challenger = ModelVersion(
            tenant_id=user.tenant_id,
            created_by=user.id,
            task_key="LEAD_CONVERSION",
            version="shadow-constant",
            algorithm="constant",
            status="CHALLENGER",
            package_versions=json.dumps({"probability": 0.42}),
            metrics_json=None,
            is_rules=0,
        )
        db.add(challenger)
        db.commit()
    finally:
        db.close()
    scored = client.post(f"/api/v1/leads/{leads[0]['id']}/score", headers=headers)
    assert scored.status_code == 200
    preds = client.get(
        "/api/v1/ml/predictions",
        headers=headers,
        params={"task_key": "LEAD_CONVERSION", "entity_id": leads[0]["id"]},
    )
    assert preds.status_code == 200
    shadows = [row for row in preds.json()["data"] if row["execution_mode"] == "SHADOW"]
    assert shadows
    assert shadows[0]["model_version"] == "shadow-constant"
    db = get_session()
    try:
        user = _tenant(db)
        result = PredictionResult(
            prediction="positive",
            probability=0.9,
            confidence=90,
            model_version="bad",
            provider_key="constant",
            feature_snapshot_id=None,
            explanation={},
            execution_mode="ACTIVE",
        )
        try:
            persist_prediction(
                db,
                tenant_id=user.tenant_id,
                actor_id=user.id,
                task_key="LEAD_CONVERSION",
                entity_type="lead",
                entity_id=leads[0]["id"],
                result=result,
                snapshot=None,
                execution_mode="ACTIVE",
            )
            raise AssertionError("ACTIVE ML should fail")
        except ValueError as exc:
            assert "ACTIVE" in str(exc)
        db.rollback()
    finally:
        db.close()


def test_promote_rollback_and_delayed_evaluation(client: TestClient) -> None:
    headers = login(client)
    seller = login(client, "seller@agrayian.demo")
    db = get_session()
    try:
        user = _tenant(db)
        row = ModelVersion(
            tenant_id=user.tenant_id,
            created_by=user.id,
            task_key="OPPORTUNITY_WIN",
            version="exp-promote",
            algorithm="constant",
            status="EXPERIMENTAL",
            metrics_json=None,
            is_rules=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        denied = client.post(
            f"/api/v1/ml/models/{row.id}/promote",
            headers=seller,
            json={"target": "CANDIDATE", "reason": "no"},
        )
        assert denied.status_code == 403
        promoted = promote(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            model_id=row.id,
            target="CANDIDATE",
            reason="review",
        )
        assert promoted.status == "CANDIDATE"
        try:
            promote(
                db,
                tenant_id=user.tenant_id,
                actor_id=user.id,
                model_id=row.id,
                target="CHALLENGER",
                reason="shadow",
            )
            promote(
                db,
                tenant_id=user.tenant_id,
                actor_id=user.id,
                model_id=row.id,
                target="CHAMPION",
                reason="should fail",
            )
            raise AssertionError("ML champion should be refused")
        except GovernanceError:
            pass
        restored = rollback_champion(db, tenant_id=user.tenant_id, actor_id=user.id, task_key="LEAD_CONVERSION", reason="keep rules")
        assert restored.is_rules == 1
        as_of = datetime.now(UTC) - timedelta(days=200)
        pred = persist_prediction(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            task_key="LEAD_CONVERSION",
            entity_type="lead",
            entity_id=client.get("/api/v1/leads", headers=headers).json()["data"][0]["id"],
            result=PredictionResult("negative", 0.2, 50, "rules-champion", "rules", None, {}, "SHADOW"),
            snapshot=None,
            execution_mode="SHADOW",
            prediction_for=as_of,
        )
        linked = evaluate_matured(db, tenant_id=user.tenant_id, actor_id=user.id)
        assert linked >= 1
        from app.models.ml import ModelEvaluation

        ev = db.scalar(select(ModelEvaluation).where(ModelEvaluation.prediction_id == pred.id))
        assert ev is not None
        assert ev.correct is not None
        db.commit()
    finally:
        db.close()


def test_cross_tenant_dataset_rejected() -> None:
    db = get_session()
    try:
        user = _tenant(db)
        try:
            build_dataset(
                db,
                tenant_id=user.tenant_id,
                actor_id=user.id,
                task_key="LEAD_CONVERSION",
                scope="CROSS_TENANT_ANONYMIZED",
            )
            raise AssertionError("cross-tenant should fail")
        except DatasetBuildError as exc:
            assert "TENANT_LOCAL" in str(exc)
        try:
            train_candidate(
                db,
                tenant_id=user.tenant_id,
                actor_id=user.id,
                task_key="LEAD_CONVERSION",
                dataset_version="missing",
            )
            raise AssertionError("train should refuse")
        except TrainingRefused:
            pass
        db.rollback()
    finally:
        db.close()
