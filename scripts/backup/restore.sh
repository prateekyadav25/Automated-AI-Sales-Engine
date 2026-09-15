#!/usr/bin/env sh
set -eu
DUMP="${1:?path to postgres.dump}"
TARGET="${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
pg_restore --clean --if-exists --no-owner --dbname="$TARGET" "$DUMP"
echo "Restore completed into $TARGET"
