# Production-Readiness Gaps (interim — appended as found)

> Auto-populated. Audit workflow w00ab6eha appends verified findings to 05.
> This file holds gaps found during direct work.

## ~~CRITICAL — Alembic migration tree broken~~ → FALSE ALARM (retracted 2026-06-04)

Initial claim: 2 heads + dangling `down_revision=f6a7b8c9d1e2`. **WRONG.**

Root cause of the false alarm: I hand-rolled a Python regex (`^revision\s*=`) to
parse the migration graph. Several migrations use the annotated style
`revision: str = "..."` / `down_revision: Union[str,None] = "..."`, which the regex
did not match → those revisions looked "missing" and their parents looked like
extra "heads".

Ground truth from the real tool (`cd backend && alembic ...`):
- `alembic heads` → exactly ONE: `jarvis_rename_v1 (head)`
- `alembic history` → 64 revisions, linear, `<base> -> ... -> jarvis_rename_v1`
- wave3 `c3d4e5f6a7b9` is mid-chain (`b2c3d4e5f6a8 -> c3d4e5f6a7b9 -> d4e5f6a7b8c1`), not a head
- `f6a7b8c9d1e2` (add_image_url_to_receipt_drafts) IS present in the tree
- One historical branchpoint `budget_phase1 -> {family_actual_budget, budget_sync_state}`
  (old decommissioned Actual Budget path) but it re-merges (heads=1). Benign.

LESSON (feed to audit verify): never parse the alembic graph by regex. Use
`alembic heads / history / branches`. The jarvis rename migration correctly sits
as the single head on top of `gig_tables`.

TODO for audit: confirm the data-integrity finder used `alembic`, not regex, before
trusting any "multiple heads" claim it returns.

---

## Real gaps found during direct work

### LOW — env-var rename ripple (Jarvis)
`config.py` field renamed `FRANKIE_MODEL`→`JARVIS_MODEL`,
`FRANKIE_DAILY_MESSAGE_CAP`→`JARVIS_DAILY_MESSAGE_CAP`. No `.env`/compose currently
sets them (defaults apply). BUT prod VM `.env` may set `FRANKIE_MODEL`. If Pydantic
Settings uses `extra="forbid"`, a leftover `FRANKIE_*` key crashes startup; if
`extra="ignore"`, the override is silently lost (falls back to claude-haiku default).
Deploy checklist: grep prod `.env` for `FRANKIE_`, rename to `JARVIS_`.

---
(more gaps appended below as audit completes)
