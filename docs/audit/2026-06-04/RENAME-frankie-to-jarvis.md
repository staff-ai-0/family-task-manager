# Rename: Frankie → Jarvis (AI assistant)

User directive (2026-06-04): "wipe out any frankie ai ref, is jarvis now"

## Full scope (grep'd 2026-06-04)

### Backend code (10 files)
- `backend/app/api/routes/frankie.py` → jarvis.py
- `backend/app/api/routes/frankie_schedules.py` → jarvis_schedules.py
- `backend/app/models/frankie_schedule.py` → jarvis_schedule.py (class `FrankieSchedule`→`JarvisSchedule`)
- `backend/app/models/frankie_message.py` → jarvis_message.py (class `FrankieMessage`→`JarvisMessage`)
- `backend/app/services/frankie_service.py` → jarvis_service.py
- `backend/app/services/frankie_schedule_service.py` → jarvis_schedule_service.py
- `backend/app/services/frankie_tools.py` → jarvis_tools.py
- `backend/app/main.py` — router include + prefix `/api/frankie`
- `backend/app/core/config.py` — any FRANKIE_* env vars
- `backend/app/models/__init__.py` — imports/exports

### Frontend (6 files)
- `frontend/src/components/BottomNav.astro` — nav label + link
- `frontend/src/pages/api/frankie/[...path].ts` → api/jarvis/[...path].ts (SSR proxy)
- `frontend/src/pages/parent/frankie.astro` → jarvis.astro
- `frontend/src/pages/parent/frankie-schedules.astro` → jarvis-schedules.astro
- `frontend/src/pages/parent/index.astro` — link/label
- `frontend/src/pages/parent/settings/index.astro` — link/label

### Tests (3 files)
- `backend/tests/test_frankie_sse.py` → test_jarvis_sse.py
- `backend/tests/test_frankie_tools.py` → test_jarvis_tools.py
- `backend/tests/test_w9_features.py` — refs only

### DB (RISK — live prod) — needs alembic migration
- table `frankie_messages` → `jarvis_messages`
- table `frankie_schedules` → `jarvis_schedules`
- constraint `chk_frankie_role` → `chk_jarvis_role`
- constraint `chk_frankie_channel` → `chk_jarvis_channel`
- Source migrations (do NOT edit history; add NEW migration): 2026_05_25_frankie_schedules.py, 2026_05_25_frankie_chat.py
- Postgres `ALTER TABLE ... RENAME` is metadata-only → fast, data-preserving. Safe.

### API surface change (RISK — clients)
- `/api/frankie/*` → `/api/jarvis/*`. If native iOS/Android calls this, URL break.
  Frankie is parent-facing web AI assistant; mobile usage unknown.

## Decisions — ANSWERED 2026-06-04
1. DB tables: **FULL rename** via alembic migration (user chose). Done.
2. API route: **clean break** /api/frankie→/api/jarvis, no alias (user chose). Done.

## STATUS: COMPLETE (code) — verified, NOT yet committed/deployed
Branch: `rename/frankie-to-jarvis`
- 14 files git-renamed (history preserved), content rewritten (Frankie/frankie/FRANKIE → Jarvis/jarvis/JARVIS)
- New migration `backend/migrations/versions/2026_06_04_jarvis_rename.py` (rev `jarvis_rename_v1`, down `gig_tables`)
- Verified: `py_compile` all changed py ✓ · `alembic heads`=1 ✓ · `alembic upgrade gig_tables:jarvis_rename_v1 --sql` renders correct ALTER RENAME SQL ✓ · `git grep frankie` clean (only migration-history + audit-docs remain) ✓
- DB objects renamed: tables frankie_messages→jarvis_messages, frankie_schedules→jarvis_schedules; indexes ix_frankie_*→ix_jarvis_*; constraints chk_frankie_role→chk_jarvis_role, chk_frankie_channel→chk_jarvis_channel
- Display strings confirmed natural ("🤖 Jarvis", "Ask Jarvis something", es/en)

NOT done (deferred, needs running env): pytest suite, npm build, deploy.

## DEPLOY CHECKLIST (when ready)
1. Commit branch, open PR or merge.
2. **Prod `.env`**: `grep FRANKIE_ /home/jc/family-task-manager/.env` on VM → rename any
   `FRANKIE_MODEL`/`FRANKIE_DAILY_MESSAGE_CAP` to `JARVIS_*` BEFORE redeploy (Pydantic may
   forbid/ignore unknown keys — see 03-prod-gaps.md).
3. Deploy: `./scripts/deploy-gcp.sh` runs `alembic upgrade head` → applies jarvis_rename_v1.
4. Smoke: GET /api/jarvis/... (was /api/frankie) returns 200; old /api/frankie now 404 (expected).
5. Native iOS/Android: if they call /api/frankie, they break until updated (user accepted clean break).

## Migration-history files that KEEP "frankie" (correct — do NOT touch)
- 2026_05_25_frankie_chat.py (rev frankie_v1), 2026_05_25_frankie_schedules.py (rev frankie_sch_v1)
- 2026_05_25_calendar_recurrence.py (down=frankie_sch_v1), 2026_05_25_pup_history.py (down=frankie_v1)
These record schema history; renaming their revision IDs would break the alembic chain.

## Execution plan (once confirmed)
1. New branch `rename/frankie-to-jarvis`
2. git mv files (preserve history)
3. sed/Edit identifiers: Frankie→Jarvis, frankie→jarvis, FRANKIE→JARVIS
4. New alembic migration: ALTER TABLE/constraint RENAME (head after wave3 chain — find current head)
5. Update tests, run pytest -k jarvis
6. Frontend: rename route dirs/files, update labels (check i18n.ts for "Frankie" strings)
7. Grep verify zero frankie refs remain (excl old migration history)
8. Deploy to GCP + run migration
