# Testing

Backend: pytest. Frontend: Vitest + React Testing Library. E2E later: Playwright.

Must cover: unit, API, tenant isolation, RBAC, workflows, agents/tools, critical journeys.

Tenant isolation is a release gate: a user in tenant A must receive 404/403 for tenant B ids, never the record.
