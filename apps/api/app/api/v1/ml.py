from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import AuthContext, require_permission
from app.db.session import get_db
from app.models.ml import DatasetVersion, ModelVersion, Prediction
from app.providers.object_storage import get_object_storage
from app.schemas.common import Envelope, Meta
from app.schemas.ml import (
    DatasetBuildIn,
    DatasetOut,
    ModelVersionOut,
    PredictionOut,
    PromoteIn,
    ReadinessOut,
    RollbackIn,
    TrainIn,
)
from app.services.ml.catalog import ensure_catalog
from app.services.ml.dataset import DatasetBuildError, build_dataset
from app.services.ml.evaluate import list_models
from app.services.ml.governance import GovernanceError, promote, rollback_champion
from app.services.ml.readiness import list_readiness
from app.services.ml.train import TrainingRefused, train_candidate
from app.services.query import get_owned

router = APIRouter(prefix="/ml", tags=["ml"])


@router.get("/readiness", response_model=Envelope[list[ReadinessOut]])
def ml_readiness(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.view"))],
) -> Envelope[list[ReadinessOut]]:
    ensure_catalog(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    rows = list_readiness(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    db.commit()
    return Envelope(data=[ReadinessOut(**row) for row in rows], meta=Meta(total=len(rows)))


@router.get("/datasets", response_model=Envelope[list[DatasetOut]])
def ml_datasets(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.view"))],
) -> Envelope[list[DatasetOut]]:
    rows = db.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.tenant_id == ctx.tenant_id, DatasetVersion.deleted_at.is_(None))
        .order_by(DatasetVersion.created_at.desc())
    ).all()
    return Envelope(data=[DatasetOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/datasets", response_model=Envelope[DatasetOut])
def ml_build_dataset(
    body: DatasetBuildIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.dataset.create"))],
) -> Envelope[DatasetOut]:
    try:
        row = build_dataset(
            db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user.id,
            task_key=body.task_key,
            feature_set_version=body.feature_set_version,
            label_version=body.label_version,
        )
    except DatasetBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return Envelope(data=DatasetOut.model_validate(row))


@router.get("/models", response_model=Envelope[list[ModelVersionOut]])
def ml_models(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.view"))],
) -> Envelope[list[ModelVersionOut]]:
    ensure_catalog(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id)
    rows = list_models(db, ctx.tenant_id)
    db.commit()
    return Envelope(data=[ModelVersionOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))


@router.post("/models/{model_id}/promote", response_model=Envelope[ModelVersionOut])
def ml_promote(
    model_id: UUID,
    body: PromoteIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.promote"))],
) -> Envelope[ModelVersionOut]:
    try:
        row = promote(
            db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user.id,
            model_id=model_id,
            target=body.target,
            reason=body.reason,
        )
    except GovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return Envelope(data=ModelVersionOut.model_validate(row))


@router.post("/models/rollback", response_model=Envelope[ModelVersionOut])
def ml_rollback(
    body: RollbackIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.rollback"))],
) -> Envelope[ModelVersionOut]:
    try:
        row = rollback_champion(
            db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user.id,
            task_key=body.task_key,
            reason=body.reason,
        )
    except GovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return Envelope(data=ModelVersionOut.model_validate(row))


@router.post("/train", response_model=Envelope[ModelVersionOut])
def ml_train(
    body: TrainIn,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.train"))],
) -> Envelope[ModelVersionOut]:
    try:
        row = train_candidate(
            db,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user.id,
            task_key=body.task_key,
            dataset_version=body.dataset_version,
            algorithm=body.algorithm,
        )
    except TrainingRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return Envelope(data=ModelVersionOut.model_validate(row))


@router.get("/models/{model_id}/artifact")
def ml_artifact(
    model_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.train"))],
):
    row = get_owned(db, ModelVersion, ctx.tenant_id, model_id)
    expected = f"tenant/{ctx.tenant_id}/"
    if (
        not row.artifact_location
        or ".." in row.artifact_location
        or not row.artifact_location.startswith(expected)
    ):
        raise HTTPException(status_code=404, detail="No artifact")
    data = get_object_storage().get(row.artifact_location)
    return Response(content=data, media_type="application/octet-stream")


@router.get("/predictions", response_model=Envelope[list[PredictionOut]])
def ml_predictions(
    db: Annotated[Session, Depends(get_db)],
    ctx: Annotated[AuthContext, Depends(require_permission("ml.view"))],
    entity_type: str | None = None,
    entity_id: str | None = None,
    task_key: str | None = None,
) -> Envelope[list[PredictionOut]]:
    stmt = select(Prediction).where(Prediction.tenant_id == ctx.tenant_id, Prediction.deleted_at.is_(None))
    if entity_type:
        stmt = stmt.where(Prediction.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(Prediction.entity_id == entity_id)
    if task_key:
        stmt = stmt.where(Prediction.task_key == task_key)
    rows = db.scalars(stmt.order_by(Prediction.created_at.desc()).limit(100)).all()
    return Envelope(data=[PredictionOut.model_validate(row) for row in rows], meta=Meta(total=len(rows)))
