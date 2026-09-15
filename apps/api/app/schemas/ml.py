from datetime import datetime
from uuid import UUID

from app.schemas.common import APIModel


class ReadinessOut(APIModel):
    task_key: str
    name: str
    entity_type: str
    status: str
    recommended_status: str
    reason: str
    rows: int
    mature_labels: int
    positive: int
    negative: int
    pending: int
    censored: int
    history_days: int
    minimum_rows: int
    minimum_positive: int
    minimum_negative: int
    minimum_history_days: int
    feature_set_version: str
    label_version: str
    horizon_days: int
    baseline: str
    split_policy: str


class DatasetOut(APIModel):
    id: UUID
    task_key: str
    version: str
    feature_set_version: str
    label_version: str
    date_start: datetime | None = None
    date_end: datetime | None = None
    row_count: int
    positive_count: int
    negative_count: int
    censored_count: int
    scope: str
    fingerprint: str
    status: str


class DatasetBuildIn(APIModel):
    task_key: str
    feature_set_version: str = "v1"
    label_version: str = "v1"


class ModelVersionOut(APIModel):
    id: UUID
    task_key: str
    version: str
    algorithm: str
    feature_set_version: str
    label_version: str
    dataset_version: str
    status: str
    metrics_json: str | None = None
    training_completed_at: datetime | None = None
    is_rules: int
    artifact_location: str = ""


class PromoteIn(APIModel):
    target: str
    reason: str


class RollbackIn(APIModel):
    task_key: str
    reason: str


class PredictionOut(APIModel):
    id: UUID
    task_key: str
    entity_type: str
    entity_id: str
    model_version: str
    probability: float | None = None
    confidence: int
    execution_mode: str
    created_at: datetime
    feature_snapshot_id: UUID | None = None
    provider_key: str


class FeedbackIn(APIModel):
    action: str
    note: str = ""
    useful: str = ""


class TrainIn(APIModel):
    task_key: str
    dataset_version: str
    algorithm: str = "logistic_regression"
