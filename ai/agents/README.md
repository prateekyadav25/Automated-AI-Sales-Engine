# Agents

Runtime lives in `apps/api/app/ai` so FastAPI and Celery share one import path. Agent contracts:

- Supervisor
- AccountResearch
- Knowledge
- Lead scoring explain-only
- Email draft (no send)
