#!/usr/bin/env sh
set -eu
ROOT="${1:-./backups}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="$ROOT/$STAMP"
mkdir -p "$DEST"
ADMIN_URL="${DATABASE_ADMIN_URL:-${DATABASE_URL:-}}"
if [ -z "$ADMIN_URL" ]; then
  echo "DATABASE_ADMIN_URL or DATABASE_URL is required" >&2
  exit 1
fi
pg_dump "$ADMIN_URL" --no-owner --format=custom --file="$DEST/postgres.dump"
if [ -n "${S3_ENDPOINT:-}" ]; then
  echo "Object storage mirror is operator-owned; copy $S3_BUCKET separately." > "$DEST/object-storage.txt"
fi
echo "$STAMP" > "$DEST/MANIFEST"
echo "Backup written to $DEST"
