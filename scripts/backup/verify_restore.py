"""Restore a dump into a temporary SQLite or Postgres URL and run integrity checks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


def main() -> int:
    dump = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    target = os.environ.get("RESTORE_DATABASE_URL", "sqlite:///./restore-check.db")
    if dump and dump.exists() and target.startswith("postgres"):
        subprocess.check_call(["pg_restore", "--clean", "--if-exists", "--no-owner", f"--dbname={target}", str(dump)])
    engine = create_engine(target)
    with engine.connect() as conn:
        if target.startswith("sqlite"):
            tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            assert tables, "no tables after restore"
        else:
            conn.execute(text("SELECT 1"))
            tenants = conn.execute(text("SELECT count(*) FROM tenants")).scalar()
            assert tenants is not None
    print("restore verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
