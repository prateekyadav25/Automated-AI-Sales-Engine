# Security

- HTTPS in production, security headers, CORS allowlist
- Argon2 password hashing
- JWT access + rotating refresh cookies
- RBAC via permission strings
- Shared-schema multi-tenancy with mandatory `tenant_id` filters plus Postgres RLS (`set_config` tenant context; `agrayian_app` has no BYPASSRLS)
- Rate limiting on auth (Redis when available, in-process fallback). Broader AI/upload limits stay conservative.
- Secrets from environment only
- Encrypted integration credentials at rest (Fernet; set `TOKEN_ENCRYPTION_KEY` in production)
- Audit log on mutations and auth events
- Input validation (Pydantic / Zod), file type and size checks
- Least privilege for AI tools
- CSRF strategy for cookie refresh
- Parameterized SQL

AI data boundary: tools receive only records the principal can already read.
