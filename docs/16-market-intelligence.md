# Market Intelligence Engine

Phase 7 — implemented.

Entities: `Market`, `MarketSignal`, `AccountSignal`, `TechnologySignal`, `IntentSignal`, `CompetitiveSignal`, `TriggerEvent`.

Every signal stores source, evidence, confidence, timestamp, type, entity, impact, recommended action. Mock providers are labeled `is_mock`.

Scores (`rules-v1`, deterministic): market attractiveness, AI readiness, technology readiness, budget potential, growth potential, competitive intensity, procurement probability, buying timing.

Account Research agent produces company overview, priorities, tech, triggers, stakeholders, and relevant AGRAYIAN solutions from tools + RAG — not from invented facts.

API: `/api/v1/market`, `/overview`, `/{id}/score`, `/desk/signals`, `/desk/triggers`, `/refresh`.
UI: `/market`, `/market/[id]`, `/market/signals`, `/market/triggers`.
