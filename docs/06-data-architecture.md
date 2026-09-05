# Data Architecture

## Principles

- Shared PostgreSQL, `tenant_id` on every tenant-owned row.
- UUID primary keys.
- Soft delete where recovery matters (`deleted_at`).
- Enrichment values store source, confidence, verified_at.
- Scores store components, reasons, version, timestamp.
- Data quality tracked as completeness, validity, freshness, confidence, duplicate risk.

## Stores

| Store | Use |
|---|---|
| PostgreSQL + pgvector | OLTP + RAG chunks |
| Redis | cache, rate limit, celery broker |
| MinIO / S3 | documents, exports, recording metadata |

## Quality

The DataQuality agent (later) flags incomplete accounts, stale scores, and probable duplicates. Uncertain merges require human review.
