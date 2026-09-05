# Frontend Architecture

## Stack

Next.js App Router, React, TypeScript strict, Tailwind CSS, shadcn/ui, TanStack Query, TanStack Table, React Hook Form, Zod, Recharts.

## Layouts

- `(auth)` — login
- `(app)` — authenticated shell with sidebar, top bar, command palette, copilot drawer

## MVP routes

| Route | Permission |
|---|---|
| `/` | command_center.read |
| `/leads` `/leads/[id]` | leads.read |
| `/accounts` `/accounts/[id]` | accounts.read |
| `/contacts` `/contacts/[id]` | contacts.read |
| `/pipeline` `/opportunities/[id]` | opportunities.read |
| `/tasks` | tasks.read |
| `/intelligence` | ai.copilot |
| `/knowledge` | knowledge.read |
| `/automation/approvals` | ai.approvals.read |
| `/admin/users` `/admin/teams` `/admin/roles` `/admin/flags` `/admin/audit` | admin.* |

## State

- Session and permissions: cookie + `/auth/me`
- Server data: TanStack Query via `packages/sdk`
- Forms: RHF + Zod matching API schemas
- UI chrome: `packages/ui`

## Page contract

Loading, empty, error, success, 403, no-results, pagination, search, filter, sort, responsive.
