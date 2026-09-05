# Workflow Architecture

```text
Trigger → Conditions → Actions
```

Runs are persisted in `workflow_runs`. Sequences, onboarding, renewals, and approvals never live only in memory.

**Phase 22 implemented:** `Playbook` rows execute those actions and persist `WorkflowRun` logs. No live send.

MVP foundation: event trigger, simple condition JSON, actions `create_task`, `write_activity`, `enqueue_agent`, `request_approval`.

Example: `deal.won` → create customer, create renewal stub, create handoff task, write activity.
