# Economy Loop — Wishlist Goals, Affordability & Redemption Nudges

**Date:** 2026-06-09  
**Status:** Approved  
**Scope:** Kid/teen reward goal selection, progress tracking, push nudge on threshold, dashboard goal widget  

---

## Problem

Kids earn points but have no persistent target to work toward. The reward catalog exists, but there is no "save toward X" moment. Without a named goal, points feel abstract and motivation drops between task completions. The north-star metric for this project is: *"kid sees effort become real pesos toward a named goal."* This feature closes that gap.

---

## Approach

Dedicated `user_reward_goals` table owned by a new `RewardGoalService`. One active goal per kid enforced at the DB level via a partial unique index. Push + in-app nudge fires once when balance crosses the goal threshold. Dashboard surfaces goal widget. Existing redemption path marks goal achieved.

Alternatives rejected:
- **FK on User model** — conflates identity with economy state, no history, pollutes user serialization.
- **Multi-goal allocations** — diffuses motivation, YAGNI for v1.

---

## Data Layer

### New table: `user_reward_goals`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK, default gen_random_uuid() |
| `user_id` | UUID | FK → users.id NOT NULL |
| `family_id` | UUID | FK → families.id NOT NULL |
| `reward_id` | UUID | FK → rewards.id NOT NULL |
| `set_at` | TIMESTAMP | NOT NULL, default now() |
| `achieved_at` | TIMESTAMP | nullable — set on redemption |
| `nudge_sent_at` | TIMESTAMP | nullable — set when GOAL_REACHED push fires; reset on goal change |

**Partial unique index:** `UNIQUE (user_id) WHERE achieved_at IS NULL`  
Enforces one active goal per kid at the DB level. Completed goals (achieved_at non-null) accumulate as history without constraint conflicts.

**Cascade:** ON DELETE CASCADE on user_id and reward_id FKs (goal disappears if user or reward is deleted).

### Alembic migration

Single migration: `add_user_reward_goals`  
File: `backend/alembic/versions/<hash>_add_user_reward_goals.py`

---

## Backend

### Service: `backend/app/services/reward_goal_service.py`

Single-responsibility service. All methods accept `db: AsyncSession`.

```
get_active_goal(user_id, family_id) → GoalWithProgress | None
    One indexed lookup (partial unique). JOINs reward row.
    Fetches user's current point balance via SUM(PointTransaction.points) WHERE user_id.
    Returns: {goal, reward, balance, progress_pct, pts_to_go, affordable}

set_goal(user_id, family_id, reward_id)
    Validates reward belongs to family and is active.
    Implementation: DELETE existing active row (achieved_at IS NULL) + INSERT new row
    (SQLAlchemy async lacks native partial-index conflict target support; explicit
    delete+insert inside one transaction is equivalent and clearer).
    Resets nudge_sent_at to NULL (new goal = new nudge eligibility).

clear_goal(user_id, family_id)
    Deletes active row (achieved_at IS NULL).

mark_achieved(user_id, reward_id, db)
    Sets achieved_at = now() on matching active row.
    Called inside RewardService.redeem() transaction — no double-write risk.
    No-op if no matching active goal (user redeemed without a goal set).

check_nudge(user_id, family_id, new_balance, db)
    Called by PointsService after any balance increase.
    If new_balance >= goal.points_required AND nudge_sent_at IS NULL:
        → emit GOAL_REACHED in-app notification
        → fire push to kid's device subscriptions
        → set nudge_sent_at = now()
    Prevents repeated fires on rapid point gains.
```

### New routes (extend `backend/app/api/routes/rewards.py`)

```
GET    /api/rewards/goal    roles: CHILD, TEEN
PUT    /api/rewards/goal    roles: CHILD, TEEN    body: {reward_id: UUID}
DELETE /api/rewards/goal    roles: CHILD, TEEN
```

Parent cannot set or view child's goal through these endpoints (parent sees goals via analytics, future scope).

### Notification type

Add `GOAL_REACHED = "goal_reached"` to `NotificationType` enum in `backend/app/models/notification.py`.

Push payload:
```json
{
  "title": "¡Meta alcanzada! / Goal reached!",
  "body": "Tienes suficiente para [reward.title]. / You have enough for [reward.title].",
  "url": "/rewards",
  "tag": "goal-reached"
}
```

### Integration points

- `PointsService.award_points()` — call `check_nudge()` after balance commit
- `RewardService.redeem()` — call `mark_achieved()` inside existing transaction
- Both calls wrapped in try/except: exceptions log at WARNING level, never propagate — primary operation (award points, redeem) must not fail due to nudge/goal machinery

---

## Frontend

### `/rewards` page (kids/teens)

- Each reward card: "Set as Goal" button (CHILD/TEEN only, hidden for PARENT)
- Active goal card: colored ring border + "Tu Meta / Your Goal" badge
- Active goal card progress bar: `pts_earned / pts_required` with `X pts to go` label
- Non-goal cards: generic "X pts to go" label only (no progress bar, keeps visual hierarchy)
- `affordable=true` on active goal: replace "Set as Goal" with "¡Canjear ahora! / Redeem now! →" CTA
- `affordable=true` on non-goal cards: show "Puedes canjearlo / You can redeem this" chip

### Dashboard goal widget (kids/teens only)

Rendered below points balance. Three states:

**State 1 — Goal set, not yet affordable:**
```
🎯  Tu Meta / Your Goal
[icon] [reward.title]
████████░░░░  320 / 500 pts
180 pts to go
```

**State 2 — Goal affordable (balance ≥ cost):**
```
🎉  ¡Meta alcanzada! / Goal reached!
[icon] [reward.title]
¡Canjear ahora! / Redeem now! →   (links to /rewards)
```

**State 3 — No goal set:**
```
Elige una meta →   (soft link to /rewards, muted styling)
```

Widget fetches `GET /api/rewards/goal` on page load. Single request, no polling.

### Affordability banner

When State 2 is active on dashboard load, a dismissible top-of-page banner also appears (same session, not persisted — re-shows on next load if still affordable and not yet redeemed).

---

## Performance & Maintainability

| Concern | Decision |
|---------|----------|
| Dashboard load latency | `get_active_goal` = one indexed lookup (partial unique index = O(1)) |
| Push spam | `nudge_sent_at` column — fires exactly once per goal until goal changes |
| Multi-tenancy | `family_id` on goal table — consistent with every other model |
| Redemption atomicity | `mark_achieved` inside existing `RewardService.redeem()` transaction |
| N+1 | `get_active_goal` JOINs reward in one query |
| Cascade cleanup | FK ON DELETE CASCADE — no orphan goals if user/reward deleted |
| Rollback safety | `nudge_sent_at` reset on goal change — no permanent nudge suppression |

---

## Tests (`tests/test_reward_goals.py`)

1. Set goal — active row created, `nudge_sent_at` is null
2. Replace goal — only one active row remains (partial unique holds)
3. Clear goal — active row deleted
4. `get_active_goal` — returns correct `pts_to_go`, `progress_pct`, `affordable`
5. `check_nudge` — fires `GOAL_REACHED` notification when balance crosses threshold
6. `check_nudge` — does NOT re-fire on second call (nudge_sent_at set)
7. `check_nudge` — re-fires after goal replaced (nudge_sent_at reset)
8. `mark_achieved` — sets `achieved_at`; new goal can be set immediately after
9. `mark_achieved` — no-op when no active goal (no crash)

---

## Out of Scope (v1)

- Parent visibility into child's goal (future: analytics page)
- Multiple simultaneous goals
- Goal sharing / family goal board
- Auto-suggest goals based on point velocity
