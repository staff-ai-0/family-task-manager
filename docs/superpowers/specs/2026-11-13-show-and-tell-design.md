# Monthly show-and-tell + AI baseline photos (chore rules project 3 of 3)

Status: IMPLEMENTED on branch worktree-show-and-tell (approved: user: "just dive in, go with your recommendations") — my calls, not asked one by one.

## Intent
Once a month a parent does a chore step by step and photographs it. Those photos are the family's own standard of "done right": the AI compares a kid's proof photo against them, and can suggest how to tighten the chore. Goal: fairer, more consistent proof review (chores are graded and paid).

## Non-goals / anti-goals
- The AI never approves, grades or pays. The existing review stays ADVISORY (score + note for the parent's queue).
- No new photo pipeline for kids; no video; no auto-edit of chores from AI output (suggestions are shown, the parent applies them by hand).
- Baseline photos of the home must never leave the family: family-scoped serving, no public URL, AI use behind the existing gates.

## Design (my calls)
- **Table** `chore_baselines(id, family_id→families CASCADE, template_id→task_templates CASCADE, image_url, caption ≤120, position, created_by→users SET NULL, created_at)`. Max `MAX_BASELINES_PER_TEMPLATE = 4` per template. Joins the family-export registry.
- **Files**: `<UPLOADS_ROOT>/chore-baselines/<uuid>.<ext>` + WebP thumb (same helpers as proofs: `read_upload_capped`, `assert_allowed_type`, `make_webp_thumbnail`). Served by `GET /uploads/chore-baselines/{filename}` scoped by a `chore_baselines` row of the caller's family (404 otherwise), `?size=thumb` supported.
- **API** (parent only, family-scoped, template must belong to the family): `GET/POST /api/task-templates/{id}/baselines` (multipart `file` + optional `caption`; 409 `baseline_limit`), `DELETE …/baselines/{baseline_id}` (also deletes files). `GET /api/task-templates/baselines/status` → active `requires_proof` templates of the family: `{template_id,title,baseline_count,last_baseline_at,due}`; `due` = no baseline, or newest older than `BASELINE_STALE_DAYS = 30`.
- **Validator**: `validate_proof_photo(..., baseline_urls=())` sends up to 3 downscaled baseline images BEFORE the kid's photo with a prompt addition ("the first N images are this family's reference for the task done properly; the LAST image is the kid's proof; judge the proof against them, be lenient on angle/lighting"). Any baseline load failure degrades silently to the old behaviour. `review_chore_proof` loads the template's baselines (family-scoped). Same consent + paid-tier gates; no new ones.
- **Recommendations**: `POST /api/task-templates/{id}/baselines/recommendations` (parent, `ai_features`, `AI_LIMIT`, consent): inputs = title, description, baselines, last ≤3 proof photos with the parent's grade + notes; output `{suggestions: [≤5 short strings], ai_failed}`; STORES NOTHING; LLM failure → 200 `{suggestions: [], ai_failed: true}`. Listed in `test_ai_gating.py`.
- **Monthly nudge**: once per calendar month per family (family-local, from hour 10), a `show_and_tell` notification (ES/EN, link `/parent`) to PARENT members, only when ≥1 template is `due` and the family has AI consent + a paid plan. The notification row this month is the only dedupe (no column). Runs from the existing hourly `smart_ping_sweep` job as `PingService.run_monthly_show_and_tell`, in its own try block.
- **UI**: section "Show and tell" on `/parent/tasks/[id]/edit` (thumbs + caption, one file input WITHOUT `capture`, delete via `confirmSheet`, "Pedir ideas" button → list of suggestions); parent-hub card `ShowAndTellCard` listing due chores linking to their edit page (hidden when none due). Copy only in `frontend/src/lib/showAndTell.ts` (ES+EN). Browser reaches the API via the existing `task-templates` proxy; image GETs must reach `/uploads/chore-baselines` (builder verifies the existing uploads proxy covers it).

## Approaches considered
A) Baselines per template, fed to the existing validator (chosen: smallest, reuses gates, matches "baseline per task"). B) Free-text rubric generated once by AI from photos and stored on the template (cheaper per review but loses visual ground truth, adds stored AI text). C) Fine-tune/embeddings per chore (overkill, privacy cost).

## Constraints
family_id everywhere; no native dialogs; z-[60] sheets; `hidden` attribute on kit buttons; LLM via `app/core/llm.py` only; every LLM call gated + listed in `test_ai_gating.py`; Alembic single head (current `rules_acceptances`); new family table in export registry; copy ES+EN.

## Left to the builder
Exact prompt wording; thumbnail/serving reuse; where the status query lives; how the monthly "family-local hour" is read (reuse ping_service helpers).

## Known limits (accepted)
Deleting a template removes baseline rows by cascade but leaves files on disk (no orphan sweep); staleness is by date only; max 4 photos; suggestions are not saved.
