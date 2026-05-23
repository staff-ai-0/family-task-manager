# Mandatory tasks vs Gigs — design

**Date:** 2026-05-22
**Author:** brainstorming session
**Status:** Draft — pending implementation plan

## Problem

Current task model awards points for every completed `task_template`, regardless of whether it's a basic daily duty (brush teeth, make bed) or a higher-effort discretionary task (learn a new skill, plan meals). This dilutes the incentive system — kids treat baseline household duties as point-earning, and there's no mechanism to reward initiative beyond the baseline.

## Goal

Re-scope the points economy so that:

1. **Mandatory tasks** (daily duties) award **zero points**. They are expected behavior, not transactions.
2. **Gigs** (discretionary, higher-effort tasks like "learn podman + writeup", "read book + discuss", "plan next 3 days meals", "help with grocery shopping") are the **only point-earning activities**.
3. Gigs are **gated**: a user cannot earn points from a gig until **all mandatory tasks due today are completed**.
4. Gigs require **parent approval** before points are credited.

## Non-goals

- Auto-unlock notifications (push/email) when mandatory completion unlocks gigs.
- Carry-over gating (overdue mandatory blocking future gigs). Today-only gating in v1.
- Photo/file proof uploads. Text proof only in v1.
- Recurring/scheduled gigs beyond what `task_templates` already supports.
- New premium/plan limits on gigs.

## Decisions (from brainstorming)

| Topic | Decision |
|-------|----------|
| Mandatory vs gig modeling | Reuse existing `task_templates.is_bonus` flag. `is_bonus=false` → mandatory. `is_bonus=true` → gig. |
| Gating trigger | All today's mandatory assignments for the user must be `COMPLETED` before any gig completion is accepted. Family timezone applies. |
| Existing data | Migration forces `points=0` on every `task_template` where `is_bonus=false`. Past `point_transactions` rows untouched. |
| Default gigs | Alembic data migration seeds a default gig pack per family. Parents can edit/disable. |
| Approval | All gigs require parent approval. User completion sets `approval_status=PENDING`; points credit on approve. |
| Enforcement | Service-layer guard (option A). Backend is source of truth. Frontend renders `is_locked` hint computed by API. |

## Data model

### `task_templates`

No new columns. Add CHECK constraint:

```sql
ALTER TABLE task_templates
  ADD CONSTRAINT chk_mandatory_zero_points
  CHECK (is_bonus = TRUE OR points = 0);
```

Pre-constraint migration step: `UPDATE task_templates SET points = 0 WHERE is_bonus = false;`

### `families` — new column

| Column | Type | Notes |
|--------|------|-------|
| `timezone` | VARCHAR(64), nullable, default `"UTC"` | IANA tz string (e.g. `America/Mexico_City`). Used to compute "today" for gig gating. |

Backfill: `UPDATE families SET timezone = 'UTC' WHERE timezone IS NULL;` Parent settings page gains a timezone selector (frontend out of scope for this spec; backend accepts the field).

### `task_assignments` — new columns

| Column | Type | Notes |
|--------|------|-------|
| `approval_status` | enum (`NONE`, `PENDING`, `APPROVED`, `REJECTED`) | Default `NONE`. Mandatory rows stay `NONE`. Gig rows go `PENDING` on user complete. |
| `proof_text` | TEXT, nullable | User-submitted writeup when completing a gig. |
| `approved_by` | UUID, FK→users.id ON DELETE SET NULL, nullable | Parent who approved/rejected. |
| `approved_at` | TIMESTAMPTZ, nullable | When parent acted. |
| `approval_notes` | TEXT, nullable | Parent's note (esp. for rejections). |

Index: `(family_id, approval_status)` for the pending-approvals queue.

### `point_transactions`

Add new enum value `TransactionType.GIG_APPROVED`. Mandatory completions create **no** `point_transaction` row.

### Default gig pack (seeded per family)

Alembic data migration inserts ~6 starter gigs per existing family (and a post-create hook for new families):

| Title | Points | Note |
|-------|--------|------|
| Learn topic + writeup (e.g. podman, git) | 30 | Long-form learning |
| Read book chapter + discuss | 20 | Reading + conversation |
| Plan next 3 days of meals | 25 | Planning task |
| Help with grocery shopping | 15 | Errand assist |
| Cook family dinner | 25 | Cooking |
| Tech-help parent (15 min) | 10 | Family IT |

All seeded with `is_bonus=true`, `is_active=true`, `assignment_type=AUTO`, `interval_days=7`, `allowed_roles=["teen","child","parent"]`.

## Service layer

### `TaskAssignmentService.complete(assignment_id, user_id, proof_text=None)`

```
load assignment + template
verify ownership + family
if not template.is_bonus:
    assignment.status = COMPLETED
    assignment.completed_at = now()
    # no point transaction
    commit; return
else:  # gig
    if await _has_pending_mandatory_today(db, user_id):
        raise ForbiddenException("Complete today's mandatory tasks first")
    if not proof_text or len(proof_text.strip()) < 1:
        raise ValidationException("Proof text required for gigs")
    assignment.status = COMPLETED
    assignment.approval_status = PENDING
    assignment.proof_text = proof_text
    # no points yet
    commit; return
```

### `_has_pending_mandatory_today(db, user_id) -> bool`

```python
user = await get_user_by_id(db, user_id)
tz = user.family.timezone or "UTC"
local_today_date = current_date_in_tz(tz)  # date object in family TZ
q = (
    select(func.count())
    .select_from(TaskAssignment)
    .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
    .where(
        TaskAssignment.assigned_to == user_id,
        TaskTemplate.is_bonus.is_(False),
        TaskAssignment.assigned_date == local_today_date,
        TaskAssignment.status != AssignmentStatus.COMPLETED,
    )
)
return (await db.scalar(q)) > 0
```

### `TaskAssignmentService.approve_gig(assignment_id, parent_id, approve, notes=None)`

```
verify parent role + family
load assignment
if assignment.approval_status != PENDING: raise 409
if approve:
    assignment.approval_status = APPROVED
    assignment.approved_by = parent_id
    assignment.approved_at = now()
    assignment.approval_notes = notes
    await PointsService.award_gig_points(...)  # new type GIG_APPROVED
else:
    assignment.approval_status = REJECTED
    assignment.approved_by = parent_id
    assignment.approved_at = now()
    assignment.approval_notes = notes
commit; return
```

### `PointsService.award_gig_points(user_id, assignment_id, points)`

Mirror of `award_points_for_task` but writes `TransactionType.GIG_APPROVED`.

### List enrichment

`TaskAssignmentService.list_assignments` adds, per row:
- `is_locked: bool` — `True` if `template.is_bonus and _has_pending_mandatory_today(user)`. Compute once per request (cache the mandatory-pending boolean per user_id).
- `approval_status: str` — passthrough.
- `proof_text: str | None` — passthrough.

## API surface

All under `/api/task-assignments/`:

| Method + path | Purpose | Auth |
|---------------|---------|------|
| `POST /{id}/complete` | Existing. Now accepts `proof_text?: str`. Returns 403 on locked gig, 422 on missing proof for gigs, 200 otherwise. | Assignee |
| `GET /pending-approvals` | List gigs in family with `approval_status=PENDING`. | Parent |
| `POST /{id}/approve` | Body: `{approve: bool, notes?: str}`. Credits points on approve. | Parent |
| `GET /` | Existing. Response rows gain `is_locked`, `approval_status`, `proof_text`. | Family member |

## Frontend

### `/tasks` (assignment list)
- Lock icon + tooltip ("Finish today's mandatory tasks to unlock gigs") on rows where `is_locked=true`. Complete button disabled.
- Approval status badge: `PENDING` (amber), `APPROVED` (green), `REJECTED` (red). Hidden for mandatory.

### Gig completion modal
- Triggered when user clicks complete on `is_bonus=true` row.
- Required textarea: "Tell us what you did / what you learned" → `proof_text`.
- On submit: POST `/complete` with `proof_text`.

### `/parent/approvals` (new page)
- Parent-only. Lists pending-approval gigs across family.
- Per row: child name, gig title, points to award, proof text (collapsible), approve button, reject button + notes input.

### Nav badge
- Parent header gains a clipboard-with-dot icon showing count of pending approvals. Same pattern as receipt-drafts.

## Tests

### Backend

`backend/tests/test_gig_gating.py`:
- Mandatory assignment incomplete today → completing a gig returns 403 "Complete today's mandatory tasks first".
- All mandatory complete → completing a gig succeeds, returns `approval_status=PENDING`, no point transaction yet.
- Completing a mandatory task creates no `point_transaction` row.
- Mandatory tasks across timezones use family timezone for the `assigned_date` match (today in family TZ).

`backend/tests/test_gig_approval.py`:
- Approve flow: pending → approved, creates `GIG_APPROVED` transaction with `template.points`, updates user balance.
- Reject flow: pending → rejected, no transaction, balance unchanged.
- Non-parent attempts approve → 403.
- Double-approve (already approved/rejected) → 409.
- Approving a non-existent or cross-family assignment → 404.

`backend/tests/test_migration_zero_mandatory.py`:
- After migration: every `task_template` with `is_bonus=false` has `points=0`.
- CHECK constraint blocks `INSERT INTO task_templates (is_bonus=false, points=10)`.
- Existing `point_transactions` rows from past completions untouched.

`backend/tests/test_default_gig_pack.py`:
- After migration: every existing family has the seeded gig templates.
- Seed is idempotent (running again does not duplicate).
- New family creation auto-seeds the same pack.

### E2E (`e2e-tests/`)

`tests/gigs.spec.ts`:
- Child user with pending mandatory tasks tries to complete a gig → sees lock icon, button disabled, attempts API → 403.
- Child completes all mandatory tasks → lock clears, gig button enables.
- Child completes gig with proof text → row shows PENDING badge.
- Parent logs in, navigates to `/parent/approvals`, sees the gig, approves → child's balance increases, badge flips to APPROVED.
- Parent rejects a different gig → no balance change, badge flips to REJECTED.

## Migration plan

1. Alembic revision `mandatory_zero_points_and_gigs`:
   - Add `families.timezone VARCHAR(64) DEFAULT 'UTC'` (NOT NULL after backfill).
   - `UPDATE task_templates SET points = 0 WHERE is_bonus = false;`
   - Add CHECK constraint `chk_mandatory_zero_points`.
   - Add columns to `task_assignments`: `approval_status`, `proof_text`, `approved_by`, `approved_at`, `approval_notes`.
   - Add index `idx_assignments_family_approval (family_id, approval_status)`.
   - Add enum value `gig_approved` to `transactiontype`.
   - Data step: seed default gig pack for every existing family.
2. Add post-create hook in `FamilyService.create_family` to seed the gig pack for new families.
3. Downgrade is destructive (drops gig templates, drops approval cols, restores any points reset). Document as one-way in prod.

## Risk + rollout

- **Existing point balances** are not modified. Users keep what they earned. Only forward earning is constrained.
- **Active child users** may be confused that mandatory tasks no longer award points. Add a one-time in-app banner explaining the change for the first login post-deploy.
- **Approval bottleneck**: if a parent is slow to approve, gigs sit unrewarded. Acceptable for v1; revisit with notifications later.
- **Gating edge case**: a family with zero mandatory tasks today (e.g. all completed before midnight, weekend with no scheduled mandatory) → `_has_pending_mandatory_today` returns false → gigs unlocked. Correct behavior.

## Out of scope (future iterations)

- Push/email notifications for pending approvals.
- Photo proof upload for gigs.
- Gig "claim" step (reserve a gig before doing it).
- Carry-over: overdue mandatory blocking new gigs.
- Plan-tier limits on gig count.
- Auto-approval based on parent trust score.
