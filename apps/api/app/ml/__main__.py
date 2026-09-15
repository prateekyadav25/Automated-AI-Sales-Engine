"""python -m app.ml readiness|build-dataset|train|evaluate|promote"""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from sqlalchemy import select

from app.db.session import get_engine, get_session
from app.models.identity import Tenant, User
from app.services.ml.catalog import ensure_catalog
from app.services.ml.dataset import build_dataset
from app.services.ml.evaluate import evaluate_matured
from app.services.ml.governance import promote
from app.services.ml.readiness import list_readiness, readiness_report
from app.services.ml.train import train_candidate


def _session(slug: str):
    get_engine()
    db = get_session()
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise SystemExit(f"Tenant {slug} not found")
    user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.is_active.is_(True)))
    return db, tenant, user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ml")
    parser.add_argument("command", choices=["readiness", "build-dataset", "train", "evaluate", "promote"])
    parser.add_argument("task", nargs="?", default="")
    parser.add_argument("--tenant", default="agrayian")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--model-id", default="")
    parser.add_argument("--target", default="CANDIDATE")
    parser.add_argument("--reason", default="cli")
    args = parser.parse_args(argv)
    db, tenant, user = _session(args.tenant)
    actor = user.id if user else None
    try:
        ensure_catalog(db, tenant_id=tenant.id, actor_id=actor)
        if args.command == "readiness":
            rows = [readiness_report(db, tenant_id=tenant.id, task_key=args.task)] if args.task else list_readiness(db, tenant_id=tenant.id)
            print(json.dumps(rows, indent=2, default=str))
        elif args.command == "build-dataset":
            if not args.task:
                raise SystemExit("task required")
            row = build_dataset(db, tenant_id=tenant.id, actor_id=actor, task_key=args.task)
            print(json.dumps({"version": row.version, "fingerprint": row.fingerprint, "rows": row.row_count}))
        elif args.command == "train":
            if not args.task or not args.dataset:
                raise SystemExit("task and --dataset required")
            row = train_candidate(db, tenant_id=tenant.id, actor_id=actor, task_key=args.task, dataset_version=args.dataset)
            print(json.dumps({"version": row.version, "status": row.status}))
        elif args.command == "evaluate":
            print(json.dumps({"evaluated": evaluate_matured(db, tenant_id=tenant.id, actor_id=actor)}))
        elif args.command == "promote":
            if not args.model_id:
                raise SystemExit("--model-id required")
            row = promote(
                db,
                tenant_id=tenant.id,
                actor_id=actor,
                model_id=UUID(args.model_id),
                target=args.target,
                reason=args.reason,
            )
            print(json.dumps({"version": row.version, "status": row.status}))
        db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
