# Tech-Debt Forensic Audit — backend/app + frontend/src

Predecessor audits skimmed: `docs/audit/2026-06-04` (00-INDEX.md, 05-verified-prioritized.md), `2026-07-02-ux/findings.md`, `2026-07-07/01-launch-gaps.md`. Most 2026-06-04 findings are **already fixed**: root cruft gone, requirements.txt cleaned, `.python-version` matches Dockerfile, cloudflared pinned by digest, legacy Task system removed (2026-07-16), silent-exception-swallow sites now log, single alembic head, ruff zero violations. This report covers what's **new or still open**.

## Ranked findings

**P1 — `register_family` (backend/app/api/routes/auth.py:81-381)**: ~300 lines of business logic live directly in the route handler — email-uniqueness check, join-code family lookup, plan member-limit enforcement (inline bilingual error strings), consent/approval-status state machine, referral crediting, family/user creation. Violates routes→services→models layering. Successor to the exact endpoint that had the prior audit's #1 CRITICAL (cross-tenant privilege escalation). Contrast `register()` at line 51, which correctly delegates to `AuthService.register_user`. Best extraction candidate — this complexity is exactly what makes registration bugs easy to introduce and hard to unit-test in isolation.

**P1 — Kiosk domain has no service layer** (`backend/app/api/routes/kiosk.py`, 692 lines; `find services -iname "*kiosk*"` → nothing). Every other domain (analytics, family_cup, oversight, onboarding, routines, referrals) has a matching `*_service.py`; kiosk does not. `snapshot()` (kiosk.py:476-604+) does timezone resolution, member/task joins, and a weekly-leaderboard `GROUP BY` aggregation directly in the route. Largest concentration of untestable-in-isolation business logic in the routes tier.

**P1 — `backend/app/services/budget/recycle_bin_service.py`**: `restore_transaction/account/category/category_group` (141-230) and `permanently_delete_transaction/account/category/category_group` (233-319) are 4 near-identical copies each, one per entity type — collapsible to one generic method parameterized by model. Worse: `empty_recycle_bin` (321-386) loads **every** soft-deleted row per family per entity type into Python and filters by `deleted_at.timestamp() < cutoff` in a loop instead of pushing the cutoff into the SQL `WHERE` — real perf bug for a family with a large recycle bin. `SUPPORTED_MODELS` dict (line 29) is defined but never referenced anywhere (`grep -rn SUPPORTED_MODELS` → only its own definition) — looks like the generic implementation was planned and abandoned.

**P1/P2 — Services raising `fastapi.HTTPException` instead of domain exceptions** (`app.core.exceptions.NotFoundException`/`ValidationError`/etc., translated by `exception_handlers.py`): `budget/transfer_service.py` (10 sites), `bank_service.py` (6), `savings_goal_service.py` (5), `family_export_service.py` (2), `google_oauth_service.py` (1) — 24 sites total. Couples service layer to the web framework. Cosmetic today (nothing in `app/mcp/` calls into these four services), but will break confusingly the moment Jarvis MCP wires up a "transfer between jars" or "check savings goal" tool, since MCP adapters call services directly with no HTTP context to catch the exception.

**P2 — `backend/app/schemas/__init__.py:91-96`**: `__all__` lists `TaskBase`, `TaskCreate`, `TaskUpdate`, `TaskComplete`, `TaskResponse`, `TaskWithDetails` under `# Task schemas (legacy)`, but none are imported anywhere in the file — residue of the 2026-07-16 legacy-Task removal that missed this file. Verified reproducible: `from app.schemas import TaskBase` raises `ImportError`. Zero current blast radius (nothing imports these names) but a landmine — ruff's F822 doesn't catch it (only F401 scoped to `__init__.py` in ruff.toml). One-line fix: delete lines 90-96.

**P2 — `BudgetSyncState` still fully dead** (`backend/app/models/budget.py:252`, `family.py:111` relationship, exported in `models/__init__.py:30,94`). Zero service/route references confirmed; only mentions are `family_export_service.py:208,244` calling it "legacy internal points<->budget sync bookkeeping (decommissioned...)". Flagged in the 2026-06-04 audit (MEDIUM #19), **still open 7 weeks later** — needs a migration to drop the model/table/relationship.

**P2 — Duplicate amount-tolerance calculation**: `budget/dedup_service.py:57,108` and `budget/duplicate_guard_service.py:31,44` both independently define `AMOUNT_TOLERANCE = 0.01` and the identical `tol = max(1, int(abs(amount) * tolerance))` snippet. Small, but a clean extraction candidate given both sit in the same 28-service budget module describing overlapping "is this a duplicate transaction" logic.

**P2 — 3 orphaned frontend components**: `frontend/src/components/ui/BottomSheet.astro`, `SectionHeader.astro`, `FormField.astro` — zero references anywhere in `pages/`, `components/`, `layouts/` (targeted grep confirmed), while sibling files in the same directory (`Card.astro`, `Badge.astro`, `Button.astro`, `PageHeader.astro`) are actively used. Looks like an abandoned design-system pass from `57aa149 refactor(ui): close remaining shared-component gaps`. Delete or wire up.

**P2 — Ad hoc "kid-only" role gates instead of a shared dependency**: `backend/app/api/routes/bank.py` (7 sites: 78, 126, 154, 202, 297, 381, 405; local `_require_kid` helper at line 67), `gigs.py:216,293`, `kiosk.py:353,600`, `rewards.py:71,87,108` all repeat `if current_user.role == UserRole.PARENT: raise HTTPException(403, ...)` inline. CLAUDE.md documents `require_parent_role` but no symmetric `require_kid_role`/`require_non_parent_role` dependency exists, so every router reinvents it. Low severity (logic correct everywhere checked) but a clear candidate for a shared `core/dependencies.py` addition.

**P2 — Dependency staleness** (backend/requirements.txt pins vs. latest, not the drifted local `.venv`): `alembic==1.13.1` (latest 1.18.5), `fastapi==0.115.6` (latest 0.139.2), `authlib==1.3.0` (latest 1.7.2 — OAuth library, worth priority review even without a confirmed CVE), `redis==5.0.1` (latest is a major version 8.x ahead). No confirmed CVEs at these specific pins from version numbers alone, but meaningfully behind; `authlib`/`fastapi` are security-relevant enough to schedule a bump-and-test pass. Frontend (`npm outdated`) healthy — only patch/minor gaps.

**P2 — Bare `except Exception: pass`, checked, not actionable**: `budget/receipt_scanner_service.py:1187-1188` and `family_chat_service.py:301-302` both guard a `db.rollback()` call itself (defensive "don't let the rollback-of-a-rollback throw"). Correctly scoped.

**P3 — `frontend/src/middleware.ts:315`**: `console.log` for "No access_token for protected route" fires unconditionally (not gated by `import.meta.env.DEV` like the sibling log at line 136) on every unauthenticated hit to a protected route in production — log noise, consistent with the still-open "no structured logging" gap from prior audits.

## TODO/FIXME/HACK/XXX — full grep, with assessment

Backend:
- `budget/month.py:177` `# TODO: Add income tracking, balance calculations, etc.` — real, still open; low priority, dashboard scope intentionally partial.
- `budget/transfer_service.py:335` `# TODO: In a full implementation, we'd calculate actual spending from transactions` — real; "cover overspending" flow approximates via `budgeted_amount >= 0` rather than actual transaction totals. Worth revisiting if cover-overspending amounts are ever reported wrong.
- `subscriptions.py:314`, `file_import_service.py:128`, `receipt_scanner_service.py:205`, `paypal_service.py:141,147` — false positives (`XXXX`/`I-XXXX`/`P-XXXX` placeholder-format examples in docstrings/prompts).

Frontend:
- `pages/privacidad.astro:54,165,274` — legal placeholder text, already tracked as an operator-config gap in the 2026-07-07 launch-gap audit.
- `pages/parent/settings/family.astro:99` — false positive (`TODAS` = Spanish "ALL").

## "deprecated"/"legacy" — full grep (28 backend hits), with verdicts

Only 2 of 28 are actually debt (both covered above as findings: `schemas/__init__.py:90-96` dead exports, `BudgetSyncState` dead model). The remaining 26 are accurate, load-bearing comments describing intentional backward-compatibility behavior:
- `core/security.py:12,58` — bcrypt scheme migration + legacy 7-day token parsing.
- `core/config.py:82` — accurate `GOOGLE_CLIENT_ID` vs `GOOGLE_CLIENT_IDS` note.
- `mcp/registry.py:66,378-381`, `mcp/adapters_{shopping,notifications,jarvis,meals,tasks,calendar}.py:3`, `mcp/schemas/tasks.py:3` — provenance notes on the live MCP tool registry (`_register_legacy_tools` is a misleading name for the current live mechanism, not deprecated).
- `models/cash_transaction.py:46`, `kid_bank.py:67`, `task_assignment.py:117`, `schemas/task_assignment.py:152`, `schemas/family.py:93` — accurate nullable/back-compat column comments.
- `api/routes/users.py:362`, `rewards.py:151` — accurate tolerant-read/stable-contract comments.
- `services/pet_service.py:199,204` — `feed()`/`play()` thin wrappers delegating to `care()`, still actively called by routes + MCP adapter. Fine as-is.
- `services/usage_service.py:8` — "legacy single-shot path" is a still-supported alternate calling convention, not dead.
- `services/cash_service.py:85`, `receipt_scanner_service.py:1100,1190`, `paypal_service.py:5`, `task_assignment_service.py:1944`, `analytics_service.py:99`, `oversight_service.py:5`, `budget/transaction_service.py:43`, `budget/categorization_rule_service.py:303,310`, `budget/account_service.py:42` — accurate documentation of preserved back-compat/history, none dead.

## Ruff / migrations

- `cd backend && ruff check app` → **All checks passed** (0 violations).
- `alembic heads` → single head, `cash_tx_week_of`. Migration count is 106 files (CLAUDE.md says 102 — minor doc drift, not a code issue, folded into docs-cleanup pass).

## Dependency hygiene detail

- Backend prod deps clean of dead packages; dev/lint correctly split into `requirements-dev.txt`, excluded from prod image build.
- Local `backend/.venv` is stale/drifted (still has `anthropic`, `black`, `flake8`, `mypy`, `isort`, `factory-boy`, `python-jose` — all removed from requirements 2026-07-16). Dev-environment artifact, not a repo bug — `rm -rf .venv && pip install -r requirements-dev.txt` before trusting local `pip list` again.
- Frontend deps current to within patch/minor; no action needed.

## If I could only fix 5 things

1. Extract `register_family`'s ~300 inline lines (auth.py:81-381) into a service method — highest-complexity code in the most security-sensitive endpoint, same area as the prior audit's CRITICAL bug.
2. Give kiosk a service layer — 692 lines of route-embedded logic, largest single layering violation in the repo.
3. Genericize `recycle_bin_service.py` using its own unused `SUPPORTED_MODELS` dict; fix `empty_recycle_bin` to filter by cutoff in SQL, not Python.
4. Delete dead `TaskBase` et al. from `schemas/__init__.py:90-96`, and drop `BudgetSyncState` via migration — both cheap, unambiguous, zero-risk, close out two different incomplete past cleanups.
5. Standardize service-layer exceptions: sweep the 24 `raise HTTPException` sites over to the `app.core.exceptions` convention before Jarvis MCP tools start calling these services directly.
