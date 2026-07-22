# Forensic Audit — 2026-07-22

Master log. Requested scope: (1) eliminate tech debt, (2) competitor research, (3) verify tests actually pass (pytest/playwright/e2e), (4) remove stale docs + GitHub Copilot artifacts, pristine repo.

4 parallel agents dispatched. Report-only — nothing deleted/edited yet, pending user confirm per scoping decisions below.

## Scoping decisions (user, 2026-07-22)
- Tech debt: **report first, then PR** (not auto-fix).
- Competitors: allowance/chore apps (Greenlight, BusyKid, FamZoo, RoosterMoney, OurHome, S'moresUp, Bankaroo + others found).
- Docs cleanup: **flag then confirm** before deleting anything.

## Files
- `01-techdebt.md` — forensic code audit (backend + frontend)
- `02-docs-cleanup.md` — stale docs / GitHub Copilot artifact audit
- `03-competitors.md` — competitive positioning scan
- `04-test-verification.md` — live run of ruff/pytest/alembic/astro/playwright

## Headline

**Tests: all green.** ruff 0 violations, pytest 1894 passed/0 failed (79.10% cov), alembic single head (no-op upgrade), astro check + build clean. Playwright e2e run separately, see 04.

**Tech debt top 5** (see 01 for full list):
1. `register_family` (auth.py:81-381) — ~300 lines of business logic in the route handler, same endpoint family as the prior audit's CRITICAL cross-tenant bug.
2. Kiosk domain has **no service layer** — 692-line route file, only domain missing one.
3. `recycle_bin_service.py` — 4x near-duplicate restore/delete methods per entity type; `empty_recycle_bin` filters cutoff in Python instead of SQL (real perf bug); its own `SUPPORTED_MODELS` generic-dispatch dict is defined but unused.
4. Dead code left over from two past cleanups: `schemas/__init__.py:90-96` still exports removed `TaskBase` et al. (ImportError landmine), `BudgetSyncState` model/table still not dropped 7 weeks after being flagged in the 2026-06-04 audit.
5. 24 sites across 5 budget/bank services raise `fastapi.HTTPException` directly instead of the domain-exception convention — cosmetic today, will break confusingly once Jarvis MCP tools call these services directly (no HTTP context to catch it).

**Docs/Copilot**: no live GitHub Copilot config in the repo — it only exists inside an orphaned-but-still-git-registered worktree (`.claude/worktrees/agent-a34bc264adae2ec80/`, 7.2MB, fully merged into main, safe to `git worktree remove`). Real findings: `JARVIS_MCP.md` has wrong/self-contradictory infra info on a security-relevant gate; `.claudeignore` is hiding an accurate `ARCHITECTURE.md` for no current reason; `OAUTH_PAYMENT_SETUP.md` documents endpoints that don't exist; two unreferenced binary docs (BROCHURE_VENTA .html/.pdf, manual-usuario .md/.pdf) duplicate/predate current canonical docs.

**Competitors**: no researched competitor combines gamified chores + real-cash gig marketplace + full family budgeting + general AI copilot — each occupies at most 2 of those pillars. Biggest gap versus every real-money competitor (Greenlight, BusyKid, FamZoo, RoosterMoney, GoHenry, Mozper, Step): **no debit card issuance** and **no native mobile app**.

## Next step
Awaiting user go-ahead on which findings to act on (this session or as tracked PRs).
