# Security

- HTTPS in production, security headers, CORS allowlist
- Argon2 password hashing
- JWT access + rotating refresh cookies
- RBAC via permission strings
- Shared-schema multi-tenancy with mandatory `tenant_id` filters; RLS is a later hardening step
- Rate limiting on auth and AI routes
- Secrets from environment only
- Encrypted integration credentials at rest (Phase 9+)
- Audit log on mutations and auth events
- Input validation (Pydantic / Zod), file type and size checks
- Least privilege for AI tools
- CSRF strategy for cookie refresh
- Parameterized SQL

AI data boundary: tools receive only records the principal can already read.
