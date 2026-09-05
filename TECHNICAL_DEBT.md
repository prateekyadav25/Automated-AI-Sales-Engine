# Technical Debt

- PostgreSQL row-level security not yet enabled.
- Embeddings stored as JSON rather than pgvector columns.
- Refresh-token family reuse detection is basic (revoke on mismatch).
- OpenAPI types are hand-aligned in the web SDK, not yet generated into `packages/types` on every build.
- Kubernetes manifests are stubs.
- Playwright smoke is in CI (`e2e` job). Reply, CS risk, renewal, and expansion journeys wait for later batches.
- Autopilot UI polls TanStack Query; no SSE.
- Full 45-diagram set is grouped across docs; some future engines have architecture only.
