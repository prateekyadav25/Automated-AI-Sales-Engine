# 36 — Disaster Recovery

RPO target: 24 hours for Postgres and object storage. RTO target: 4 hours to a restored environment with current schema.

## What is backed up

- Postgres via `scripts/backup/backup.sh` (`pg_dump` custom format using `DATABASE_ADMIN_URL`).
- Object storage is operator-owned. The backup script records that MinIO/S3 must be mirrored separately.
- Application images and Kustomize overlays are in git. Secrets are not.

## Backup

```sh
DATABASE_ADMIN_URL=postgresql://agrayian:agrayian@localhost:5432/agrayian \
  sh scripts/backup/backup.sh ./backups
```

Store dumps off-box. Mark `backup_success=1` after `scripts/backup/verify_restore.py` passes.

## Restore

```sh
DATABASE_ADMIN_URL=postgresql://agrayian:agrayian@localhost:5432/agrayian_restore \
  sh scripts/backup/restore.sh ./backups/<stamp>
RESTORE_DATABASE_URL=postgresql+psycopg://agrayian:agrayian@localhost:5432/agrayian_restore \
  python scripts/backup/verify_restore.py ./backups/<stamp>/postgres.dump
```

Use the `agrayian_admin` role (`BYPASSRLS`) for dump/restore. Application traffic stays on `agrayian_app`.

## Failover notes

- Redis is a broker/cache. Authoritative Autopilot state is Postgres. Rebuild the broker; do not treat Redis as the system of record.
- After restore, run the migrate Job if the dump is behind `alembic head`.
- Staging must not restore production customer lists into a live-outreach environment.
