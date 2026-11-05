"""Retire the fictional sample companies and everything linked to them in one workspace.

No provider is called. Rows are soft-deleted and stay in the database.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import get_engine, get_session
from app.db.tenant_context import set_tenant_context
from app.models.identity import Tenant
from app.services.sample_data import retire_sample_data


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.retire_samples", description=__doc__)
    parser.add_argument("--tenant", default="agrayian", help="Workspace slug. Default: agrayian.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be retired and change nothing.")
    args = parser.parse_args()
    get_engine()
    db = get_session()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if tenant is None:
            raise SystemExit(f"No workspace has the slug {args.tenant!r}.")
        workspace = tenant.name
        set_tenant_context(db, tenant.id)
        counts = retire_sample_data(db, tenant_id=tenant.id, now=datetime.now(UTC))
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    verb = "Would retire" if args.dry_run else "Retired"
    print(f"{verb} {sum(counts.values())} sample rows in {workspace}.")
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
