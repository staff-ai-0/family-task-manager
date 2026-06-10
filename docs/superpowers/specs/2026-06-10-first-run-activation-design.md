# First-Run Activation Design

## Goal

Guide a newly registered parent family to their first "economy loop running" moment: at least one child invited, one task created, one reward created, and first points awarded. Implemented as a non-blocking progressive checklist widget on the parent dashboard, complemented by empty-state CTAs on the tasks and rewards pages.

## Problem Statement

New families register and land on a blank dashboard with no guidance. There is no indication of what to do first, no progress tracking, and no celebration when the family completes setup. The result: parents abandon before the first task-reward loop starts.

**Activation definition:** family has completed all 4 onboarding steps (child invited, task created, reward created, first points awarded).

---

## Architecture

### Data Model

Add 5 boolean columns to the `families` table via Alembic migration:

| Column | Type | Default | Meaning |
|---|---|---|---|
| `onboarding_child_invited` | Boolean | False | First invitation sent or first child joined |
| `onboarding_task_created` | Boolean | False | First `TaskTemplate` created |
| `onboarding_reward_created` | Boolean | False | First `Reward` created |
| `onboarding_points_awarded` | Boolean | False | First `PointsTransaction` committed |
| `onboarding_dismissed` | Boolean | False | Parent clicked × after completion |

All columns are `NOT NULL`, `server_default='false'`. Existing families get `False` for all (no back-fill — they've already completed setup).

### OnboardingService

`backend/app/services/onboarding_service.py`

```python
class OnboardingService:
    STEPS = ["child_invited", "task_created", "reward_created", "points_awarded"]

    @staticmethod
    async def advance(family_id: UUID, step: str, db: AsyncSession) -> None:
        """Set onboarding_{step}=True. No-op if already True. Caller commits."""
        col = f"onboarding_{step}"
        await db.execute(
            update(Family)
            .where(Family.id == family_id, getattr(Family, col).is_(False))
            .values({col: True})
        )

    @staticmethod
    async def get_state(family_id: UUID, db: AsyncSession) -> "OnboardingState":
        row = await db.get(Family, family_id)
        return OnboardingState(
            child_invited=row.onboarding_child_invited,
            task_created=row.onboarding_task_created,
            reward_created=row.onboarding_reward_created,
            points_awarded=row.onboarding_points_awarded,
            dismissed=row.onboarding_dismissed,
        )

    @staticmethod
    async def dismiss(family_id: UUID, db: AsyncSession) -> None:
        await db.execute(
            update(Family).where(Family.id == family_id).values(onboarding_dismissed=True)
        )
        await db.commit()
```

**Schema** (`backend/app/schemas/onboarding.py`):
```python
class OnboardingState(BaseModel):
    child_invited: bool
    task_created: bool
    reward_created: bool
    points_awarded: bool
    dismissed: bool
    all_done: bool  # computed: all 4 step flags True

    @model_validator(mode="after")
    def compute_all_done(self):
        self.all_done = all([
            self.child_invited, self.task_created,
            self.reward_created, self.points_awarded,
        ])
        return self
```

### Hook Wiring

`advance` is called in a fire-and-forget `try/except` block (failure logs warning, never blocks the main operation). The caller's existing `db.commit()` commits the flag update along with the main record.

| File | Location | Step |
|---|---|---|
| `task_template_service.py` | After template INSERT commit | `task_created` |
| `reward_service.py` | After reward INSERT commit | `reward_created` |
| `points_service.py` | In `award_gig_points` after commit | `points_awarded` |
| `task_assignment_service.py` | In approval flow after points awarded | `points_awarded` |
| `auth_service.py` | In `register_family` after user creation | `child_invited` (registering parent creates the family, so first child is when a second member joins) |
| `auth_service.py` or family join path | When a child/teen accepts invite and joins | `child_invited` |

`child_invited` fires when the **second** member joins (i.e., the first non-founder). Specifically: in the invitation acceptance path, after a new user is added to the family.

### API Routes

Mounted at `/api/families/` (existing families router):

- `GET /api/families/onboarding` — returns `OnboardingState` (parent role required)
- `POST /api/families/onboarding/dismiss` — sets `dismissed=True`, returns 204 (parent role required)

Frontend proxy: add to `frontend/src/pages/api/families/[...path].ts` (create if it doesn't exist, following the same pattern as the budget and gigs proxies).

---

## Frontend

### Checklist Widget — `frontend/src/pages/parent/index.astro`

Fetched server-side during SSR. If `dismissed=True` or all 4 steps done + dismissed, widget is not rendered (zero client-side flash).

Widget renders above the kid cards section. Hides via `hidden` class when `dismissed=True`.

**Visual structure:**
```
┌─ Empezando / Getting Started ───────────── ×  ┐
│ ✅  Cuenta creada / Account created             │
│ ✅  Tarea creada / Task created                 │
│ ◻   Invita a un hijo/a     →  /parent/invite    │
│ ◻   Crea una recompensa    →  /rewards          │
│ ◻   Aprueba la primera tarea (automático)       │
└─────────────────────────────────────────────────┘
```

- Brand-coral background, rounded-2xl, shadow-stamp — matches existing card style
- × button only visible once `all_done=True` (all 4 steps checked)
- Clicking × POSTs `/api/families/onboarding/dismiss` then removes widget from DOM
- Each incomplete step shows a `→` arrow link to the relevant page
- Completed steps: green ✅ icon, muted text
- Bilingual ES/EN (follows existing `lang` cookie pattern)

### Empty States

Two pages get a simple empty-state banner (pure frontend, no extra API calls — checked against existing data already fetched):

**Tasks page** (`/tasks`) — when `templates.length === 0`:
```
📋  Ninguna tarea todavía / No tasks yet
    [+ Crear primera tarea / Create first task]  → opens create form
```

**Rewards page** (`/rewards`) — when `rewards.length === 0`:
```
🏆  Ninguna recompensa todavía / No rewards yet
    [+ Crear primera recompensa / Create first reward]  → opens create form
```

---

## Migration

```
revision: onboarding_columns
down_revision: wave3_custom_reports_table  (current head)
```

`op.add_column('families', ...)` × 5. All `server_default='false'`, `nullable=False`.
`op.drop_column` in `downgrade`.

---

## Testing

`backend/tests/test_onboarding.py` — 8 tests:

1. `test_advance_task_created` — create template → `task_created=True`
2. `test_advance_reward_created` — create reward → `reward_created=True`
3. `test_advance_points_awarded` — approve task → `points_awarded=True`
4. `test_advance_child_invited` — child joins family → `child_invited=True`
5. `test_advance_idempotent` — advance same step twice → no error, stays True
6. `test_get_state_all_false` — fresh family returns all False
7. `test_dismiss` — POST dismiss → `dismissed=True`, GET returns dismissed
8. `test_non_parent_forbidden` — TEEN/CHILD → 403 on both routes

---

## Out of Scope

- Email drip for incomplete onboarding (separate feature)
- In-app tour tooltips / coachmarks
- Analytics events (separate instrumentation pass)
- Back-filling existing activated families (all start at False, which is correct — they won't see the widget if they immediately create tasks after upgrade)
