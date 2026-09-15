from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantOwnedMixin


class PredictionTask(Base, TenantOwnedMixin):
    __tablename__ = "prediction_tasks"
    __table_args__ = (UniqueConstraint("tenant_id", "task_key", name="uq_prediction_task"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    label_definition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prediction_horizon_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    label_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)
    minimum_history_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    minimum_positive_labels: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    minimum_negative_labels: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    minimum_rows: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="DATA_COLLECTION", nullable=False)
    split_policy: Mapped[str] = mapped_column(Text, default="", nullable=False)


class FeatureSet(Base, TenantOwnedMixin):
    __tablename__ = "feature_sets"
    __table_args__ = (UniqueConstraint("tenant_id", "task_key", "feature_set_version", name="uq_feature_set"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(40), nullable=False)
    definitions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class LabelDefinition(Base, TenantOwnedMixin):
    __tablename__ = "label_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "task_key", "label_version", name="uq_label_definition"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    label_version: Mapped[str] = mapped_column(String(20), nullable=False)
    definition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    positive_condition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    negative_condition: Mapped[str] = mapped_column(Text, default="", nullable=False)
    censoring_rule: Mapped[str] = mapped_column(Text, default="", nullable=False)


class TrainingExample(Base, TenantOwnedMixin):
    __tablename__ = "training_examples"
    __table_args__ = (Index("ix_training_examples_task", "tenant_id", "task_key", "dataset_id"),)

    dataset_id: Mapped[UUID | None] = mapped_column(ForeignKey("dataset_versions.id"), index=True, nullable=True)
    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prediction_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feature_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("ml_feature_snapshots.id"), nullable=False)
    label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    label_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feature_set_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    label_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)
    split: Mapped[str] = mapped_column(String(20), default="", nullable=False)


class DatasetVersion(Base, TenantOwnedMixin):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "task_key", "version", name="uq_dataset_version"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    label_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)
    date_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    positive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    negative_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    censored_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scope: Mapped[str] = mapped_column(String(40), default="TENANT_LOCAL", nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    quality_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    object_key: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="built", nullable=False)


class ModelExperiment(Base, TenantOwnedMixin):
    __tablename__ = "model_experiments"

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    algorithm: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    hyperparameters_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="created", nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    artifact_reference: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    code_version: Mapped[str] = mapped_column(String(80), default="", nullable=False)


class ModelVersion(Base, TenantOwnedMixin):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "task_key", "version", name="uq_model_version"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(80), default="rules", nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    label_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    artifact_location: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="EXPERIMENTAL", nullable=False)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    training_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    training_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    experiment_id: Mapped[UUID | None] = mapped_column(ForeignKey("model_experiments.id"), nullable=True)
    python_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    package_versions: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    git_commit: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    random_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    importance_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    top_features_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    is_rules: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Prediction(Base, TenantOwnedMixin):
    __tablename__ = "predictions"
    __table_args__ = (Index("ix_predictions_entity", "tenant_id", "task_key", "entity_type", "entity_id"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    model_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    feature_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("ml_feature_snapshots.id"), nullable=True)
    prediction: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    probability: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prediction_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(20), default="SHADOW", nullable=False)
    explanation_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    provider_key: Mapped[str] = mapped_column(String(40), default="rules", nullable=False)


class ModelEvaluation(Base, TenantOwnedMixin):
    __tablename__ = "model_evaluations"
    __table_args__ = (Index("ix_model_eval_task", "tenant_id", "task_key", "model_version_id"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    model_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    prediction_id: Mapped[UUID | None] = mapped_column(ForeignKey("predictions.id"), nullable=True)
    outcome_label_id: Mapped[UUID | None] = mapped_column(ForeignKey("ml_outcome_labels.id"), nullable=True)
    correct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FeatureDriftBaseline(Base, TenantOwnedMixin):
    __tablename__ = "feature_drift_baselines"
    __table_args__ = (UniqueConstraint("tenant_id", "task_key", "feature_set_version", "dataset_version", name="uq_drift_baseline"),)

    task_key: Mapped[str] = mapped_column(String(60), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    distributions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class OpportunityFieldHistory(Base, TenantOwnedMixin):
    __tablename__ = "opportunity_field_history"
    __table_args__ = (Index("ix_opp_field_history", "tenant_id", "opportunity_id", "changed_at"),)

    opportunity_id: Mapped[UUID] = mapped_column(ForeignKey("opportunities.id"), index=True, nullable=False)
    field_name: Mapped[str] = mapped_column(String(40), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    new_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EntityFieldHistory(Base, TenantOwnedMixin):
    __tablename__ = "entity_field_history"
    __table_args__ = (Index("ix_entity_field_history", "tenant_id", "entity_type", "entity_id", "changed_at"),)

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    field_name: Mapped[str] = mapped_column(String(60), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    new_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecommendationFeedback(Base, TenantOwnedMixin):
    __tablename__ = "recommendation_feedback"
    __table_args__ = (Index("ix_rec_feedback", "tenant_id", "recommendation_id"),)

    recommendation_id: Mapped[UUID] = mapped_column(nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), default="expansion_recommendation", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    useful: Mapped[str] = mapped_column(String(8), default="", nullable=False)
