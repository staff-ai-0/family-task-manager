# Production-Readiness & Tech-Debt Audit — 2026-06-04

Master log. Survives context reset. Read this first to resume.

## Goals (from user)
1. Eliminate tech debt
2. Find gaps → production ready
3. Simplify UX workflows for **budget**, **task**, **gigs**

## Shipped (PRs)
- PR #31 — rename Frankie→Jarvis → base `main` (branch `rename/frankie-to-jarvis`, commit 3f4195f)
- PR #32 — security A1-A4 → base `rename/frankie-to-jarvis` (STACKED; retarget to main after #31; commit b3c03b4)
- Not merged/deployed. Deploy: prod .env FRANKIE_→JARVIS_ first; run full suite in CI.

## Status
- [x] Repo scout (see below)
- [x] Phase 1: Map codebase (8 cluster explorers) → 01-map.md
- [x] Phase 2: Audit techdebt/prod-gaps/UX (12 dimensions) → 02, 04
- [x] Phase 3: Adversarial verify + prioritize → 05-verified-prioritized.md
- [x] Phase 4: Plan remediation → 06-plan.md
- [x] Phase 5: Execute — TRACK A (all 4 security/perf criticals) DONE, TDD green, no regressions → 07-trackA-progress.md
- [ ] Remaining tracks: B (ops), C (cleanup), D (UX) — not started
- [x] SIDE TASK: Frankie→Jarvis rename COMPLETE → RENAME-frankie-to-jarvis.md (branch rename/frankie-to-jarvis, not committed)

## Audit headline (workflow w00ab6eha — 32 agents, 2.65M tok)
87 findings: 4 critical, 24 high, 35 med, 22 low. 50 confirmed-real, 37 unverified.

### CRITICAL (all confirmed; top 2 hand-re-verified this session)
1. `/api/auth/register` accepts client role=parent + family_id, only checks family exists
   → mint PARENT in ANY family → cross-tenant takeover (auth_service.py:43-55). [A1]
2. `/uploads` StaticFiles mount public, no auth → all gig-proof/receipt images readable
   (main.py:147). [A2]
3. Sync LLM/vision client in async paths, no timeout → event-loop block ≤600s. [A3]
4. Month dashboard N+1 (~5 queries × N categories). [A4]

### Biggest UX lever
TASK and GIG are two parallel "extra-work" systems with duplicate create/claim/approve
UIs + leaking jargon. Unify into one model. Budget has dead nav links + buried account
creation + mislabeled FAB (quick wins). See 06-plan.md Track D.

### RETRACTED false alarm
"alembic multiple heads / broken tree" was my regex bug, NOT real. `alembic heads`=1. See 03.

## Files in this audit
- `00-INDEX.md` — this file (master progress log)
- `01-map.md` — codebase map (Phase 1)
- `02-techdebt.md` — tech debt findings
- `03-prod-gaps.md` — production-readiness gaps
- `04-ux-friction.md` — UX friction (budget/task/gigs)
- `05-verified-prioritized.md` — verified + ranked backlog
- `06-plan.md` — remediation plan

## Scout results (2026-06-04)
Repo MUCH bigger than CLAUDE.md documents. CLAUDE.md only covers budget/task/gig.
Actual domains present:
- Core: auth, families, users, invitations, subscriptions (PayPal), notifications, push
- Tasks: tasks (legacy), task_templates, task_assignments
- Gigs: gig_offering, gig_claim
- Budget: 20 services, 18 sub-routes (well-documented)
- **UNDOCUMENTED in CLAUDE.md**: pet (kid_pet, pup_snapshot), meals, shopping, calendar
  (calendar_scanner), frankie (AI assistant + tools + schedules + SSE), family_chat,
  dm, kiosk, analytics, consequences, rewards, points_conversion, recipe_importer, fx_service
- Backend: 184 py files. Frontend: 113 pages.
- TODO/FIXME/HACK markers: only 10 (low — but debt likely hidden, not marked)
- Migrations: alembic versions NOT in backend/alembic/versions/ (need to locate)
- Tests: ~90 test files (CLAUDE.md claims 477 tests, 416 passing, 51 pre-existing failures)

### Largest files (refactor candidates)
Backend:
- task_assignment_service.py 1236
- budget/receipt_scanner_service.py 1126
- budget/allocation_service.py 972
- schemas/budget.py 887
- email_service.py 857
- budget/transaction_service.py 850
Frontend:
- budget/settings.astro 1117
- lib/api/budget.ts 962
- budget/transactions.astro 883
- lib/i18n.ts 883
- components/TaskCreateModal.astro 741

### Root-level cruft (debt smell)
- fam-app.zip (275KB committed binary)
- test.ipynb, test_assignment_types.py (stray root test files)
- deploy-prod.sh (LEGACY, kept)
- actual/ dir (decommissioned Actual Budget — should be gone?)
- web-stack/ dir (unknown)
- ecosystem.config.cjs (pm2? unused?)
- .opencode/, logs/ committed?

## Next action
Run Phase 1 workflow: parallel explorers map each domain → write to 01-map.md
