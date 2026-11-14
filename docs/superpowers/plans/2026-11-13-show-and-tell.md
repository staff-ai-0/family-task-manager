# Show-and-tell baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Parent-uploaded baseline photos per chore feed the advisory AI proof review; monthly nudge; AI tips.
**Architecture:** One table + `BaselineService` + routes under task-templates; validator takes baseline URLs; hourly sweep adds a monthly nudge; Astro section + hub card.
**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, pytest (bare-metal runner), Astro 5, vitest.
**Spec:** `docs/superpowers/specs/2026-11-13-show-and-tell-design.md`

## Global Constraints
- Table `chore_baselines(id uuid pk, family_id fk families CASCADE idx, template_id fk task_templates CASCADE idx, image_url varchar(512), caption varchar(120) null, position int, created_by fk users SET NULL null, created_at timestamptz)`; `MAX_BASELINES_PER_TEMPLATE=4`, `BASELINE_STALE_DAYS=30`, `MAX_BASELINES_TO_AI=3` as named constants in `backend/app/services/baseline_service.py`. Alembic: single head, down_revision `rules_acceptances`, reversible. Join `EXPORTED_FAMILY_TABLES`.
- Every query family-scoped; parent-only (`require_parent_role`) for all baseline endpoints; 404 for another family's template.
- Files under `<UPLOADS_ROOT>/chore-baselines/`, UUID names, upload helpers as in `task_assignments.py::upload_gig_proof` (415 type, capped read, sniffed type, thumb). Serving route in `uploads.py`, 404 unless a row of the caller's family owns the URL.
- AI: LLM only via `app/core/llm.py`; advisory only (never approves/pays); gates = `has_ai_processing_consent` + `family_tier_allows("ai_features")`; recommendations endpoint also `require_feature("ai_features")` + `AI_LIMIT`, listed in `tests/test_ai_gating.py`, stores nothing.
- Frontend: copy only `frontend/src/lib/showAndTell.ts` (ES+EN); no native dialogs; `hidden` attribute; no `capture` on file input; header tones per CLAUDE.md; vitest guards green; `npm run check` 0 errors.
- Tests: backend via `bash /private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/4d8d3d34-9ff6-4b35-9867-b691487eb7e4/scratchpad/pytest.sh tests/<file> -v` (from worktree root; PG 5435 + redis running). Agents never run the full backend suite.

## Review Focus
- Family B can never list/read/delete/serve family A's baselines; template of another family → 404.
- 5th upload → 409 `baseline_limit`; non-image / oversized → 415/413; delete removes row AND files.
- Baseline missing/unreadable file → validator falls back to title-only, never raises.
- AI off (no consent / free plan): review skipped, recommendations gated, nudge not sent.
- Monthly nudge fires once per calendar month, only parents, only when ≥1 due template; second hourly tick sends nothing.

### Task 1: Baselines record, upload/list/delete API, serving, status
**Files:** Create `backend/app/models/chore_baseline.py`, `backend/app/services/baseline_service.py`, `backend/app/schemas/baseline.py`, `backend/app/api/routes/baselines.py`, `backend/migrations/versions/2026_11_13_chore_baselines.py`. Modify `models/__init__.py`, `main.py` (router; `/baselines/status` must not be shadowed by any `/{template_id}` route), `api/routes/uploads.py` (serve route), `family_export_service.py`. Test `backend/tests/test_chore_baselines.py`.
**Interfaces:** Produces `BaselineService.add(db, user, template_id, file_bytes, content_type, caption) -> ChoreBaseline`, `.list(db, family_id, template_id) -> list`, `.delete(db, family_id, template_id, baseline_id)`, `.status(db, family_id, now=None) -> list[dict{template_id,title,baseline_count,last_baseline_at,due}]`, `.urls_for_ai(db, family_id, template_id) -> list[str]` (newest first, ≤ MAX_BASELINES_TO_AI); routes `GET/POST /api/task-templates/{id}/baselines`, `DELETE /api/task-templates/{id}/baselines/{bid}`, `GET /api/task-templates/baselines/status`, `GET /uploads/chore-baselines/{filename}`.
- [ ] Failing tests for every Review Focus bullet in this task + status `due` logic (none / stale / fresh, non-proof templates excluded, inactive excluded), export-registry test, migration round-trip (follow `tests/test_migration_early_bird.py`).
- [ ] Implement; ruff clean; run new tests + export registry test + migration round-trip. Commit `feat(baselines): per-chore baseline photos + API`.

### Task 2: Validator uses baselines
**Files:** Modify `backend/app/services/task_proof_validator.py` (`validate_proof_photo(proof_image_url, task_title, task_description=None, baseline_urls: Sequence[str]=())`), `TaskAssignmentService.review_chore_proof` (pass `BaselineService.urls_for_ai`). Test `backend/tests/test_proof_baseline_review.py` (mock `app.core.llm.OpenAI`).
- [ ] Failing tests: with 2 baselines the request content has 3 image parts, proof LAST, prompt mentions reference; zero baselines → same shape as today (1 image); unreadable baseline skipped, still validates; consent/paid gates unchanged (existing tests stay green); other callers of `validate_proof_photo` (gig path) unaffected.
- [ ] Implement; run new tests + existing proof-validator/chore-proof tests; ruff. Commit `feat(baselines): AI proof review compares against baselines`.

### Task 3: AI recommendations endpoint
**Files:** New `backend/app/services/baseline_advisor.py`, modify `routes/baselines.py` (`POST /api/task-templates/{id}/baselines/recommendations`), `tests/test_ai_gating.py` (list endpoint). Test `backend/tests/test_baseline_recommendations.py`.
**Interface:** `async suggest(db, family_id, template_id) -> {suggestions:list[str] (≤5, each ≤160 chars), ai_failed:bool}`; uses baselines + last ≤3 proofs (family-scoped, with `approval_notes`, grade, `ai_validation_notes`); `max_tokens=8192`, 25 s timeout, JSON-only parse, nothing stored.
- [ ] Failing tests: parent+paid+consent → suggestions parsed & capped; LLM None/garbage → 200 `ai_failed:true`; free plan → gated like other AI endpoints; no consent → same error as other consent-gated endpoints; kid → 403; other family's template → 404; nothing written to DB.
- [ ] Implement; run tests + `test_ai_gating.py`; ruff. Commit `feat(baselines): AI tips for a chore from baselines and recent proofs`.

### Task 4: Monthly nudge
**Files:** Modify `notification_service.py` (`show_and_tell` type + ES/EN copy, add to SUPERSEDING_TYPES), `ping_service.py` (`run_monthly_show_and_tell(db, now=None) -> int`), `main.py` `_smart_ping_sweep` (own try block). Test `backend/tests/test_show_and_tell_nudge.py`.
- [ ] Failing tests per Review Focus nudge bullet + not before hour 10 family-local, not for families without consent/paid AI, other family untouched, parents only, link `/parent`.
- [ ] Implement; run tests + existing ping tests; ruff. Commit `feat(baselines): monthly show-and-tell nudge`.

### Task 5: Frontend + docs
**Files:** Create `frontend/src/lib/showAndTell.ts`, `frontend/src/components/tasks/BaselineSection.astro`, `frontend/src/components/parent/ShowAndTellCard.astro`; modify `parent/tasks/[id]/edit.astro` (mount section), `pages/parent/index.astro` (mount card), the image-serving proxy if `/uploads/chore-baselines` is not covered, `CLAUDE.md` (baselines paragraph near the Early bird row), `docs/USER_GUIDE_{EN,ES}.md` (short section), spec status → IMPLEMENTED. Test `frontend/test/showAndTell.test.ts` (copy helpers: counts, due text, error-code mapping `baseline_limit`/415/413/`ai_failed`).
- [ ] Failing vitest; implement; run full vitest, `npm run check`, `npm run build`. Commit `feat(baselines): show-and-tell UI + docs`.
