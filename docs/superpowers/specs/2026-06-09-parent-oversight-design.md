# Parent Oversight — Fixes + Command Center

**Date:** 2026-06-09
**Status:** Approved
**Scope:** Fix 6 broken oversight paths, then unified parent command center (per-kid summary cards + merged approval queue + goal visibility + goal-reached parent notification)

---

## Problem

Parent oversight is fragmented and partly broken:

- Two disjoint approval queues (`/parent/approvals` for task assignments, `/parent/gigs?tab=pending` for gig claims); hub badge counts only the first.
- The consequences create form 422s against the backend schema — parents cannot create consequences from the UI at all.
- Client-side gig approve/reject calls hit the frontend origin with no Astro proxy → 404.
- Expired consequences stay `active=True` forever (sweep endpoint exists, nothing calls it).
- Analytics (`gigs_completed`, PUP score inputs) count only the legacy task-assignment gig path — the new gig board is invisible.
- Parents cannot see kids' reward goals (service supports it; route blocks it), and get no signal when a kid reaches a goal.
- No single view answers "how is each kid doing right now?"

---

## Phase A — Bug Fixes

### A1. Consequences create form (422)

`frontend/src/pages/parent/consequences.astro:25-43` POSTs `{title, description, user_id, due_date}`. Backend `ConsequenceCreate` requires `applied_to_user: UUID` and `restriction_type` (required enum, no default), accepts `severity` (low/medium/high, default low) and `duration_days` (1–30); it has no `due_date` field.

**Fix (frontend only):**
- Rename form field `user_id` → `applied_to_user`.
- Drop `due_date` input; add `duration_days` number input (1–30, default 3).
- Add `restriction_type` select (screen_time / rewards / extra_tasks / allowance / activities / custom) — required.
- Add `severity` select (low / medium / high) — default low.
- POST payload: `{title, description, applied_to_user, restriction_type, severity, duration_days}`.

### A2. Consequence expiry never renders

`parent/consequences.astro:232-239` and `profile.astro` ("until" span) render `c.due_date`, but `ConsequenceResponse` has `end_date`.

**Fix:** render `c.end_date` in both files. Also show `severity` and `restriction_type` badges on the parent list (data already returned).

### A3. Missing Astro proxy for `/api/gigs/*`

`frontend/src/pages/api/` has no `gigs/` directory. Client-side fetches in `parent/gigs.astro` (approve/reject/create/edit/archive) and `gigs/index.astro` (claim) target the frontend origin and fall through middleware to 404.

**Fix:** create `frontend/src/pages/api/gigs/[...path].ts` — wildcard cookie-auth proxy, same pattern as `frontend/src/pages/api/budget/[...path].ts` (forward method, body, bearer token from cookie; stream response back).

### A4. Expired consequences never auto-resolve

`ConsequenceService.check_expired_consequences(db, family_id)` only runs via on-demand `POST /api/consequences/check-expired`.

**Fix:**
- Add `ConsequenceService.check_expired_all(db)` — single global statement: set `active=False, resolved=True, resolved_at=now()` where `active IS TRUE AND end_date < now()`. No per-family loop.
- Call it from the existing hourly `_overdue_sweep_loop` in `backend/app/main.py` (after `mark_overdue_all`), wrapped in try/except (log warning, never break the sweep).

### A5. Hub badge counts only the task queue

`parent/index.astro:23-27` badges from `GET /api/task-assignments/pending-approvals` length only.

**Fix:** badge from `GET /api/oversight/summary` → `pending_counts.total` (Phase B endpoint). Single fetch replaces the current one.

### A6. Analytics blind to the new gig board

`AnalyticsService` computes `gigs_completed` from `task_assignments` joined to `TaskTemplate.is_bonus=True` only. `gig_claims` (new board, the primary gig path since commit d42c479) are excluded from per-member stats and PUP inputs.

**Fix:** in `per_member_completion_rate`, add a grouped count of `GigClaim` where `status == APPROVED AND approved_at >= window_start`, grouped by `claimed_by`, and sum it into each member's `gigs_completed`. One extra grouped query, no N+1. Cast aggregates to `int()`.

---

## Phase B — Command Center

### B1. `RewardGoalService.get_family_goals`

New static method:

```
get_family_goals(family_id, db) -> dict[UUID, GoalProgress]
```

Single query: `select(UserRewardGoal, Reward, User).join(Reward).join(User, UserRewardGoal.user_id == User.id).where(UserRewardGoal.family_id == family_id, UserRewardGoal.achieved_at.is_(None))`. Balance from the joined `User.points` (no per-row `db.get`). Returns map keyed by `user_id` for O(1) merge into summary cards. Reuses the existing `GoalProgress` schema per entry (computed `progress_pct`, `pts_to_go`, `affordable` — same formulas as `get_active_goal`).

### B2. `OversightService` + routes

New files: `backend/app/services/oversight_service.py`, `backend/app/api/routes/oversight.py` (registered in `main.py` with prefix `/api/oversight`), `backend/app/schemas/oversight.py`.

All routes `Depends(require_parent_role)`. Multi-tenant: every query filters `family_id` from the JWT user.

**`GET /api/oversight/summary` → `OversightSummary`**

```python
class KidGoal(BaseModel):            # subset of GoalProgress for the card
    reward_title: str
    reward_icon: Optional[str] = None
    progress_pct: int
    pts_to_go: int
    affordable: bool

class KidSummary(BaseModel):
    user_id: UUID
    name: str
    role: str                        # serialized UserRole value, exactly as /api/auth/me returns it
    points: int
    gig_trust_streak: int
    auto_approve_active: bool        # streak >= settings.GIG_AUTO_APPROVE_STREAK
    goal: Optional[KidGoal] = None
    pending_approvals: int           # this kid's items across BOTH queues
    open_today: int                  # PENDING assignments dated family-local today
    active_consequences: int

class PendingCounts(BaseModel):
    tasks: int
    gig_claims: int
    total: int

class OversightSummary(BaseModel):
    members: list[KidSummary]        # CHILD/TEEN only, active only, ordered by name
    pending_counts: PendingCounts
```

Implementation — 5 queries total, zero N+1:
1. `select(User)` — family members, role in (CHILD, TEEN), `is_active`.
2. Grouped count: `TaskAssignment` where `approval_status == PENDING`, group by `assigned_to`.
3. Grouped count: `GigClaim` where `status == COMPLETED`, group by `claimed_by`.
4. Grouped count: `Consequence` where `active IS TRUE`, group by `applied_to_user`.
5. Grouped count: `TaskAssignment` where `status == PENDING AND assigned_date == family-local today` (reuse `TaskAssignmentService._family_local_today`), group by `assigned_to`.
Plus `RewardGoalService.get_family_goals` (1 query). All counts cast `int()`.

**`GET /api/oversight/pending-approvals` → `list[PendingApprovalItem]`**

```python
class PendingApprovalItem(BaseModel):
    kind: Literal["task", "gig_claim"]
    id: UUID                          # assignment_id or claim_id
    title: str
    kid_id: UUID
    kid_name: str
    points: int
    completed_at: Optional[datetime]
    proof_text: Optional[str] = None
    proof_image_url: Optional[str] = None
    ai_score: Optional[float] = None  # tasks only; gig claims have no AI validation
```

Normalizes `TaskAssignmentService.list_pending_approvals` + `GigClaimService.get_pending_approvals` into one list sorted by `completed_at` asc (nulls last). Approve/reject actions are NOT duplicated — clients keep POSTing to the existing `/api/task-assignments/{id}/approve` and `/api/gigs/claims/{id}/approve` endpoints.

### B3. Goal-reached parent fan-out

In `RewardGoalService.check_nudge`, after the kid notification succeeds (inside the same try block, before setting `nudge_sent_at`): select active parents (`User.family_id == family_id, role == PARENT, is_active`) and `NotificationService.create` per parent — type `GOAL_REACHED`, title `"🎯 {kid_name} alcanzó su meta / reached their goal"`, body names the reward, link `/parent`, `push=True`. Same per-parent fan-out pattern as `GigClaimService._notify_parents_pending`. Parent fan-out failure must not block the kid nudge nor `nudge_sent_at` (separate inner try/except).

### B4. Frontend — `/parent/index.astro` command center

Replace the static members list with per-kid summary cards fed by one `GET /api/oversight/summary` SSR fetch (replaces the current pending-approvals fetch):

- Card: name + role chip · **points** (large) · 🔥 streak with "auto-approve ON" state when `auto_approve_active` · 🎯 goal row (title + mini progress bar + pts-to-go, or "¡Meta alcanzada!" highlight when `affordable`; omit row when no goal) · chips: `pending_approvals` (amber, links `/parent/approvals`), `open_today`, `active_consequences` (red when >0, links `/parent/consequences`).
- Approvals tile badge: `pending_counts.total` (9+ cap, as today).
- Parents-only members (PARENT role) stay out of cards; member management remains in `/parent/members`.

### B5. Frontend — `/parent/approvals` unified queue

Switch data source to `GET /api/oversight/pending-approvals`. Render both kinds in one list:

- `kind == "task"`: keep current row UI (AI score chip green ≥0.7 / amber ≥0.4 / red), approve/reject POST to existing Astro proxy `/api/assignments/approve`.
- `kind == "gig_claim"`: same row layout minus AI chip, plus "Gig" tag; approve/reject POST client-side to `/api/gigs/claims/{id}/approve` through the new A3 proxy.
- Empty state unchanged. `/parent/gigs?tab=pending` stays (board management context) — no removal.

---

## Decisions

| Topic | Decision |
|-------|----------|
| Premium gating | None. Oversight ships free (retention; unknown features are ungated by default in `premium.py`) |
| Activity feed | Deferred — needs `family_id` migration on `point_transactions` + event recording for silent paths |
| Trust-streak reset control | Deferred — view-only on cards |
| i18n | `t()` keys where they exist; inline ES/EN ternaries for new strings (matches current debt pattern; see `project_i18n_debt`) |
| Approve endpoints | Reuse existing ones; oversight endpoints are read-only aggregations |
| `KidGoal` vs `GoalProgress` | Separate slim schema — cards don't need `balance`/`set_at`/`reward_id` |

## Performance & Maintainability

| Concern | Decision |
|---------|----------|
| Summary latency | 6 fixed queries regardless of family size; grouped counts, no N+1 |
| Decimal leak | `int()` cast on every aggregate (CLAUDE.md rule) |
| Route ordering | New `/api/oversight` prefix — no wildcard collisions |
| Sweep safety | `check_expired_all` wrapped in try/except inside the loop; one global UPDATE |
| Queue normalization | Single server-side normalization layer; frontend never reconciles two shapes |
| Proxy security | Gigs proxy forwards cookie-derived bearer token only; same CSRF middleware gate as budget proxy |

## Tests (`tests/test_oversight.py` + extensions)

1. `get_family_goals` returns map for kids with goals only; excludes achieved; cross-family isolated
2. Summary: correct per-kid `pending_approvals` across both queues
3. Summary: `active_consequences` and `open_today` counts correct
4. Summary: `auto_approve_active` true at streak ≥ threshold
5. Summary: excludes PARENT members and inactive kids
6. Summary: kid/teen caller → 403
7. Pending-approvals: union contains both kinds, sorted by `completed_at`
8. Pending-approvals: task rows carry `ai_score`, gig rows null
9. Pending-approvals: kid caller → 403; cross-family isolated
10. `check_expired_all` resolves only expired-active rows; leaves unexpired untouched
11. Analytics `gigs_completed` includes approved gig-board claims in window
12. `check_nudge` parent fan-out: every active parent notified; kid nudge unaffected if parent fan-out fails
13. Consequence create with new payload shape succeeds end-to-end (route test)

## Out of Scope (this iteration)

- Family activity feed / timeline
- Trust-streak reset, notification preferences, digests
- Batch approve/reject, pagination on pending queues
- Per-kid drill-down page (cards link to existing pages)
- Enforcement of non-REWARDS restriction types
