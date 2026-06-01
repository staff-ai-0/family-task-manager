# Gigs Refactor — Design Spec

**Date:** 2026-06-01  
**Status:** Approved

## Problem

Mandatory tasks and bonus gigs share `TaskTemplate` / `TaskAssignment` models via an `is_bonus` flag. Their lifecycles are fundamentally different:

| | Mandatory | Gig |
|---|---|---|
| Points | 0 | Yes (= peso amount) |
| Shuffle | Weekly | Never |
| Availability | Assigned per week | Always open until archived |
| Claim model | One per assigned user | Any kid independently |
| Approval gate | None | Parent approves each claim |

## Solution

Clean split: new `gig_offerings` + `gig_claims` tables. Existing mandatory task flow untouched. Existing `is_bonus=True` templates migrated to new table.

## Data Models

### `gig_offerings`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `family_id` | FK families | |
| `title` | str(200) | |
| `description` | Text? | |
| `points` | int | 1 pt = $1 MXN |
| `difficulty` | int 1–3 | 1=Easy 2=Medium 3=Hard |
| `category` | enum | CHORES/ERRANDS/CREATIVE/LEARNING/OUTDOOR/OTHER |
| `allowed_roles` | JSONB | null = all roles |
| `is_active` | bool | false = archived |
| `created_by` | FK users | |
| `created_at`, `updated_at` | datetime | |

### `gig_claims`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `gig_id` | FK gig_offerings CASCADE | |
| `family_id` | FK families | |
| `claimed_by` | FK users | |
| `status` | enum | CLAIMED→COMPLETED→APPROVED/REJECTED |
| `proof_text` | Text? | |
| `proof_image_url` | str? | |
| `points_awarded` | int? | snapshot at approval |
| `completed_at` | datetime? | |
| `approved_by` | FK users? | |
| `approved_at` | datetime? | |
| `approval_notes` | Text? | |
| `created_at` | datetime | = claimed_at |

**Unique constraint**: `(gig_id, claimed_by)` where `status NOT IN ('REJECTED')` — one active claim per user per gig.

### `point_transactions` change

Add nullable `gig_claim_id FK gig_claims ON DELETE SET NULL`. Used when `type = GIG_APPROVED` via new gig flow.

## API Routes — `/api/gigs`

| Method | Path | Auth | Behavior |
|--------|------|------|----------|
| GET | `/offerings` | any member | list active; enriched with `my_claim` status |
| POST | `/offerings` | parent | create |
| PUT | `/offerings/{id}` | parent | edit |
| DELETE | `/offerings/{id}` | parent | soft-deactivate |
| POST | `/offerings/{id}/claim` | non-parent | create GigClaim; 409 if active claim exists |
| POST | `/claims/{id}/complete` | claimer | submit proof; CLAIMED→COMPLETED |
| POST | `/claims/{id}/unclaim` | claimer | delete claim record; only when CLAIMED |
| GET | `/claims/my` | any member | my claims (all statuses) |
| GET | `/claims/pending-approvals` | parent | COMPLETED claims awaiting review |
| POST | `/claims/{id}/approve` | parent | `{approved, notes?}`; award points if approved |

Proof image upload reuses `POST /api/task-assignments/proof-upload`.

## Frontend

| Page | Audience | Purpose |
|------|----------|---------|
| `/gigs` | kids/teens | gig board — browse + claim |
| `/gigs/my-gigs` | kids/teens | active claims + proof submission |
| `/parent/gigs` | parent | manage offerings + approval queue |

## Mandatory Tasks Changes

- Dashboard: filter to `is_bonus=False`; show `effort_level` as colored chip (Easy/Medium/Hard)
- `/parent/tasks`: filter to `is_bonus=False`; label field "Difficulty" instead of "Effort"
- New component: `DifficultyChip.astro`

## Migration

1. Create `gig_offerings` + `gig_claims` tables
2. Add `gig_claim_id` to `point_transactions`
3. Data: copy `is_bonus=TRUE` task_templates → `gig_offerings`
4. Soft-delete migrated templates (`is_active=FALSE` in task_templates)

## Points

1 point = $1 MXN. On approval: `PointTransaction(type=GIG_APPROVED, points=gig.points, gig_claim_id=claim.id)`. Existing `TransactionType.GIG_APPROVED` enum value reused.
