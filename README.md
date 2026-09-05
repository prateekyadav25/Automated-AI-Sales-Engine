# AGRAYIAN Autonomous Revenue OS

Autonomous AI revenue operating system for AGRAYIAN AI LABS.

Lifecycle: Intelligence → Acquire → Sell → Close → Succeed → Retain → Expand → Advocate → Learn

This is not a CRM-only product. The architecture supports the full revenue flywheel. MVP implements Phases 0–6.

## Local development

```bash
cp .env.example .env
docker compose up --build
```

Services:

- Web: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- MinIO: http://localhost:9001

Demo users (fictional):

| Email | Password | Role |
|---|---|---|
| admin@agrayian.demo | Agrarian!Demo1 | Tenant Admin |
| seller@agrayian.demo | Agrarian!Demo1 | Sales Rep |
| readonly@agrayian.demo | Agrarian!Demo1 | Read Only |
| admin@northline.demo | Agrarian!Demo1 | Tenant Admin (second tenant) |

## Without Docker (API)

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
set DATABASE_URL=sqlite:///./test.db
set SECRET_KEY=dev-secret
set LLM_PROVIDER=mock
uvicorn app.main:app --reload --port 8000
```

## Validation

```bash
cd apps/api && ruff check app tests && pytest
cd apps/web && pnpm lint && pnpm exec tsc --noEmit && pnpm test && pnpm build
```

## Documentation

Start at [docs/00-product-vision.md](docs/00-product-vision.md) and [docs/30-implementation-roadmap.md](docs/30-implementation-roadmap.md).
