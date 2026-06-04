# Track C — tech-debt cleanup: progress

Branch `chore/cleanup` (stacked on `fix/prod-ops`).

## DONE ✓
- **C5 — cruft removal.**
  - `git rm`: `fam-app.zip` (272K committed binary), `test_assignment_types.py` (stray root
    test, unimported), `ecosystem.config.cjs` + `scripts/deploy.sh` (legacy pm2 deploy to the
    DECOMMISSIONED on-prem servers 10.1.0.91/92 — `ecosystem` was only referenced by that script).
  - Untracked `.playwright-mcp/` (40 generated page-snapshot artifacts) via `git rm --cached`,
    kept on disk; added `.playwright-mcp/` + `*.zip` to `.gitignore`.
- **C4 — account-list N+1.** `get_balances_for_all_accounts` LOOKED batched but looped
  `get_balance` per account (~3 queries each). Added a real batched primitive
  `AccountService.get_balances_for_accounts` (2 grouped queries), delegated the all-accounts
  helper to it, and wired the `GET /api/budget/accounts/` enrichment loop to it.
  Tests: `test_account_balance_batch.py` (equivalence + constant query count). 30 passed in
  the account/budget regression.
- **C6 — docs.** Added an "Additional domains" table to CLAUDE.md (Jarvis, pet, meals,
  shopping, calendar, chat/dm, kiosk, analytics, consequences/rewards/points) — previously only
  budget/task/gig were documented.

## DEFERRED — with findings (need prod verification or are higher-churn/lower-value)

### C1 — gig_claims unique-constraint drift (DATA INTEGRITY — verify against prod before fixing)
`backend/app/models/gig.py:84` declares a FULL unique `UniqueConstraint("gig_id","claimed_by",
name="uq_gig_claim_active")`, but the model's own comment says the INTENT is a PARTIAL unique
(only one NON-rejected claim per user per gig). The creating migration
(`2026_06_01_gig_tables.py`) creates plain indexes (ix_gig_claims_*) and NO unique constraint
matching the ORM. So:
- Tests build schema from the ORM → enforce FULL unique.
- Prod's actual constraint = whatever the migration produced (appears to be NONE).
Consequence of FULL unique: a kid whose claim was REJECTED can never re-claim that gig (the
rejected row blocks a new claim). Consequence of NO unique (prod): a gig can be double-claimed
(ties into C2).
FIX (do with prod-state verification): decide the intended semantics, then make ORM + a new
migration agree on a PARTIAL unique index `WHERE status != 'rejected'`. Do NOT change a live
prod constraint blind — first inspect prod (`\d gig_claims`).

### C2 — double-award / double-trust-streak race on gig approval
Check-then-write with no row lock / idempotency key in the gig approval + auto-approve path
(`gig_claim_service.complete` / approval). Two concurrent approvals could double-award points
and double-increment `gig_trust_streak`. FIX: `SELECT ... FOR UPDATE` on the claim (or a unique
award guard / idempotency key on PointTransaction). Hard to reproduce deterministically in a
test (needs true concurrency); pair with C1's unique work.

### C3 — dev/lint tooling + vuln-prone pins in the prod image
`backend/requirements.txt` mixes prod + dev/test/lint deps; all ship in the prod image. FIX:
split into `requirements.txt` (prod) + `requirements-dev.txt` (pytest, ruff, etc.), install
dev only in the test stage of the Dockerfile, and pin/upgrade known-vuln transitive deps.

### C7 — large-file splits (opportunistic)
~7 files >800 lines (task_assignment_service 1236, receipt_scanner 1126, budget/settings.astro
1117, etc.). Split when next touched; not a standalone task.

## Local-only (NOT deleted — flagged for the user)
- `actual/` — **583MB** untracked vendored Actual-Budget repo. Already gitignored (out of the
  repo). Decommissioned (budget is native Postgres now) and re-clonable from upstream. Left on
  disk — run `rm -rf actual/` locally to reclaim the space if you don't need it.
- `web-stack/` — a tracked 301K Astro "design handoff" folder (brand tokens/components),
  unreferenced by any build. Looks like a one-time handoff; left in place (recoverable from git
  history if you later `git rm` it). Say the word and I'll remove it.
