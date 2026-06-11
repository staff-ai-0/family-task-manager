# Remediation Plan — mapped to user's 3 goals

Source: workflow w00ab6eha (32 agents). 87 findings → 4 critical, 24 high, 35 med, 22 low.
50 confirmed-real by adversarial verify; 37 unverified (spot-check before acting).
Full detail: 02-techdebt.md, 04-ux-friction.md, 05-verified-prioritized.md.

Two criticals independently re-verified by hand (this session): auth-register cross-tenant
escalation + public /uploads mount. Both real.

---

## TRACK A — CRITICAL security/correctness (PROD BLOCKERS — do first)

A1. **[CRITICAL] Broken access control in `/api/auth/register`** `[authz]`
    `UserCreate` accepts client `role` (can = parent) + `family_id`; `register_user` only
    checks the family *exists* (auth_service.py:43-55). Anyone can mint a PARENT in ANY
    family → full cross-tenant takeover. **Fix:** drop public `/register` (or require a
    valid invitation/join_code) and force role server-side. Keep `/register-family`
    (code-gated) + invitation flow as the only paths. Effort M. **Needs tests.**

A2. **[CRITICAL] Public `/uploads` static mount** `[authz]`
    `main.py:147` mounts `/app/uploads` via StaticFiles, no auth. Backend is public
    (api-gcp-family.agent-ia.mx) → all gig-proof + receipt images readable by anyone with
    the (UUID) URL. **Fix:** remove the StaticFiles mount; serve images only through an
    authenticated, family-scoped FastAPI route (frontend already proxies with auth). Effort M.

A3. **[CRITICAL] Sync LLM/vision client in async paths, no timeout** `[resilience]`
    Blocking OpenAI/Anthropic client called inside async functions; can block the event
    loop up to 600s (receipt scanner, jarvis). **Fix:** use async client or
    `run_in_threadpool`, add explicit timeouts + graceful failure. Effort M.

A4. **[CRITICAL] Month dashboard N+1** `[perf]`
    ~5 queries per category × N categories per load. **Fix:** batch/aggregate in one query
    (or a CTE), mirror the int-cast pattern. Effort M.

## TRACK B — Production-readiness / ops (HIGH)

B1. No rate limiting anywhere → auth brute force + enumeration. Add slowapi/redis limiter on
    auth + scan endpoints. Effort M.
B2. APScheduler + overdue-sweep fire in EVERY uvicorn worker (prod --workers 2 → 2× cron).
    Gate scheduler to one worker (leader lock / separate process). Effort M.
B3. `/health` reports DB "connected" without touching DB (static dict). Make it actually
    ping DB + redis; add `/ready`. Effort S.
B4. No startup secret validation — boots with placeholder SECRET_KEY (forgeable JWTs).
    Fail-fast in config on default/empty SECRET_KEY in prod. Effort S.
B5. No error tracking + no structured logging. Add Sentry + JSON logging. Effort M.
B6. PayPal webhook drops events on transient DB failure (dedupe key burned before commit).
    Reorder: commit state change before marking processed, or make idempotent. Effort M.
B7. PayPal calls use blocking `requests` in async handlers. Move to httpx async / threadpool.
    Effort M.

## TRACK C — Tech debt / data integrity / cleanup

C1. **[HIGH] gig_claims unique-constraint drift** ORM (full unique) vs migration
    (partial `WHERE status != 'rejected'`). Reconcile; add migration to match intent. M.
C2. **[HIGH] Double-award / double-trust-streak race** on gig approval (check-then-write,
    no row lock/idempotency). Add `SELECT ... FOR UPDATE` or unique award guard. M.
C3. **[HIGH] Dev/lint tooling + vuln-prone pins in prod image** (no dev/prod dep split).
    Split requirements; multistage build. M.
C4. **[HIGH] Account-list N+1** (3 queries/account). Batch balances (CLAUDE.md already
    documents the int-cast; same place). M.
C5. Dead code / cruft to delete: root `fam-app.zip` (275KB binary), `test.ipynb`,
    root `test_assignment_types.py`, `actual/` (decommissioned Actual Budget), `web-stack/`,
    `ecosystem.config.cjs` (pm2, unused), committed `logs/`, `.playwright-mcp/` snapshots,
    legacy `deploy-prod.sh`, `/api/sync` 410 leftovers. Gitignore the junk. S–M.
C6. CLAUDE.md documents only budget/task/gig but repo has pet/meals/shopping/calendar/
    jarvis/chat/dm/kiosk/consequences/rewards. Document or mark experimental. S.
C7. ~7 large files >800 lines (task_assignment_service 1236, receipt_scanner 1126,
    budget/settings.astro 1117) — split when touched. M each, opportunistic.

## TRACK D — UX simplification (the headline ask) — NEEDS DESIGN PASS

**Dominant theme: TASK and GIG are two parallel "extra-work" systems with duplicate
create/claim/approve UIs and leaking jargon.** This is the biggest simplification lever.

D-TASK/GIG (unify):
- Two parallel 'extra work' systems, duplicate create/claim/approve UIs (HIGH, confirmed).
- Kid sees two unrelated "gigs" UIs with same vocabulary (HIGH). Parent has TWO approval
  screens; dashboard badge misses half (HIGH).
- Gig jargon (Gig mode / Competition / Rotation / Collaboration) leaks into mandatory-task
  create+edit (MED, confirmed). Create modal silently zeroes non-bonus points (MED, confirmed).
- Kid claim→proof split across 2 pages w/ dead-end hop; raw confirm/prompt/alert + full
  reloads vs polished task-approval screen.
- "1 pt = $1 MXN" cash framing shown but no cash payout exists → trust failure.
→ Proposal: ONE mental model "work" with two types (mandatory chore / optional gig), ONE
  create flow, ONE kid list, ONE approval queue. Brainstorm before coding.

D-BUDGET:
- "Categories" nav links DEAD (point to #categories accordion that doesn't exist) (HIGH, confirmed).
- No way to create first Account from add-transaction/empty flows — buried in Settings (HIGH).
- FAB mode buttons MISLABELED: "Photo"→receipt scan, "Scan"→CSV import (MED, confirmed).
- Nav triple-fragmented (3 tabs + 13-item drawer + receipt icon + FAB + bottom nav).
- Allocate hidden behind unlabeled "Ready to Assign"; Reports "Budget vs Actual" permanent
  "Coming soon"; edit flows hard `location.reload`.
→ Quick wins (dead links, FAB labels, account-create entry) are S and safe; nav
  consolidation needs design.

---

## Suggested sequencing
1. **Track A (criticals)** — immediately, each with a regression test. Security blockers.
2. **Track B3/B4** (health + secret validation) — S, ship with A.
3. **Track C5** cruft delete + **C6** docs — low risk, shrinks surface.
4. **Track B/C remaining HIGHs** — batched.
5. **Track D** — brainstorm task/gig unification first (design), then budget quick wins,
   then nav. Largest UX payoff but needs product decisions.

## Open question for user
Start with Track A (security criticals, recommended) now, or prioritize the UX
simplification (Track D) first? A is lower-risk + protects prod; D needs a design pass.
