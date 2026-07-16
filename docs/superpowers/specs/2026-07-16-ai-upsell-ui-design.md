# AI Upsell UI — design (2026-07-16)

## Context

PR #120 gated all AI/LLM entry points behind paid plans. Free families now get
403 `upgrade_required` on five frontend surfaces that previously "worked":
recipe import (meals), auto-categorize (budget transactions), Jarvis schedules,
template translate, and the a2a price-agent settings page. Today those 403s
render as raw errors ("[object Object]", "undefined de undefined").

## Approach (approved: hybrid server-side)

Follow the existing `budget/reports.astro` pattern: resolve the family's plan
server-side via `/api/subscriptions/current`, **fail open** (only lock when the
plan is positively `free`; backend still enforces), and render upsell UI
instead of dead controls.

- **Shared helper** `frontend/src/lib/plan.ts` — `isFreePlan(token)`
  replicating the reports fail-open logic (reads `plan.name` or `plan_name`).
- **Full-page lock** (pages that are 100% AI):
  - `/parent/jarvis-schedules` → `UpgradePrompt feature="ai_features"` card
    instead of form + list; skip the SSR form action when free.
  - `/parent/settings/a2a` → `UpgradePrompt feature="a2a_webhook"` card
    instead of the config form.
- **Inline lock chips** (controls inside mixed pages), linking to
  `/parent/settings/subscription`:
  - `/meals` import section → compact 🔒 "Plus" strip replacing URL input + button.
  - `/budget/transactions` auto-categorize button → 🔒 chip link when free.
  - `/parent/tasks/[id]/edit` translate button → 🔒 chip link when free.
- **UpgradePrompt.astro** — add `ai_features` and `a2a_webhook` labels.
- **`/api/translate/[id].ts` proxy** — stop flattening every backend error to
  500; pass the backend status through (defensive; SSR lock means free users
  normally never call it).
- `TaskCreateModal` background auto-translate is fire-and-forget and already
  fails silently on 403 — no change.

## Non-goals

Metered-limit upsells (receipt scan counter), new visual design (reuse
UpgradePrompt as-is), i18n refactor (keep inline ES/EN ternaries per repo
convention).

## Verification

`npm run build` (frontend has no unit-test infra). Playwright e2e optional,
requires local podman stack; backend enforcement already covered by
`backend/tests/test_ai_gating.py`.
