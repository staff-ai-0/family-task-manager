# UX-C2 Parent "Today" Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/parent` from a navigation grid into a "what needs me now" hub: review the 3 oldest items inline, see each kid's day with a capped nudge, then pay, own chores, budget glance.

**Architecture:** Server-rendered Astro page that fetches existing endpoints in parallel and renders small components (review section, kid rows, setup card, hub layout). Backend adds five fields to the oversight kid summary and one nudge endpoint; no migration. Pure logic lives in three vitest-covered libs; each component owns its own small client script.

**Tech Stack:** FastAPI + SQLAlchemy async + pytest (backend) · Astro 5 SSR + Tailwind v4 + vanilla TS scripts + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-09-28-ux-c2-parent-hub-design.md`

## Execution environment (read once)

- Worktree: `/Users/jc/dev-2026/AgentIA/family-task-manager/.claude/worktrees/ux-c2-parent-hub` (branch `feat/ux-c2-parent-hub`). Never edit the main checkout.
- Backend tests (podman is down; an ephemeral PG runs on port 5435): `bash /private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad/run-backend-tests-c2.sh tests/<file>.py -v` — the script `cd`s into the worktree backend, sets `TZ=UTC`, and uses `backend/.venv` of the main checkout. Run ONLY the files your task names; the full suite is run by the controller at the end.
- Lint: `cd backend && /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/ruff check app`
- Frontend (from the worktree's `frontend/`): `npx vitest run test/<file>.test.ts`, `npm run check` (astro check), `npm run build`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Global Constraints

- Scope is `/parent` (PARENT only) plus `/parent/approvals`' request code. Kid screens (`/dashboard`) do not change.
- No database migration. `parent_nudge` is a string on the existing `String(48)` notification `type` column.
- **No scan button anywhere on `/parent`.** CLAUDE.md: "Visible scan triggers are exactly two: the FAB's 'Escanear' mode and the drawer's 'Escanear ticket'."
- Kid pay meters never show a dollar figure — reuse C1's `payMeterView` (`frontend/src/lib/kidHome.ts`) unchanged.
- Wording: "gig" only for the cash gig board; chores/bonus tasks are "tarea"/"task".
- Nudge rules (exact): cooldown `timedelta(hours=3)` per kid shared by all parents; target must be an active TEEN/CHILD in the caller's family else **404**; nothing open → **409** `{"detail": "nothing_to_nudge"}`; cooldown → **429** `{"detail": "nudge_cooldown", "retry_after_seconds": <int>}` plus `Retry-After` header; success → **200** `{"sent": true, "open": <n>, "nudged_at": <iso>}`; link `/dashboard`.
- Nudge copy: title "⏰ Te faltan {n} tareas" / "⏰ {n} chores to go" (singular "⏰ Te falta 1 tarea" / "⏰ 1 chore to go"); body "{parent} te lo recuerda · tócalo para verlas" / "{parent} is reminding you · tap to see them" (singular body "{parent} te lo recuerda · tócala para verla" / "{parent} is reminding you · tap to see it"). `{parent}` = parent's first name.
- Every backend query filters by `family_id`.
- Review home queue: render at most **8** cards, show the first **3**; a card leaves only after a 2xx; one decision in flight per page.
- Client scripts use the project pattern: `document.addEventListener("astro:page-load", init); if (document.readyState !== "loading") init();` with an idempotency guard.
- Show/hide with the HTML `hidden` attribute (Tailwind v4 preflight: `[hidden] { display: none !important }`).
- Inline ES/EN ternaries are the accepted copy style on these pages (no new i18n keys required).
- Every new test is mutation-checked: break the line it guards, watch it fail, restore.

## Review Focus

1. **Kid whose only open work is overdue** (nothing assigned today) → the row offers "⏰ Recordar", never "✓ Listo". Pinned in Task 4 (`kidRowView` "offers a nudge when only overdue work is left").
2. **Kid whose only open items are bonus tasks** → no nudge: backend 409, row shows no button. Pinned in Task 2 (`test_only_bonus_open_is_nothing_to_nudge`) and Task 1 (bonus excluded from the counts).
3. **Kid with the default English preference** (`users.preferred_lang` defaults to `"en"`) gets English nudge copy; Spanish only when preferred. Pinned in Task 2 (`test_english_kid_gets_english_copy`).
4. **More than 8 pending items** → after the rendered cards are cleared the section says "Quedan N · Ver todas", not "Nada por revisar". Pinned in Task 3 (`advanceQueue` "reports what is left elsewhere").
5. **Server clock ahead of the browser** (`last_nudged_at` slightly in the future) → the button shows the cooldown ("hace menos de 1 h"), never "ready". Pinned in Task 4 (`kidRowView` "treats a nudge stamped in the future as just sent").

## Plan-time refinements (vs. the spec)

- Client scripts live in the components that own the markup (`ReviewSection`, `KidRow`, `SetupCard`), not in one `ParentHub` script; `ParentHub` is layout only.
- Two copy keys, `parent_nudge` and `parent_nudge_one` (singular), both of type `parent_nudge`.
- The setup card keeps the existing starter-pack link, the module chooser (only while `enabled_modules` is unset) and the "🧭 Guíame" first-task mission button (`data-mission="first-task"`, consumed by the missions script that stays in `parent/index.astro`). The optional first-gig and flyer steps are dropped, as the spec says.
- The "N/M hoy" label shows only when `required_total_today > 0`.
- The budget glance uses the **same month and the same math as the budget dashboard** (`frontend/src/pages/budget/index.astro`): month from the server clock; `budgeted` = Σ `total_budgeted` of non-income groups; `spent` = |Σ `total_activity`| of non-income groups; drafts from the existing `GET /api/budget/receipt-drafts/count` (`{count}`). Tapping through shows the same numbers.
- The `/parent` header shows "Hola, {first name}" and the date in `user.timezone` (the family timezone denormalized on `/auth/me`).

---

### Task 1: Kid summary "today" counts + last nudge (backend)

**Files:**
- Modify: `backend/app/models/notification.py` (add `PARENT_NUDGE`)
- Modify: `backend/app/schemas/oversight.py` (`KidSummary` +5 fields)
- Modify: `backend/app/services/oversight_service.py` (3 helpers + `get_summary`)
- Test: `backend/tests/test_oversight_today_fields.py` (new)

**Interfaces:**
- Produces: `NotificationType.PARENT_NUDGE = "parent_nudge"`; `KidSummary.required_total_today: int`, `required_done_today: int`, `required_open_today: int`, `overdue_count: int`, `last_nudged_at: Optional[datetime]`; `OversightService._required_today_counts(db, family_id, today, user_id=None) -> dict[UUID, tuple[int, int, int]]` (total, done, open); `OversightService._overdue_counts(db, family_id, today, user_id=None) -> dict[UUID, int]`; `OversightService._last_nudges(db, family_id, user_id=None) -> dict[UUID, datetime]`. Task 2 reuses all three helpers.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_oversight_today_fields.py`:

```python
"""KidSummary "today" counts for the parent hub (UX-C2).

The hub's per-kid row must say exactly what the kid's own home says:
required_total_today / required_done_today mirror get_daily_progress, and
overdue_count mirrors list_open_mandatory_before. Asserted as parity, so a
future change to either definition fails here instead of drifting.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.notification import Notification, NotificationType as NT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.services.oversight_service import OversightService
from app.services.task_assignment_service import TaskAssignmentService

from conftest import family_local_today


async def _template(db, family, *, bonus=False, title="Chore"):
    t = TaskTemplate(
        id=uuid4(), title=title, points=10, interval_days=1,
        assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
        family_id=family.id,
    )
    db.add(t)
    await db.commit()
    return t


async def _assign(db, family_id, template, kid, day, status, approval=ApprovalStatus.NONE):
    a = TaskAssignment(
        family_id=family_id, template_id=template.id, assigned_to=kid.id,
        status=status, approval_status=approval,
        assigned_date=day, week_of=day - timedelta(days=day.weekday()),
    )
    db.add(a)
    await db.commit()
    return a


async def _seed_mixed_day(db, family, kid):
    today = await family_local_today(db, family.id)
    chore = await _template(db, family, title="Dishes")
    bonus = await _template(db, family, bonus=True, title="Extra")
    fid = family.id
    await _assign(db, fid, chore, kid, today, AssignmentStatus.PENDING)
    await _assign(db, fid, chore, kid, today, AssignmentStatus.COMPLETED)
    await _assign(db, fid, chore, kid, today, AssignmentStatus.COMPLETED, ApprovalStatus.PENDING)
    await _assign(db, fid, chore, kid, today, AssignmentStatus.CANCELLED)
    await _assign(db, fid, bonus, kid, today, AssignmentStatus.PENDING)
    await _assign(db, fid, chore, kid, today - timedelta(days=1), AssignmentStatus.OVERDUE)
    await _assign(db, fid, chore, kid, today - timedelta(days=3), AssignmentStatus.PENDING)
    await _assign(db, fid, chore, kid, today - timedelta(days=2), AssignmentStatus.COMPLETED)
    await _assign(db, fid, bonus, kid, today - timedelta(days=1), AssignmentStatus.PENDING)
    return today


def _card(summary, kid):
    return next(m for m in summary.members if m.user_id == kid.id)


class TestTodayCounts:
    async def test_counts_match_the_kids_own_progress(
        self, db_session, test_family, test_child_user, test_teen_user,
    ):
        today = await _seed_mixed_day(db_session, test_family, test_child_user)
        summary = await OversightService.get_summary(db_session, test_family.id)
        card = _card(summary, test_child_user)
        progress = await TaskAssignmentService.get_daily_progress(
            db_session, test_child_user.id, test_family.id,
        )
        overdue = await TaskAssignmentService.list_open_mandatory_before(
            db_session, test_child_user.id, test_family.id, today,
        )
        # pending + completed + completed-awaiting-approval + cancelled (bonus excluded)
        assert card.required_total_today == progress["required_total"] == 4
        assert card.required_done_today == progress["required_completed"] == 2
        assert card.required_open_today == 1
        assert card.overdue_count == len(overdue) == 2
        teen = _card(summary, test_teen_user)
        assert (
            teen.required_total_today, teen.required_done_today,
            teen.required_open_today, teen.overdue_count,
        ) == (0, 0, 0, 0)

    async def test_today_is_the_familys_day(
        self, db_session, test_family, test_child_user,
    ):
        test_family.timezone = "Pacific/Kiritimati"  # UTC+14
        await db_session.commit()
        today = await family_local_today(db_session, test_family.id)
        chore = await _template(db_session, test_family)
        await _assign(db_session, test_family.id, chore, test_child_user, today, AssignmentStatus.PENDING)
        card = _card(await OversightService.get_summary(db_session, test_family.id), test_child_user)
        assert (card.required_total_today, card.required_open_today, card.overdue_count) == (1, 1, 0)

    async def test_other_family_rows_never_counted(
        self, db_session, test_family, test_child_user, other_family,
    ):
        today = await family_local_today(db_session, test_family.id)
        foreign = await _template(db_session, other_family)
        # Rows stamped with ANOTHER family id — the family filter must drop them.
        await _assign(db_session, other_family.id, foreign, test_child_user, today, AssignmentStatus.PENDING)
        await _assign(db_session, other_family.id, foreign, test_child_user, today - timedelta(days=1), AssignmentStatus.OVERDUE)
        db_session.add(Notification(
            family_id=other_family.id, user_id=test_child_user.id,
            type=NT.PARENT_NUDGE, title="⏰",
        ))
        await db_session.commit()
        card = _card(await OversightService.get_summary(db_session, test_family.id), test_child_user)
        assert (card.required_total_today, card.required_open_today, card.overdue_count) == (0, 0, 0)
        assert card.last_nudged_at is None

    async def test_last_nudged_at_is_the_latest_nudge(
        self, db_session, test_family, test_child_user,
    ):
        card = _card(await OversightService.get_summary(db_session, test_family.id), test_child_user)
        assert card.last_nudged_at is None
        now = datetime.now(timezone.utc)
        for ts in (now - timedelta(hours=5), now - timedelta(hours=1)):
            db_session.add(Notification(
                family_id=test_family.id, user_id=test_child_user.id,
                type=NT.PARENT_NUDGE, title="⏰", created_at=ts,
            ))
        # A newer notification of another type must not count.
        db_session.add(Notification(
            family_id=test_family.id, user_id=test_child_user.id,
            type=NT.TASK_DUE, title="x", created_at=now,
        ))
        await db_session.commit()
        card = _card(await OversightService.get_summary(db_session, test_family.id), test_child_user)
        assert card.last_nudged_at is not None
        assert abs((card.last_nudged_at - (now - timedelta(hours=1))).total_seconds()) < 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash …/scratchpad/run-backend-tests-c2.sh tests/test_oversight_today_fields.py -v`
Expected: FAIL — `AttributeError: type object 'NotificationType' has no attribute 'PARENT_NUDGE'` (collection error) or `'KidSummary' object has no attribute 'required_total_today'`.

- [ ] **Step 3: Add the notification type**

In `backend/app/models/notification.py`, directly under `GIG_PUBLISHED = "gig_published"`:

```python
    PARENT_NUDGE = "parent_nudge"
```

- [ ] **Step 4: Add the schema fields**

In `backend/app/schemas/oversight.py`, `KidSummary`, after `active_consequences: int`:

```python
    # UX-C2 parent hub. Same definitions as the kid's own home:
    # required_* mirror get_daily_progress (non-bonus rows dated family-local
    # today; cancelled rows count in the total, never as done), overdue_count
    # mirrors list_open_mandatory_before.
    required_total_today: int = 0
    required_done_today: int = 0
    required_open_today: int = 0  # status PENDING or OVERDUE
    overdue_count: int = 0
    last_nudged_at: Optional[datetime] = None
```

- [ ] **Step 5: Add the helpers and wire `get_summary`**

In `backend/app/services/oversight_service.py`:

1. Replace the module docstring's last sentence "Approve/reject actions stay on their existing endpoints; this service never mutates." with:
   "Approve/reject actions stay on their existing endpoints. The only write here is the parent → kid nudge (UX-C2), which creates one notification."
2. Imports — change `from datetime import datetime, timezone` to `from datetime import date, datetime, timezone`, add `from typing import Optional`, and add:

```python
from app.models.notification import Notification, NotificationType
from app.models.task_template import TaskTemplate
```

3. Add these static methods inside `class OversightService`, above `get_summary`:

```python
    @staticmethod
    async def _required_today_counts(
        db: AsyncSession, family_id: UUID, today: date, user_id: Optional[UUID] = None
    ) -> dict[UUID, tuple[int, int, int]]:
        """Per kid (total, done, open) over today's NON-bonus assignments — the
        set get_daily_progress counts as required_total / required_completed.
        Cancelled rows count in the total and never as done, exactly like the
        kid's own "N/M hoy"; open = PENDING or OVERDUE."""
        q = (
            select(
                TaskAssignment.assigned_to,
                func.count(),
                func.count().filter(TaskAssignment.status == AssignmentStatus.COMPLETED),
                func.count().filter(
                    TaskAssignment.status.in_(
                        [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
                    )
                ),
            )
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_date == today,
                TaskTemplate.is_bonus.is_(False),
            )
            .group_by(TaskAssignment.assigned_to)
        )
        if user_id is not None:
            q = q.where(TaskAssignment.assigned_to == user_id)
        return {
            uid: (int(total), int(done), int(open_))
            for uid, total, done, open_ in (await db.execute(q)).all()
        }

    @staticmethod
    async def _overdue_counts(
        db: AsyncSession, family_id: UUID, today: date, user_id: Optional[UUID] = None
    ) -> dict[UUID, int]:
        """Per kid count of the rows list_open_mandatory_before returns:
        non-bonus, dated before today, PENDING or OVERDUE."""
        q = (
            select(TaskAssignment.assigned_to, func.count())
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_date < today,
                TaskTemplate.is_bonus.is_(False),
                TaskAssignment.status.in_(
                    [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
                ),
            )
            .group_by(TaskAssignment.assigned_to)
        )
        if user_id is not None:
            q = q.where(TaskAssignment.assigned_to == user_id)
        return {uid: int(n) for uid, n in (await db.execute(q)).all()}

    @staticmethod
    async def _last_nudges(
        db: AsyncSession, family_id: UUID, user_id: Optional[UUID] = None
    ) -> dict[UUID, datetime]:
        """Latest parent_nudge created_at per kid."""
        q = (
            select(Notification.user_id, func.max(Notification.created_at))
            .where(
                Notification.family_id == family_id,
                Notification.type == NotificationType.PARENT_NUDGE,
                Notification.user_id.is_not(None),
            )
            .group_by(Notification.user_id)
        )
        if user_id is not None:
            q = q.where(Notification.user_id == user_id)
        return dict((await db.execute(q)).all())
```

4. In `get_summary`: change the docstring to `"""Per-kid cards + unified pending counts. Nine fixed queries, no N+1."""`. After the `open_today_counts = dict(...)` block add:

```python
        required_today = await OversightService._required_today_counts(db, family_id, today)
        overdue_counts = await OversightService._overdue_counts(db, family_id, today)
        last_nudges = await OversightService._last_nudges(db, family_id)
```

and inside the `KidSummary(...)` constructor, after `active_consequences=...,` add:

```python
                    required_total_today=required_today.get(kid.id, (0, 0, 0))[0],
                    required_done_today=required_today.get(kid.id, (0, 0, 0))[1],
                    required_open_today=required_today.get(kid.id, (0, 0, 0))[2],
                    overdue_count=int(overdue_counts.get(kid.id, 0)),
                    last_nudged_at=last_nudges.get(kid.id),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bash …/scratchpad/run-backend-tests-c2.sh tests/test_oversight_today_fields.py tests/test_oversight.py -v`
Expected: all PASS (the existing oversight tests must stay green).

- [ ] **Step 7: Mutation-check**

One at a time, confirm the named test fails, then restore: (a) remove `TaskTemplate.is_bonus.is_(False)` from `_required_today_counts` → `test_counts_match_the_kids_own_progress`; (b) change `assigned_date < today` to `<=` in `_overdue_counts` → same test; (c) remove `TaskAssignment.family_id == family_id` from `_overdue_counts` → `test_other_family_rows_never_counted`; (d) remove the `type == PARENT_NUDGE` filter → `test_last_nudged_at_is_the_latest_nudge`.

- [ ] **Step 8: Lint and commit**

```bash
cd backend && /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/ruff check app && cd ..
git add backend/app/models/notification.py backend/app/schemas/oversight.py backend/app/services/oversight_service.py backend/tests/test_oversight_today_fields.py
git commit -m "feat(oversight): per-kid today/overdue counts and last nudge on the summary

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Parent → kid nudge endpoint (backend)

**Files:**
- Modify: `backend/app/services/notification_service.py` (copy + `SUPERSEDING_TYPES`)
- Modify: `backend/app/services/oversight_service.py` (`NUDGE_COOLDOWN`, `NudgeRefused`, `nudge`)
- Modify: `backend/app/schemas/oversight.py` (`NudgeResponse`)
- Modify: `backend/app/api/routes/oversight.py` (`POST /nudge/{kid_id}`)
- Test: `backend/tests/test_parent_nudge.py` (new)

**Interfaces:**
- Consumes (Task 1): `NotificationType.PARENT_NUDGE`, `OversightService._required_today_counts`, `_overdue_counts`, `_last_nudges`.
- Produces: `NUDGE_COOLDOWN = timedelta(hours=3)`; `class NudgeRefused(Exception)` with `.reason: str` (`"nothing_to_nudge"` | `"nudge_cooldown"`) and `.retry_after_seconds: int`; `OversightService.nudge(db, family_id: UUID, parent: User, kid_id: UUID, now: datetime | None = None) -> dict` returning `{"sent": True, "open": int, "nudged_at": datetime}`; HTTP `POST /api/oversight/nudge/{kid_id}` per Global Constraints. Task 6's button calls it through the frontend proxy.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_parent_nudge.py`:

```python
"""Parent → kid nudge (UX-C2): POST /api/oversight/nudge/{kid_id}.

One push per kid per 3 h across BOTH parents, only while the kid still has
required work open (today or overdue), never across families.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.notification import Notification, NotificationType as NT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.oversight_service import NUDGE_COOLDOWN, NudgeRefused, OversightService

from conftest import family_local_today

PUSH = "app.services.push_service.PushService.send_to_user"


async def _login(client, email):
    res = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def parent_headers(client, test_parent_user):
    return await _login(client, "parent@test.com")


@pytest_asyncio.fixture
async def parent2_headers(client, test_parent_user_2):
    return await _login(client, "parent2@test.com")


@pytest_asyncio.fixture
async def child_headers(client, test_child_user):
    return await _login(client, "child@test.com")


async def _chore(db, family, kid, *, days_ago=0, bonus=False, status=AssignmentStatus.PENDING):
    today = await family_local_today(db, family.id)
    day = today - timedelta(days=days_ago)
    t = TaskTemplate(
        id=uuid4(), title="Dishes", points=10, interval_days=1,
        assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
        family_id=family.id,
    )
    db.add(t)
    await db.commit()
    a = TaskAssignment(
        family_id=family.id, template_id=t.id, assigned_to=kid.id, status=status,
        approval_status=ApprovalStatus.NONE, assigned_date=day,
        week_of=day - timedelta(days=day.weekday()),
    )
    db.add(a)
    await db.commit()
    return a


async def _nudges(db, kid_id):
    return list((await db.execute(
        select(Notification)
        .where(Notification.user_id == kid_id, Notification.type == NT.PARENT_NUDGE)
        .order_by(Notification.created_at)
    )).scalars().all())


async def _spanish(db, kid):
    kid.preferred_lang = "es"
    await db.commit()


class TestNudgeSends:
    async def test_nudge_sends_one_notification_with_push(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _spanish(db_session, test_child_user)
        await _chore(db_session, test_family, test_child_user)
        await _chore(db_session, test_family, test_child_user, days_ago=2, status=AssignmentStatus.OVERDUE)
        with patch(PUSH, new_callable=AsyncMock) as push:
            res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["sent"] is True and body["open"] == 2 and body["nudged_at"]
        rows = await _nudges(db_session, test_child_user.id)
        assert len(rows) == 1
        assert rows[0].title == "⏰ Te faltan 2 tareas"
        assert rows[0].body == "Test te lo recuerda · tócalo para verlas"
        assert rows[0].link == "/dashboard"
        push.assert_awaited_once()
        assert push.await_args.args[1] == test_child_user.id

    async def test_singular_copy(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _spanish(db_session, test_child_user)
        await _chore(db_session, test_family, test_child_user)
        with patch(PUSH, new_callable=AsyncMock):
            res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 200, res.text
        row = (await _nudges(db_session, test_child_user.id))[0]
        assert row.title == "⏰ Te falta 1 tarea"
        assert row.body == "Test te lo recuerda · tócala para verla"

    async def test_english_kid_gets_english_copy(
        self, client, db_session, parent_headers, test_family, test_teen_user,
    ):
        # preferred_lang defaults to "en"
        await _chore(db_session, test_family, test_teen_user)
        await _chore(db_session, test_family, test_teen_user)
        with patch(PUSH, new_callable=AsyncMock):
            res = await client.post(f"/api/oversight/nudge/{test_teen_user.id}", headers=parent_headers)
        assert res.status_code == 200, res.text
        row = (await _nudges(db_session, test_teen_user.id))[0]
        assert row.title == "⏰ 2 chores to go"
        assert row.body == "Test is reminding you · tap to see them"


class TestNudgeCooldown:
    async def test_second_nudge_within_3h_is_429(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user)
        with patch(PUSH, new_callable=AsyncMock):
            first = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
            second = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert first.status_code == 200
        assert second.status_code == 429
        body = second.json()
        assert body["detail"] == "nudge_cooldown"
        assert 0 < body["retry_after_seconds"] <= 3 * 3600
        assert second.headers["Retry-After"] == str(body["retry_after_seconds"])
        assert len(await _nudges(db_session, test_child_user.id)) == 1

    async def test_cooldown_is_shared_by_both_parents(
        self, client, db_session, parent_headers, parent2_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user)
        with patch(PUSH, new_callable=AsyncMock):
            first = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
            other = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent2_headers)
        assert first.status_code == 200
        assert other.status_code == 429

    async def test_after_cooldown_a_new_nudge_supersedes_the_old(
        self, db_session, test_family, test_parent_user, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user)
        with patch(PUSH, new_callable=AsyncMock):
            await OversightService.nudge(db_session, test_family.id, test_parent_user, test_child_user.id)
            almost = datetime.now(timezone.utc) + NUDGE_COOLDOWN - timedelta(minutes=1)
            with pytest.raises(NudgeRefused) as refused:
                await OversightService.nudge(
                    db_session, test_family.id, test_parent_user, test_child_user.id, now=almost,
                )
            assert refused.value.reason == "nudge_cooldown"
            assert 0 < refused.value.retry_after_seconds <= 120
            later = datetime.now(timezone.utc) + NUDGE_COOLDOWN + timedelta(minutes=1)
            result = await OversightService.nudge(
                db_session, test_family.id, test_parent_user, test_child_user.id, now=later,
            )
        assert result["sent"] is True
        rows = await _nudges(db_session, test_child_user.id)
        assert len(rows) == 2
        await db_session.refresh(rows[0])
        assert rows[0].is_read is True
        assert rows[1].is_read is False

    def test_cooldown_is_three_hours(self):
        assert NUDGE_COOLDOWN == timedelta(hours=3)


class TestNudgeRefusals:
    async def test_nothing_open_is_409(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user, status=AssignmentStatus.COMPLETED)
        res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 409
        assert res.json()["detail"] == "nothing_to_nudge"

    async def test_only_bonus_open_is_nothing_to_nudge(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user, bonus=True)
        await _chore(db_session, test_family, test_child_user, bonus=True, days_ago=1)
        res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 409

    async def test_kid_in_another_family_is_404(
        self, client, db_session, parent_headers, other_family,
    ):
        stranger = User(
            email="stranger.kid@test.com", password_hash=get_password_hash("password123"),
            name="Stranger", role=UserRole.TEEN, family_id=other_family.id, email_verified=True,
        )
        db_session.add(stranger)
        await db_session.commit()
        await _chore(db_session, other_family, stranger)
        res = await client.post(f"/api/oversight/nudge/{stranger.id}", headers=parent_headers)
        assert res.status_code == 404
        assert await _nudges(db_session, stranger.id) == []

    async def test_parent_target_is_404(
        self, client, parent_headers, test_parent_user_2,
    ):
        res = await client.post(f"/api/oversight/nudge/{test_parent_user_2.id}", headers=parent_headers)
        assert res.status_code == 404

    async def test_inactive_kid_is_404(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user)
        test_child_user.is_active = False
        await db_session.commit()
        res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 404

    async def test_unknown_id_is_404(self, client, parent_headers):
        res = await client.post(f"/api/oversight/nudge/{uuid4()}", headers=parent_headers)
        assert res.status_code == 404

    async def test_kid_caller_is_403(self, client, child_headers, test_teen_user):
        res = await client.post(f"/api/oversight/nudge/{test_teen_user.id}", headers=child_headers)
        assert res.status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash …/scratchpad/run-backend-tests-c2.sh tests/test_parent_nudge.py -v`
Expected: FAIL — `ImportError: cannot import name 'NUDGE_COOLDOWN' from 'app.services.oversight_service'`.

- [ ] **Step 3: Add the copy and the supersede entry**

In `backend/app/services/notification_service.py`:

1. Change `SUPERSEDING_TYPES = frozenset({NT.TASK_DUE, NT.TASK_ASSIGNED})` to:

```python
SUPERSEDING_TYPES = frozenset({NT.TASK_DUE, NT.TASK_ASSIGNED, NT.PARENT_NUDGE})
```

and append to the comment above it: `A parent nudge (UX-C2) supersedes the kid's older unread nudge the same way.`

2. In `_COPY`, directly after the `"gig_published": {...},` entry, add:

```python
    # ── Parent → kid nudge (UX-C2) ─────────────────────────────────
    "parent_nudge": {
        "type": NT.PARENT_NUDGE,
        "title": {"es": "⏰ Te faltan {n} tareas", "en": "⏰ {n} chores to go"},
        "body": {
            "es": "{parent} te lo recuerda · tócalo para verlas",
            "en": "{parent} is reminding you · tap to see them",
        },
    },
    "parent_nudge_one": {
        "type": NT.PARENT_NUDGE,
        "title": {"es": "⏰ Te falta 1 tarea", "en": "⏰ 1 chore to go"},
        "body": {
            "es": "{parent} te lo recuerda · tócala para verla",
            "en": "{parent} is reminding you · tap to see it",
        },
    },
```

- [ ] **Step 4: Add the response schema**

At the end of `backend/app/schemas/oversight.py`:

```python
class NudgeResponse(BaseModel):
    sent: bool
    open: int
    nudged_at: datetime
```

- [ ] **Step 5: Add the service method**

In `backend/app/services/oversight_service.py`:

1. Change `from datetime import date, datetime, timezone` to `from datetime import date, datetime, timedelta, timezone`, and add `from app.core.exceptions import NotFoundException`.
2. Below `_EPOCH = ...` add:

```python
# One nudge per kid per window, shared by every parent in the family.
NUDGE_COOLDOWN = timedelta(hours=3)


class NudgeRefused(Exception):
    """A nudge the rules refuse: "nothing_to_nudge" (409) or
    "nudge_cooldown" (429, with retry_after_seconds)."""

    def __init__(self, reason: str, retry_after_seconds: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
```

3. Add this static method at the end of `class OversightService`:

```python
    @staticmethod
    async def nudge(
        db: AsyncSession,
        family_id: UUID,
        parent: User,
        kid_id: UUID,
        now: Optional[datetime] = None,
    ) -> dict:
        """Remind a kid of their open required chores (today + overdue).

        404 for anyone who is not an active teen/child of this family (no
        cross-family existence oracle); refused when nothing is open or when
        any parent nudged this kid within NUDGE_COOLDOWN."""
        now = now or datetime.now(timezone.utc)
        kid = (
            await db.execute(
                select(User).where(
                    User.id == kid_id,
                    User.family_id == family_id,
                    User.role.in_([UserRole.CHILD, UserRole.TEEN]),
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if kid is None:
            raise NotFoundException("Member not found")

        today = await TaskAssignmentService._family_local_today(db, family_id)
        today_counts = await OversightService._required_today_counts(
            db, family_id, today, user_id=kid.id
        )
        overdue = await OversightService._overdue_counts(
            db, family_id, today, user_id=kid.id
        )
        open_n = today_counts.get(kid.id, (0, 0, 0))[2] + overdue.get(kid.id, 0)
        if open_n == 0:
            raise NudgeRefused("nothing_to_nudge")

        last = (await OversightService._last_nudges(db, family_id, user_id=kid.id)).get(kid.id)
        if last is not None and now - last < NUDGE_COOLDOWN:
            remaining = NUDGE_COOLDOWN - (now - last)
            retry = max(1, min(int(NUDGE_COOLDOWN.total_seconds()), int(remaining.total_seconds()) + 1))
            raise NudgeRefused("nudge_cooldown", retry_after_seconds=retry)

        parts = (parent.name or "").split()
        parent_first = parts[0] if parts else {"es": "Tu familia", "en": "Your family"}
        from app.services.notification_service import NotificationService

        note = await NotificationService.create_localized(
            db,
            family_id,
            "parent_nudge_one" if open_n == 1 else "parent_nudge",
            user_id=kid.id,
            params={"n": open_n, "parent": parent_first},
            link="/dashboard",
        )
        return {"sent": True, "open": open_n, "nudged_at": note.created_at}
```

- [ ] **Step 6: Add the route**

In `backend/app/api/routes/oversight.py`:

1. Replace the imports block with:

```python
"""Parent oversight: read-only aggregations for the command center, plus the
parent → kid nudge (UX-C2)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.models.user import User
from app.schemas.oversight import NudgeResponse, OversightSummary, PendingApprovalItem
from app.services.oversight_service import NudgeRefused, OversightService
```

(keep the existing first docstring line replaced by the one above; there must be only one module docstring).

2. Append:

```python
@router.post("/nudge/{kid_id}", response_model=NudgeResponse)
async def oversight_nudge(
    kid_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Remind one kid of their open chores. Parents only; 3 h cooldown per kid."""
    try:
        return await OversightService.nudge(
            db, to_uuid_required(current_user.family_id), current_user, kid_id
        )
    except NudgeRefused as refused:
        if refused.reason == "nudge_cooldown":
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "nudge_cooldown",
                    "retry_after_seconds": refused.retry_after_seconds,
                },
                headers={"Retry-After": str(refused.retry_after_seconds)},
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="nothing_to_nudge")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `bash …/scratchpad/run-backend-tests-c2.sh tests/test_parent_nudge.py tests/test_oversight_today_fields.py tests/test_oversight.py -v`
Expected: all PASS.

- [ ] **Step 8: Mutation-check**

One at a time, confirm the named test fails, then restore: (a) drop `NT.PARENT_NUDGE` from `SUPERSEDING_TYPES` → `test_after_cooldown_a_new_nudge_supersedes_the_old`; (b) replace `today_counts.get(...)[2]` with `[0]` → `test_nothing_open_is_409`; (c) remove `User.family_id == family_id` from the kid lookup → `test_kid_in_another_family_is_404`; (d) use `"parent_nudge"` for every count → `test_singular_copy`; (e) change `now - last < NUDGE_COOLDOWN` to `False` → `test_second_nudge_within_3h_is_429`.

- [ ] **Step 9: Lint and commit**

```bash
cd backend && /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/ruff check app && cd ..
git add backend/app/services/notification_service.py backend/app/services/oversight_service.py backend/app/schemas/oversight.py backend/app/api/routes/oversight.py backend/tests/test_parent_nudge.py
git commit -m "feat(oversight): parent nudge endpoint with a shared 3 h cooldown per kid

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Review queue + shared approval requests (frontend libs, approvals page)

**Files:**
- Create: `frontend/src/lib/reviewQueue.ts`
- Create: `frontend/src/lib/approvalActions.ts`
- Modify: `frontend/src/pages/parent/approvals.astro` (its `decide()` delegates to `submitDecision`)
- Test: `frontend/test/review-queue.test.ts`, `frontend/test/approval-actions.test.ts` (new)

**Interfaces:**
- Produces:
  - `type ReviewKind = "task" | "gig" | "redemption"`
  - `interface ReviewItem { kind: ReviewKind; id: string; title: string; kidName: string; when: string | null; chip: string; proofImageUrl: string | null; proofText: string | null; allowPartial: boolean }`
  - `buildReviewQueue(tasks: unknown, claims: unknown, redemptions: unknown, lang: "es" | "en"): ReviewItem[]`
  - `interface QueueState { visible: string[]; hidden: string[]; total: number }`
  - `advanceQueue(state: QueueState, decidedId: string): QueueState & { reveal: string | null; empty: boolean; remainingElsewhere: number }`
  - `type Decision = { kind: ReviewKind; id: string; approve: boolean; grade?: "full" | "partial" | "missed" | null; partialPct?: number | null; notes?: string | null }`
  - `type DecisionResult = { ok: true } | { ok: false; error: string | null }`
  - `decisionRequest(d: Decision): { url: string; body: Record<string, unknown> }`
  - `submitDecision(d: Decision, fetchImpl?: typeof fetch): Promise<DecisionResult>`
  - Task 5 imports `ReviewItem`, `QueueState`, `advanceQueue`, `Decision`, `submitDecision`; Task 7 imports `buildReviewQueue`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/test/review-queue.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { advanceQueue, buildReviewQueue } from "../src/lib/reviewQueue";

const task = (over: Record<string, unknown> = {}) => ({
    assignment_id: "t1", template_title: "Lavar platos", assigned_to_name: "Diego", points: 10,
    completed_at: "2026-09-27T20:14:00Z", proof_text: "listo", proof_image_url: "/uploads/p.jpg",
    template_gig_mode: "claim", ...over,
});
const claim = (over: Record<string, unknown> = {}) => ({
    id: "c1", gig_title: "Lavar el carro", claimer_name: "Sofia", gig_points: 120,
    completed_at: "2026-09-28T17:02:00Z", proof_text: null, proof_image_url: null, ...over,
});
const redemption = (over: Record<string, unknown> = {}) => ({
    id: "r1", reward_title: "1 h de videojuegos", user_name: "Diego", points_cost: 200,
    created_at: "2026-09-28T18:00:00Z", ...over,
});

describe("buildReviewQueue", () => {
    it("merges the three sources oldest first", () => {
        const q = buildReviewQueue([task()], [claim()], [redemption()], "es");
        expect(q.map((i) => `${i.kind}:${i.id}`)).toEqual(["task:t1", "gig:c1", "redemption:r1"]);
    });
    it("sorts across sources by time, not by source", () => {
        const q = buildReviewQueue(
            [task({ completed_at: "2026-09-28T19:00:00Z" })],
            [claim({ completed_at: "2026-09-28T09:00:00Z" })],
            [],
            "es",
        );
        expect(q.map((i) => i.id)).toEqual(["c1", "t1"]);
    });
    it("puts items without a timestamp last, keeping their order", () => {
        const q = buildReviewQueue(
            [task({ assignment_id: "a", completed_at: null }), task({ assignment_id: "b", completed_at: null })],
            [claim()],
            [],
            "es",
        );
        expect(q.map((i) => i.id)).toEqual(["c1", "a", "b"]);
    });
    it("allows partial credit only on non-collaboration tasks", () => {
        const q = buildReviewQueue(
            [task({ assignment_id: "solo" }), task({ assignment_id: "team", template_gig_mode: "collaboration" })],
            [claim()],
            [redemption()],
            "es",
        );
        const byId = Object.fromEntries(q.map((i) => [i.id, i.allowPartial]));
        expect(byId).toEqual({ solo: true, team: false, c1: false, r1: false });
    });
    it("labels chips and titles per kind", () => {
        const es = buildReviewQueue([task()], [claim()], [redemption()], "es");
        expect(es.map((i) => i.chip)).toEqual(["+10 pts", "gig $120", "200 pts"]);
        expect(es[2].title).toBe("Canjear: 1 h de videojuegos");
        const en = buildReviewQueue([], [], [redemption()], "en");
        expect(en[0].title).toBe("Redeem: 1 h de videojuegos");
    });
    it("maps names, proof and ids", () => {
        const [t] = buildReviewQueue([task()], [], [], "es");
        expect(t).toMatchObject({ kind: "task", id: "t1", kidName: "Diego", proofText: "listo", proofImageUrl: "/uploads/p.jpg" });
    });
    it("tolerates non-array inputs", () => {
        expect(buildReviewQueue(null, undefined, { detail: "x" }, "es")).toEqual([]);
    });
});

describe("advanceQueue", () => {
    it("reveals the next hidden card and decrements the total", () => {
        const next = advanceQueue({ visible: ["a", "b", "c"], hidden: ["d", "e"], total: 5 }, "b");
        expect(next).toEqual({
            visible: ["a", "c", "d"], hidden: ["e"], total: 4,
            reveal: "d", empty: false, remainingElsewhere: 0,
        });
    });
    it("reports what is left elsewhere once the rendered cards run out", () => {
        const next = advanceQueue({ visible: ["a"], hidden: [], total: 10 }, "a");
        expect(next).toMatchObject({ visible: [], total: 9, reveal: null, empty: false, remainingElsewhere: 9 });
    });
    it("is empty when the last item is decided", () => {
        const next = advanceQueue({ visible: ["a"], hidden: [], total: 1 }, "a");
        expect(next).toMatchObject({ total: 0, empty: true, remainingElsewhere: 0 });
    });
    it("ignores an id it does not know", () => {
        const state = { visible: ["a"], hidden: ["b"], total: 2 };
        expect(advanceQueue(state, "zzz")).toEqual({ ...state, reveal: null, empty: false, remainingElsewhere: 0 });
    });
});
```

Create `frontend/test/approval-actions.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import { decisionRequest, submitDecision } from "../src/lib/approvalActions";

const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("decisionRequest", () => {
    it("task full approval", () => {
        expect(decisionRequest({ kind: "task", id: "a1", approve: true, grade: "full" })).toEqual({
            url: "/api/assignments/approve",
            body: { assignment_id: "a1", approve: true, notes: null, grade: "full", partial_credit_pct: null },
        });
    });
    it("task partial carries the percent and the note", () => {
        expect(
            decisionRequest({ kind: "task", id: "a1", approve: true, grade: "partial", partialPct: 75, notes: "casi" }).body,
        ).toEqual({ assignment_id: "a1", approve: true, notes: "casi", grade: "partial", partial_credit_pct: 75 });
    });
    it("task missed", () => {
        expect(decisionRequest({ kind: "task", id: "a1", approve: false, grade: "missed" }).body).toMatchObject({
            approve: false, grade: "missed",
        });
    });
    it("task batch approval keeps grade null", () => {
        expect(decisionRequest({ kind: "task", id: "a1", approve: true }).body).toMatchObject({ grade: null, partial_credit_pct: null });
    });
    it("gig claim", () => {
        expect(decisionRequest({ kind: "gig", id: "c1", approve: false, notes: "x" })).toEqual({
            url: "/api/gigs/claims/c1/approve",
            body: { approved: false, notes: "x" },
        });
    });
    it("reward redemption approve and reject", () => {
        expect(decisionRequest({ kind: "redemption", id: "r1", approve: true })).toEqual({
            url: "/api/rewards/redemptions/r1/approve", body: { notes: null },
        });
        expect(decisionRequest({ kind: "redemption", id: "r1", approve: false }).url).toBe("/api/rewards/redemptions/r1/reject");
    });
});

describe("submitDecision", () => {
    it("posts JSON and resolves ok on 2xx", async () => {
        const f = vi.fn(async () => json(200, {}));
        expect(await submitDecision({ kind: "gig", id: "c1", approve: true }, f as unknown as typeof fetch)).toEqual({ ok: true });
        expect(f).toHaveBeenCalledWith("/api/gigs/claims/c1/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: true, notes: null }),
        });
    });
    it("surfaces detail, then message", async () => {
        const detail = vi.fn(async () => json(400, { detail: "Insufficient points. Need 200, have 50" }));
        expect(await submitDecision({ kind: "redemption", id: "r1", approve: true }, detail as unknown as typeof fetch)).toEqual({
            ok: false, error: "Insufficient points. Need 200, have 50",
        });
        const message = vi.fn(async () => json(500, { message: "boom" }));
        expect(await submitDecision({ kind: "gig", id: "c1", approve: true }, message as unknown as typeof fetch)).toEqual({ ok: false, error: "boom" });
    });
    it("drops a non-string detail (validation list)", async () => {
        const f = vi.fn(async () => json(422, { detail: [{ loc: ["body"], msg: "bad" }] }));
        expect(await submitDecision({ kind: "task", id: "a1", approve: true }, f as unknown as typeof fetch)).toEqual({ ok: false, error: null });
    });
    it("a network error is a failure without a reason", async () => {
        const f = vi.fn(async () => { throw new Error("offline"); });
        expect(await submitDecision({ kind: "task", id: "a1", approve: true }, f as unknown as typeof fetch)).toEqual({ ok: false, error: null });
    });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npx vitest run test/review-queue.test.ts test/approval-actions.test.ts`
Expected: FAIL — cannot resolve `../src/lib/reviewQueue` / `../src/lib/approvalActions`.

- [ ] **Step 3: Implement `reviewQueue.ts`**

Create `frontend/src/lib/reviewQueue.ts`:

```ts
import { parseUtcInstant } from "./datetime";

/** One pending decision on the parent home (UX-C2): a chore/bonus proof, a
 *  gig-board claim, or a reward redemption — the same three sources
 *  /parent/approvals lists. */
export type ReviewKind = "task" | "gig" | "redemption";

export interface ReviewItem {
    kind: ReviewKind;
    id: string;
    title: string;
    kidName: string;
    when: string | null;
    chip: string;
    proofImageUrl: string | null;
    proofText: string | null;
    /** Partial credit is rejected on collaboration gigs (pot conservation). */
    allowPartial: boolean;
}

const asArray = (v: unknown): any[] => (Array.isArray(v) ? v : []);

const instant = (when: string | null): number => {
    if (!when) return NaN;
    const t = parseUtcInstant(when).getTime();
    return Number.isFinite(t) ? t : NaN;
};

export function buildReviewQueue(
    tasks: unknown,
    claims: unknown,
    redemptions: unknown,
    lang: "es" | "en",
): ReviewItem[] {
    const items: ReviewItem[] = [
        ...asArray(tasks).map((r): ReviewItem => ({
            kind: "task",
            id: String(r.assignment_id),
            title: r.template_title ?? "",
            kidName: r.assigned_to_name ?? "",
            when: r.completed_at ?? null,
            chip: `+${r.points ?? 0} pts`,
            proofImageUrl: r.proof_image_url ?? null,
            proofText: r.proof_text ?? null,
            allowPartial: r.template_gig_mode !== "collaboration",
        })),
        ...asArray(claims).map((c): ReviewItem => ({
            kind: "gig",
            id: String(c.id),
            title: c.gig_title ?? "",
            kidName: c.claimer_name ?? "",
            when: c.completed_at ?? null,
            chip: `gig $${c.gig_points ?? 0}`,
            proofImageUrl: c.proof_image_url ?? null,
            proofText: c.proof_text ?? null,
            allowPartial: false,
        })),
        ...asArray(redemptions).map((r): ReviewItem => ({
            kind: "redemption",
            id: String(r.id),
            title: `${lang === "es" ? "Canjear" : "Redeem"}: ${r.reward_title ?? ""}`,
            kidName: r.user_name ?? "",
            when: r.created_at ?? null,
            chip: `${r.points_cost ?? 0} pts`,
            proofImageUrl: null,
            proofText: null,
            allowPartial: false,
        })),
    ];
    return items
        .map((item, index) => ({ item, index, t: instant(item.when) }))
        .sort((a, b) => {
            const aMissing = Number.isNaN(a.t);
            const bMissing = Number.isNaN(b.t);
            if (aMissing !== bMissing) return aMissing ? 1 : -1;
            if (!aMissing && a.t !== b.t) return a.t - b.t;
            return a.index - b.index;
        })
        .map((x) => x.item);
}

/** Ids of the rendered cards (visible + hidden) and the full pending count,
 *  which can exceed what the page rendered. */
export interface QueueState {
    visible: string[];
    hidden: string[];
    total: number;
}

export function advanceQueue(
    state: QueueState,
    decidedId: string,
): QueueState & { reveal: string | null; empty: boolean; remainingElsewhere: number } {
    const known = state.visible.includes(decidedId) || state.hidden.includes(decidedId);
    if (!known) {
        return { ...state, reveal: null, empty: state.total === 0, remainingElsewhere: 0 };
    }
    const visible = state.visible.filter((id) => id !== decidedId);
    let hidden = state.hidden.filter((id) => id !== decidedId);
    let reveal: string | null = null;
    if (visible.length < state.visible.length && hidden.length > 0) {
        reveal = hidden[0];
        hidden = hidden.slice(1);
        visible.push(reveal);
    }
    const total = Math.max(0, state.total - 1);
    const remainingElsewhere = visible.length === 0 && total > 0 ? total : 0;
    return { visible, hidden, total, reveal, empty: total === 0, remainingElsewhere };
}
```

- [ ] **Step 4: Implement `approvalActions.ts`**

Create `frontend/src/lib/approvalActions.ts`:

```ts
import type { ReviewKind } from "./reviewQueue";

/** One review decision — the request shapes /parent/approvals has always
 *  sent, shared with the parent home (UX-C2). */
export type Decision = {
    kind: ReviewKind;
    id: string;
    approve: boolean;
    grade?: "full" | "partial" | "missed" | null;
    partialPct?: number | null;
    notes?: string | null;
};

export type DecisionResult = { ok: true } | { ok: false; error: string | null };

export function decisionRequest(d: Decision): { url: string; body: Record<string, unknown> } {
    const notes = d.notes ?? null;
    if (d.kind === "gig") {
        return { url: `/api/gigs/claims/${d.id}/approve`, body: { approved: d.approve, notes } };
    }
    if (d.kind === "redemption") {
        return { url: `/api/rewards/redemptions/${d.id}/${d.approve ? "approve" : "reject"}`, body: { notes } };
    }
    return {
        url: "/api/assignments/approve",
        body: {
            assignment_id: d.id,
            approve: d.approve,
            notes,
            grade: d.grade ?? null,
            partial_credit_pct: d.partialPct ?? null,
        },
    };
}

export async function submitDecision(d: Decision, fetchImpl: typeof fetch = fetch): Promise<DecisionResult> {
    const { url, body } = decisionRequest(d);
    try {
        const r = await fetchImpl(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (r.ok) return { ok: true };
        const err = await r.json().catch(() => null);
        const reason = err && (err.detail || err.message);
        return { ok: false, error: typeof reason === "string" ? reason : null };
    } catch {
        return { ok: false, error: null };
    }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run test/review-queue.test.ts test/approval-actions.test.ts`
Expected: PASS.

- [ ] **Step 6: Point `/parent/approvals` at the shared requests**

In `frontend/src/pages/parent/approvals.astro`, inside `<script>`:

1. Add as the first line of the script block:

```ts
        import { submitDecision, type Decision } from "../../lib/approvalActions";
```

2. Replace the whole `async function decide(...) { ... }` (from `async function decide(` through the closing `}` right before `let lastError: string | null = null;`) with:

```ts
            async function decide(
                li: HTMLLIElement,
                approve: boolean,
                grade: Decision["grade"] = null,
                partialPct: number | null = null,
            ): Promise<boolean> {
                const notes = li.querySelector<HTMLTextAreaElement>("[data-notes]");
                const res = await submitDecision({
                    kind: li.dataset.kind as Decision["kind"],
                    id: li.dataset.id!,
                    approve,
                    grade,
                    partialPct,
                    notes: notes?.value.trim() || null,
                });
                if (res.ok) {
                    li.remove();
                    return true;
                }
                // Surface the backend reason (e.g. "Insufficient points.
                // Need X, have Y") instead of a blanket error.
                lastError = res.error;
                return false;
            }
```

Nothing else in the page changes (markup, batch buttons, `alert` calls stay).

- [ ] **Step 7: Type-check**

Run (from `frontend/`): `npm run check`
Expected: `0 errors`.

- [ ] **Step 8: Mutation-check**

One at a time, confirm the named test fails, then restore: (a) in `buildReviewQueue` return `items` unsorted → "sorts across sources by time"; (b) drop `aMissing !== bMissing` branch → "puts items without a timestamp last"; (c) in `advanceQueue` set `remainingElsewhere` to `0` always → "reports what is left elsewhere"; (d) in `decisionRequest` send `approve` instead of `approved` for gigs → "gig claim"; (e) return `err.detail` without the string check → "drops a non-string detail".

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/reviewQueue.ts frontend/src/lib/approvalActions.ts frontend/src/pages/parent/approvals.astro frontend/test/review-queue.test.ts frontend/test/approval-actions.test.ts
git commit -m "feat(approvals): shared review queue and decision requests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Parent hub view logic (frontend lib)

**Files:**
- Create: `frontend/src/lib/parentHub.ts`
- Test: `frontend/test/parent-hub.test.ts` (new)

**Interfaces:**
- Consumes: `payMeterView`, `PayMeter` from `frontend/src/lib/kidHome.ts` (C1, unchanged); `parseUtcInstant` from `frontend/src/lib/datetime.ts`.
- Produces:
  - `NUDGE_COOLDOWN_MS = 3 * 3600 * 1000`
  - `type NudgeState = { kind: "ready" } | { kind: "cooldown"; hoursAgo: number } | { kind: "done" } | { kind: "none" }`
  - `interface KidRowView { id: string; name: string; initial: string; doneLabel: string | null; overdueChip: string | null; meter: PayMeter; progressPct: number; goalLine: string | null; nudge: NudgeState }`
  - `kidRowView(kid: any, paycheck: any, now: Date, lang: "es" | "en"): KidRowView`
  - `nudgeLabel(state: NudgeState, lang: "es" | "en"): string | null`
  - `type BudgetGlance = { show: false } | { show: true; spentCents: number; budgetedCents: number; pct: number; over: boolean; draftsLine: string | null; draftsCount: number }`
  - `budgetGlanceView(month: any, draftsCount: number, lang: "es" | "en"): BudgetGlance`
  - `greetingDate(now: Date, lang: "es" | "en", tz: string | null | undefined): string`
  - `monthLabel(year: number, month: number, lang: "es" | "en"): string`
  - `firstName(name: unknown): string`
  - Task 6 imports `KidRowView`, `nudgeLabel`, `NUDGE_COOLDOWN_MS`; Task 7 imports the rest.

- [ ] **Step 1: Write the failing tests**

Create `frontend/test/parent-hub.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
    NUDGE_COOLDOWN_MS,
    budgetGlanceView,
    firstName,
    greetingDate,
    kidRowView,
    monthLabel,
    nudgeLabel,
} from "../src/lib/parentHub";

const NOW = new Date("2026-09-28T20:00:00Z");
const H = 3600 * 1000;
const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString();
const kid = (over: Record<string, unknown> = {}) => ({
    user_id: "k1", name: "Diego Martinez", role: "teen", points: 340, goal: null,
    required_total_today: 5, required_done_today: 2, required_open_today: 3, overdue_count: 1,
    last_nudged_at: null, ...over,
});

describe("kidRowView nudge state", () => {
    it("is ready while work is open and nobody nudged recently", () => {
        expect(kidRowView(kid(), null, NOW, "es").nudge).toEqual({ kind: "ready" });
    });
    it("cools down for 3 h after a nudge", () => {
        expect(kidRowView(kid({ last_nudged_at: ago(2 * H + 59 * 60 * 1000) }), null, NOW, "es").nudge)
            .toEqual({ kind: "cooldown", hoursAgo: 2 });
        expect(kidRowView(kid({ last_nudged_at: ago(3 * H + 60 * 1000) }), null, NOW, "es").nudge)
            .toEqual({ kind: "ready" });
    });
    it("offers a nudge when only overdue work is left", () => {
        const k = kid({ required_total_today: 0, required_done_today: 0, required_open_today: 0, overdue_count: 2 });
        expect(kidRowView(k, null, NOW, "es").nudge).toEqual({ kind: "ready" });
    });
    it("says done when today's chores are handled (a cancelled one included)", () => {
        const k = kid({ required_total_today: 4, required_done_today: 3, required_open_today: 0, overdue_count: 0 });
        expect(kidRowView(k, null, NOW, "es").nudge).toEqual({ kind: "done" });
    });
    it("shows nothing when the kid has no chores at all", () => {
        const k = kid({ required_total_today: 0, required_done_today: 0, required_open_today: 0, overdue_count: 0 });
        expect(kidRowView(k, null, NOW, "es").nudge).toEqual({ kind: "none" });
    });
    it("ignores a recent nudge once nothing is open", () => {
        const k = kid({ required_total_today: 2, required_done_today: 2, required_open_today: 0, overdue_count: 0, last_nudged_at: ago(H) });
        expect(kidRowView(k, null, NOW, "es").nudge).toEqual({ kind: "done" });
    });
    it("treats a nudge stamped in the future as just sent", () => {
        const future = new Date(NOW.getTime() + 5 * 60 * 1000).toISOString();
        expect(kidRowView(kid({ last_nudged_at: future }), null, NOW, "es").nudge).toEqual({ kind: "cooldown", hoursAgo: 0 });
    });
    it("reads naive backend timestamps as UTC", () => {
        // 2h ago in UTC, written without a zone
        expect(kidRowView(kid({ last_nudged_at: "2026-09-28T18:00:00" }), null, NOW, "es").nudge)
            .toEqual({ kind: "cooldown", hoursAgo: 2 });
    });
    it("pins the cooldown to 3 h", () => {
        expect(NUDGE_COOLDOWN_MS).toBe(3 * H);
    });
});

describe("kidRowView labels", () => {
    it("counts today and the overdue chip", () => {
        const es = kidRowView(kid(), null, NOW, "es");
        expect(es.doneLabel).toBe("2/5 hoy");
        expect(es.overdueChip).toBe("1 atrasada");
        expect(kidRowView(kid({ overdue_count: 3 }), null, NOW, "es").overdueChip).toBe("3 atrasadas");
        const en = kidRowView(kid({ overdue_count: 3 }), null, NOW, "en");
        expect(en.doneLabel).toBe("2/5 today");
        expect(en.overdueChip).toBe("3 overdue");
        expect(kidRowView(kid({ overdue_count: 0 }), null, NOW, "es").overdueChip).toBeNull();
    });
    it("hides the done label when nothing is assigned today", () => {
        const k = kid({ required_total_today: 0, required_done_today: 0, required_open_today: 0 });
        expect(kidRowView(k, null, NOW, "es").doneLabel).toBeNull();
    });
    it("uses the pay meter only in chore mode, a plain bar otherwise", () => {
        const plain = kidRowView(kid(), { mode: "flat", cap_cents: 0 }, NOW, "es");
        expect(plain.meter).toEqual({ show: false });
        expect(plain.progressPct).toBe(40);
        const paid = kidRowView(kid(), { mode: "chore_proportional", cap_cents: 25000, pct: 48, discounted_pct: 8 }, NOW, "es");
        expect(paid.meter).toMatchObject({ show: true, greenPct: 48, redPct: 8 });
    });
    it("goal line", () => {
        const goal = { reward_title: "Audífonos", progress_pct: 60, affordable: false, pts_to_go: 80 };
        expect(kidRowView(kid({ goal }), null, NOW, "es").goalLine).toBe("🎯 Audífonos · 60%");
        expect(kidRowView(kid({ goal: { ...goal, affordable: true } }), null, NOW, "es").goalLine).toBe("🎯 Audífonos · ¡lista!");
        expect(kidRowView(kid({ goal: { ...goal, affordable: true } }), null, NOW, "en").goalLine).toBe("🎯 Audífonos · ready!");
        expect(kidRowView(kid(), null, NOW, "es").goalLine).toBeNull();
    });
    it("identity", () => {
        expect(kidRowView(kid(), null, NOW, "es")).toMatchObject({ id: "k1", name: "Diego Martinez", initial: "D" });
    });
});

describe("nudgeLabel", () => {
    it("labels every state in both languages", () => {
        expect(nudgeLabel({ kind: "ready" }, "es")).toBe("⏰ Recordar");
        expect(nudgeLabel({ kind: "ready" }, "en")).toBe("⏰ Remind");
        expect(nudgeLabel({ kind: "cooldown", hoursAgo: 0 }, "es")).toBe("Enviado · hace menos de 1 h");
        expect(nudgeLabel({ kind: "cooldown", hoursAgo: 2 }, "es")).toBe("Enviado · hace 2 h");
        expect(nudgeLabel({ kind: "cooldown", hoursAgo: 0 }, "en")).toBe("Sent · under 1 h ago");
        expect(nudgeLabel({ kind: "cooldown", hoursAgo: 2 }, "en")).toBe("Sent · 2 h ago");
        expect(nudgeLabel({ kind: "done" }, "es")).toBe("✓ Listo");
        expect(nudgeLabel({ kind: "done" }, "en")).toBe("✓ Done");
        expect(nudgeLabel({ kind: "none" }, "es")).toBeNull();
    });
});

describe("budgetGlanceView", () => {
    const month = (groups: unknown[]) => ({ category_groups: groups });
    it("sums expense groups only and reads activity as spending", () => {
        const view = budgetGlanceView(month([
            { is_income: false, total_budgeted: 1200000, total_activity: -824000 },
            { is_income: true, total_budgeted: 0, total_activity: 3000000 },
        ]), 0, "es");
        expect(view).toEqual({ show: true, spentCents: 824000, budgetedCents: 1200000, pct: 69, over: false, draftsLine: null, draftsCount: 0 });
    });
    it("flags over budget and clamps the bar", () => {
        const view = budgetGlanceView(month([{ is_income: false, total_budgeted: 100, total_activity: -150 }]), 0, "es");
        expect(view).toMatchObject({ show: true, pct: 100, over: true });
    });
    it("has no percent without a budget", () => {
        const view = budgetGlanceView(month([{ is_income: false, total_budgeted: 0, total_activity: -500 }]), 0, "es");
        expect(view).toMatchObject({ show: true, spentCents: 500, pct: 0, over: false });
    });
    it("is hidden when the month is missing or empty", () => {
        expect(budgetGlanceView(null, 3, "es")).toEqual({ show: false });
        expect(budgetGlanceView(month([{ is_income: false, total_budgeted: 0, total_activity: 0 }]), 0, "es")).toEqual({ show: false });
    });
    it("drafts line", () => {
        const m = month([{ is_income: false, total_budgeted: 100, total_activity: -10 }]);
        expect(budgetGlanceView(m, 1, "es")).toMatchObject({ draftsLine: "🧾 1 ticket por revisar", draftsCount: 1 });
        expect(budgetGlanceView(m, 2, "en")).toMatchObject({ draftsLine: "🧾 2 receipts to review", draftsCount: 2 });
    });
});

describe("greetingDate / monthLabel / firstName", () => {
    it("uses the family's day", () => {
        const late = new Date("2026-09-29T03:00:00Z"); // 21:00 on the 28th in Mexico City
        const mx = greetingDate(late, "es", "America/Mexico_City");
        expect(mx.startsWith("Lunes")).toBe(true);
        expect(mx).toContain("28");
        const utc = greetingDate(late, "es", "UTC");
        expect(utc.startsWith("Martes")).toBe(true);
        expect(utc).toContain("29");
    });
    it("english and a bad timezone fall back to UTC", () => {
        const en = greetingDate(NOW, "en", "Not/AZone");
        expect(en.startsWith("Monday")).toBe(true);
        expect(en).toContain("28");
    });
    it("month label", () => {
        expect(monthLabel(2026, 9, "es")).toBe("septiembre");
        expect(monthLabel(2026, 9, "en")).toBe("September");
    });
    it("first name", () => {
        expect(firstName("Juan Carlos Martinez")).toBe("Juan");
        expect(firstName("   ")).toBe("");
        expect(firstName(null)).toBe("");
    });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run test/parent-hub.test.ts`
Expected: FAIL — cannot resolve `../src/lib/parentHub`.

- [ ] **Step 3: Implement `parentHub.ts`**

Create `frontend/src/lib/parentHub.ts`:

```ts
import { parseUtcInstant } from "./datetime";
import { payMeterView, type PayMeter } from "./kidHome";

/** Mirror of the backend's NUDGE_COOLDOWN (display only — the server decides). */
export const NUDGE_COOLDOWN_MS = 3 * 3600 * 1000;

export type NudgeState =
    | { kind: "ready" }
    | { kind: "cooldown"; hoursAgo: number }
    | { kind: "done" }
    | { kind: "none" };

export interface KidRowView {
    id: string;
    name: string;
    initial: string;
    doneLabel: string | null;
    overdueChip: string | null;
    meter: PayMeter;
    progressPct: number;
    goalLine: string | null;
    nudge: NudgeState;
}

const n = (v: unknown) => {
    const x = Math.round(Number(v));
    return Number.isFinite(x) && x > 0 ? x : 0;
};

function nudgeState(kid: any, now: Date): NudgeState {
    const total = n(kid?.required_total_today);
    const open = n(kid?.required_open_today) + n(kid?.overdue_count);
    if (open === 0) return total > 0 ? { kind: "done" } : { kind: "none" };
    if (kid?.last_nudged_at) {
        const last = parseUtcInstant(String(kid.last_nudged_at)).getTime();
        if (Number.isFinite(last)) {
            const elapsed = now.getTime() - last;
            if (elapsed < NUDGE_COOLDOWN_MS) {
                return { kind: "cooldown", hoursAgo: Math.max(0, Math.floor(elapsed / 3600000)) };
            }
        }
    }
    return { kind: "ready" };
}

export function kidRowView(kid: any, paycheck: any, now: Date, lang: "es" | "en"): KidRowView {
    const es = lang === "es";
    const name = String(kid?.name ?? "");
    const total = n(kid?.required_total_today);
    const done = n(kid?.required_done_today);
    const overdue = n(kid?.overdue_count);
    const goal = kid?.goal;
    return {
        id: String(kid?.user_id ?? ""),
        name,
        initial: (name.trim().charAt(0) || "?").toUpperCase(),
        doneLabel: total > 0 ? `${done}/${total} ${es ? "hoy" : "today"}` : null,
        overdueChip: overdue > 0 ? (es ? `${overdue} atrasada${overdue === 1 ? "" : "s"}` : `${overdue} overdue`) : null,
        meter: payMeterView(paycheck),
        progressPct: total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0,
        goalLine: goal
            ? `🎯 ${goal.reward_title} · ${goal.affordable ? (es ? "¡lista!" : "ready!") : `${n(goal.progress_pct)}%`}`
            : null,
        nudge: nudgeState(kid, now),
    };
}

export function nudgeLabel(state: NudgeState, lang: "es" | "en"): string | null {
    const es = lang === "es";
    switch (state.kind) {
        case "ready":
            return es ? "⏰ Recordar" : "⏰ Remind";
        case "cooldown":
            if (state.hoursAgo < 1) return es ? "Enviado · hace menos de 1 h" : "Sent · under 1 h ago";
            return es ? `Enviado · hace ${state.hoursAgo} h` : `Sent · ${state.hoursAgo} h ago`;
        case "done":
            return es ? "✓ Listo" : "✓ Done";
        default:
            return null;
    }
}

export type BudgetGlance =
    | { show: false }
    | {
          show: true;
          spentCents: number;
          budgetedCents: number;
          pct: number;
          over: boolean;
          draftsLine: string | null;
          draftsCount: number;
      };

/** Same math as the budget dashboard (pages/budget/index.astro): expense
 *  groups only; spent = |Σ activity|, budgeted = Σ total_budgeted. */
export function budgetGlanceView(month: any, draftsCount: number, lang: "es" | "en"): BudgetGlance {
    if (!month || !Array.isArray(month.category_groups)) return { show: false };
    const expense = month.category_groups.filter((g: any) => !g?.is_income);
    const budgetedCents = expense.reduce((s: number, g: any) => s + (Number(g?.total_budgeted) || 0), 0);
    const spentCents = Math.abs(expense.reduce((s: number, g: any) => s + (Number(g?.total_activity) || 0), 0));
    if (budgetedCents <= 0 && spentCents <= 0) return { show: false };
    const pct = budgetedCents > 0 ? Math.max(0, Math.min(100, Math.round((spentCents / budgetedCents) * 100))) : 0;
    const drafts = n(draftsCount);
    const es = lang === "es";
    return {
        show: true,
        spentCents,
        budgetedCents,
        pct,
        over: budgetedCents > 0 && spentCents > budgetedCents,
        draftsLine: drafts > 0
            ? (es ? `🧾 ${drafts} ticket${drafts === 1 ? "" : "s"} por revisar` : `🧾 ${drafts} receipt${drafts === 1 ? "" : "s"} to review`)
            : null,
        draftsCount: drafts,
    };
}

/** "Lunes 28 sep" / "Monday, Sep 28" in the family's timezone (UTC fallback). */
export function greetingDate(now: Date, lang: "es" | "en", tz: string | null | undefined): string {
    const locale = lang === "es" ? "es-MX" : "en-US";
    const make = (zone: string) =>
        new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "short", timeZone: zone });
    let fmt: Intl.DateTimeFormat;
    try {
        fmt = make(tz || "UTC");
    } catch {
        fmt = make("UTC");
    }
    const parts = fmt.formatToParts(now);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
    const weekday = get("weekday");
    const w = weekday.charAt(0).toUpperCase() + weekday.slice(1);
    const month = get("month").replace(/\.$/, "");
    return lang === "es" ? `${w} ${get("day")} ${month}` : `${w}, ${month} ${get("day")}`;
}

/** Month name for the budget glance header ("septiembre" / "September"). */
export function monthLabel(year: number, month: number, lang: "es" | "en"): string {
    return new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "en-US", { month: "long", timeZone: "UTC" }).format(
        new Date(Date.UTC(year, month - 1, 15)),
    );
}

export function firstName(name: unknown): string {
    if (typeof name !== "string") return "";
    return name.trim().split(/\s+/)[0] ?? "";
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run test/parent-hub.test.ts`
Expected: PASS.

- [ ] **Step 5: Mutation-check**

One at a time, confirm the named test fails, then restore: (a) drop `+ n(kid?.overdue_count)` from `open` → "offers a nudge when only overdue work is left"; (b) change `elapsed < NUDGE_COOLDOWN_MS` to `elapsed >= 0 && elapsed < NUDGE_COOLDOWN_MS` → "treats a nudge stamped in the future as just sent"; (c) filter `g?.is_income` instead of `!g?.is_income` → "sums expense groups only"; (d) drop the `timeZone: zone` option → "uses the family's day" (under `TZ=UTC` runs, and also check with the machine's own zone).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/parentHub.ts frontend/test/parent-hub.test.ts
git commit -m "feat(parent-hub): kid row, nudge, budget glance and greeting view logic

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Review section on the home (components + client script)

**Files:**
- Create: `frontend/src/components/home/ReviewCard.astro`
- Create: `frontend/src/components/home/ReviewSection.astro`

**Interfaces:**
- Consumes (Task 3): `ReviewItem`, `QueueState`, `advanceQueue`, `Decision`, `submitDecision`; `fmtDateTime(value, lang, tz)` from `lib/datetime`; `showToast(message, type)` from `lib/toast`; `EnablePushButton` props `{ lang, userId, class?, label? }`.
- Produces: `<ReviewSection items={ReviewItem[]} lang={"es"|"en"} tz={string|null} userId={string} />` (Task 7 renders it). Root carries `data-review-root`.

- [ ] **Step 1: Create `ReviewCard.astro`**

```astro
---
/**
 * One pending decision on the parent home (UX-C2). ✓ decides in one tap;
 * "Casi" / "No hecha" expand an inline panel (percent chips + note) with a
 * confirm button. Behavior lives in ReviewSection's script.
 */
import type { ReviewItem } from "../../lib/reviewQueue";
import { fmtDateTime } from "../../lib/datetime";

interface Props {
    item: ReviewItem;
    lang: "es" | "en";
    tz: string | null;
    hidden?: boolean;
}
const { item, lang, tz, hidden = false } = Astro.props;
const es = lang === "es";
const when = item.when ? fmtDateTime(item.when, lang, tz) : "";
const initial = (item.kidName.trim().charAt(0) || "?").toUpperCase();
const chipClass =
    item.kind === "task"
        ? "bg-violet-100 text-violet-700"
        : item.kind === "gig"
            ? "bg-emerald-100 text-emerald-700"
            : "bg-amber-100 text-amber-700";
const rejectLabel =
    item.kind === "redemption" ? (es ? "✗ Rechazar" : "✗ Reject") : (es ? "✗ No hecha" : "✗ Missed");
---

<li
    data-review-card
    data-kind={item.kind}
    data-id={item.id}
    hidden={hidden}
    class="bg-white rounded-2xl border border-brand-ink/10 p-3 shadow-[var(--shadow-card)]"
>
    <div class="flex gap-3">
        <div class="w-8 h-8 rounded-full bg-brand-cream-deep flex items-center justify-center font-bold text-sm text-brand-sky-deep shrink-0" aria-hidden="true">
            {initial}
        </div>
        <div class="flex-1 min-w-0">
            <p class="font-bold text-brand-ink text-sm leading-tight truncate">{item.title}</p>
            <p class="text-xs text-brand-ink-soft mt-0.5">
                {item.kidName}{when && ` · ${when}`}
                <span class={`ml-1 inline-block rounded-full px-1.5 py-0.5 text-[10px] font-bold ${chipClass}`}>{item.chip}</span>
            </p>
            {item.proofText && <p class="text-xs text-brand-ink mt-1 line-clamp-2">{item.proofText}</p>}
        </div>
        {item.proofImageUrl && (
            <a href={item.proofImageUrl} target="_blank" rel="noopener" class="shrink-0" aria-label={es ? "Ver foto de prueba" : "View proof photo"}>
                <img src={`${item.proofImageUrl}?size=thumb`} alt="" loading="lazy" class="w-12 h-12 rounded-lg object-cover border border-brand-ink/10" />
            </a>
        )}
    </div>
    <div class="flex gap-2 mt-3">
        <button type="button" data-review-action="reject"
            class="flex-1 rounded-xl border border-red-300 text-red-700 py-2 text-xs font-bold hover:bg-red-50 disabled:opacity-50">
            {rejectLabel}
        </button>
        {item.allowPartial && (
            <button type="button" data-review-action="partial"
                class="flex-1 rounded-xl border border-amber-400 text-amber-700 py-2 text-xs font-bold hover:bg-amber-50 disabled:opacity-50">
                {es ? "Casi" : "Almost"}
            </button>
        )}
        <button type="button" data-review-action="approve"
            class="flex-1 rounded-xl bg-emerald-600 text-white py-2 text-xs font-bold hover:bg-emerald-700 disabled:opacity-50">
            {es ? "✓ Aprobar" : "✓ Approve"}
        </button>
    </div>
    <div data-review-expand hidden class="mt-3 space-y-2">
        {item.allowPartial && (
            <div data-review-pcts hidden>
                <div class="flex items-center gap-2">
                    <span class="text-xs font-semibold text-brand-ink-soft">{es ? "Crédito:" : "Credit:"}</span>
                    {[25, 50, 75].map((pct) => (
                        <button type="button" data-pct={pct} aria-pressed={pct === 50 ? "true" : "false"}
                            class="px-3 py-1 rounded-full border border-brand-ink/20 text-xs font-bold text-brand-ink-soft aria-pressed:bg-amber-100 aria-pressed:border-amber-400 aria-pressed:text-amber-800 disabled:opacity-50">
                            {pct}%
                        </button>
                    ))}
                </div>
            </div>
        )}
        <textarea data-review-note rows="2" maxlength="500"
            class="w-full rounded-lg border border-brand-ink/20 p-2 text-sm bg-brand-cream focus:ring-2 focus:ring-amber-500 outline-none"
            placeholder={es ? "Nota para tu hijo/a (opcional)" : "Note for your kid (optional)"}></textarea>
        <button type="button" data-review-confirm
            class="w-full rounded-xl bg-brand-ink text-white py-2 text-xs font-bold hover:opacity-90 disabled:opacity-50">
            {es ? "Confirmar" : "Confirm"}
        </button>
    </div>
</li>
```

- [ ] **Step 2: Create `ReviewSection.astro`**

```astro
---
/**
 * "Por revisar" on the parent home (UX-C2): the oldest pending decisions,
 * 3 visible, up to 8 rendered; a decided card leaves only after a 2xx and
 * the next hidden one slides in. Bulk approval stays on /parent/approvals.
 */
import ReviewCard from "./ReviewCard.astro";
import EnablePushButton from "../EnablePushButton.astro";
import type { ReviewItem } from "../../lib/reviewQueue";

interface Props {
    items: ReviewItem[];
    lang: "es" | "en";
    tz: string | null;
    userId: string;
}
const { items, lang, tz, userId } = Astro.props;
const es = lang === "es";
const RENDERED = 8;
const VISIBLE = 3;
const rendered = items.slice(0, RENDERED);
const total = items.length;
---

<section data-review-root data-total={total} data-lang={lang} class="mb-6" aria-labelledby="review-heading">
    <div class="flex items-center justify-between mb-2 px-1">
        <h2 id="review-heading" class="text-xs font-extrabold uppercase tracking-wider text-brand-ink-soft">
            {es ? "Por revisar" : "To review"}<span data-review-heading-count hidden={total === 0}> · <span data-review-count>{total}</span></span>
        </h2>
        {total > 0 && (
            <a data-review-all href="/parent/approvals" class="text-xs font-semibold text-brand-sky-deep hover:underline">
                {es ? "Ver todas" : "See all"} (<span data-review-count>{total}</span>) ›
            </a>
        )}
    </div>
    <ul data-review-list class="space-y-2">
        {rendered.map((item, i) => <ReviewCard item={item} lang={lang} tz={tz} hidden={i >= VISIBLE} />)}
    </ul>
    <p data-review-empty hidden={total > 0} class="rounded-xl bg-emerald-50 text-emerald-700 text-sm font-semibold px-3 py-2">
        ✓ {es ? "Nada por revisar" : "Nothing to review"}
    </p>
    <a data-review-more hidden href="/parent/approvals"
        class="block rounded-xl border border-brand-sky-deep/30 bg-brand-sky/10 px-3 py-2 text-sm font-semibold text-brand-sky-deep">
        {es ? <>Quedan <span data-review-more-count></span></> : <><span data-review-more-count></span> left</>} · {es ? "Ver todas ›" : "See all ›"}
    </a>
    <EnablePushButton
        lang={lang}
        userId={userId}
        class="mt-2 flex items-center"
        label={es ? "🔔 Avísame cuando haya algo que revisar" : "🔔 Tell me when something needs review"}
    />
</section>

<script>
    import { submitDecision, type Decision } from "../../lib/approvalActions";
    import { advanceQueue, type QueueState } from "../../lib/reviewQueue";
    import { showToast } from "../../lib/toast";

    function initReview() {
        const root = document.querySelector<HTMLElement>("[data-review-root]");
        if (!root || root.dataset.bound === "1") return;
        root.dataset.bound = "1";
        const es = root.dataset.lang === "es";
        const cards = () => Array.from(root.querySelectorAll<HTMLElement>("[data-review-card]"));
        let state: QueueState = {
            visible: cards().filter((c) => !c.hidden).map((c) => c.dataset.id!),
            hidden: cards().filter((c) => c.hidden).map((c) => c.dataset.id!),
            total: Number(root.dataset.total || "0"),
        };
        let busy = false;

        const setBusy = (on: boolean) => {
            busy = on;
            root.querySelectorAll<HTMLButtonElement>("[data-review-card] button").forEach((b) => (b.disabled = on));
        };
        const collapse = (card: HTMLElement) => {
            card.querySelector<HTMLElement>("[data-review-expand]")?.setAttribute("hidden", "");
            delete card.dataset.mode;
        };
        const expand = (card: HTMLElement, mode: "partial" | "reject") => {
            cards().forEach((c) => { if (c !== card) collapse(c); });
            if (card.dataset.mode === mode) { collapse(card); return; }
            card.dataset.mode = mode;
            const panel = card.querySelector<HTMLElement>("[data-review-expand]");
            panel?.removeAttribute("hidden");
            panel?.querySelector<HTMLElement>("[data-review-pcts]")?.toggleAttribute("hidden", mode !== "partial");
            panel?.querySelector<HTMLTextAreaElement>("[data-review-note]")?.focus();
        };
        const render = (reveal: string | null, empty: boolean, elsewhere: number) => {
            if (reveal) root.querySelector<HTMLElement>(`[data-review-card][data-id="${CSS.escape(reveal)}"]`)?.removeAttribute("hidden");
            root.querySelectorAll("[data-review-count]").forEach((el) => (el.textContent = String(state.total)));
            if (empty) {
                root.querySelector("[data-review-heading-count]")?.setAttribute("hidden", "");
                root.querySelector("[data-review-all]")?.setAttribute("hidden", "");
                root.querySelector("[data-review-empty]")?.removeAttribute("hidden");
            }
            const more = root.querySelector<HTMLElement>("[data-review-more]");
            if (more) {
                more.toggleAttribute("hidden", elsewhere === 0);
                more.querySelectorAll("[data-review-more-count]").forEach((el) => (el.textContent = String(elsewhere)));
            }
        };
        const decide = async (card: HTMLElement, d: Pick<Decision, "approve" | "grade" | "partialPct">) => {
            if (busy) return;
            setBusy(true);
            const notes = card.querySelector<HTMLTextAreaElement>("[data-review-note]")?.value.trim() || null;
            const res = await submitDecision({
                kind: card.dataset.kind as Decision["kind"],
                id: card.dataset.id!,
                notes,
                ...d,
            });
            setBusy(false);
            if (!res.ok) {
                showToast(res.error || (es ? "No se pudo guardar. Intenta de nuevo." : "Couldn't save. Try again."), "error");
                return;
            }
            const next = advanceQueue(state, card.dataset.id!);
            state = { visible: next.visible, hidden: next.hidden, total: next.total };
            card.remove();
            render(next.reveal, next.empty, next.remainingElsewhere);
        };

        root.addEventListener("click", (e) => {
            const target = e.target as HTMLElement;
            const card = target.closest<HTMLElement>("[data-review-card]");
            if (!card || busy) return;
            const kind = card.dataset.kind;
            const action = target.closest<HTMLElement>("[data-review-action]")?.dataset.reviewAction;
            if (action === "approve") {
                void decide(card, { approve: true, grade: kind === "task" ? "full" : null });
                return;
            }
            if (action === "partial" || action === "reject") {
                expand(card, action);
                return;
            }
            const pct = target.closest<HTMLElement>("[data-pct]");
            if (pct) {
                card.querySelectorAll<HTMLElement>("[data-pct]").forEach((b) =>
                    b.setAttribute("aria-pressed", b === pct ? "true" : "false"));
                return;
            }
            if (target.closest("[data-review-confirm]")) {
                if (card.dataset.mode === "partial") {
                    const sel = card.querySelector<HTMLElement>('[data-pct][aria-pressed="true"]');
                    void decide(card, { approve: true, grade: "partial", partialPct: Number(sel?.dataset.pct ?? 50) });
                } else if (card.dataset.mode === "reject") {
                    void decide(card, { approve: false, grade: kind === "task" ? "missed" : null });
                }
            }
        });
    }

    document.addEventListener("astro:page-load", initReview);
    // astro:page-load is one-shot on DOMContentLoaded; a module running after it
    // would miss it (see WelcomeTour.astro). data-bound keeps this idempotent.
    if (document.readyState !== "loading") initReview();
</script>
```

- [ ] **Step 3: Type-check**

Run (from `frontend/`): `npm run check`
Expected: `0 errors` (the components are not rendered by a page yet; astro check still type-checks them).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/home/ReviewCard.astro frontend/src/components/home/ReviewSection.astro
git commit -m "feat(parent-hub): inline review section with graded decisions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Kid rows with nudge, oversight proxy, setup card

**Files:**
- Create: `frontend/src/pages/api/oversight/[...path].ts`
- Create: `frontend/src/components/home/KidRow.astro`
- Create: `frontend/src/components/home/SetupCard.astro`

**Interfaces:**
- Consumes (Task 4): `KidRowView`, `nudgeLabel`, `NUDGE_COOLDOWN_MS`; (Task 2) `POST /api/oversight/nudge/{kid_id}`; `showToast`; `t(lang, key)` keys `pd_onb_task`, `pd_onb_task_cta`, `pd_onb_reward`, `pd_onb_invite`, `pd_onb_approve`, `onboarding_progress_label`.
- Produces: `<KidRow view={KidRowView} lang={"es"|"en"} />` (an `<li>`); `<SetupCard onboarding={{task_created, reward_created, child_invited, points_awarded}} lang={"es"|"en"} showModuleStarter={boolean} />` with ids `onboarding-widget` / `dismiss-onboarding` and a `data-mission="first-task"` button (Task 7 keeps the missions script that consumes it).

- [ ] **Step 1: Create the proxy**

`frontend/src/pages/api/oversight/[...path].ts`:

```ts
import { createApiProxy } from "../../../lib/server/proxy";

export const { GET, POST, PUT, DELETE, PATCH } = createApiProxy({ name: "oversight" });
```

- [ ] **Step 2: Create `KidRow.astro`**

```astro
---
/**
 * One kid on the parent home (UX-C2): today's count, overdue chip, weekly pay
 * meter (bar only, no $ — C1 rule) or a plain progress bar, goal line, and a
 * "⏰ Recordar" nudge capped server-side at one per kid per 3 h.
 */
import { nudgeLabel, type KidRowView } from "../../lib/parentHub";

interface Props {
    view: KidRowView;
    lang: "es" | "en";
}
const { view, lang } = Astro.props;
const es = lang === "es";
const label = nudgeLabel(view.nudge, lang);
const showButton = view.nudge.kind === "ready" || view.nudge.kind === "cooldown";
---

<li data-kid-row data-kid-id={view.id} data-kid-name={view.name}
    class="bg-white rounded-2xl border border-brand-ink/10 p-3 shadow-[var(--shadow-card)] flex items-center gap-3">
    <a href="/parent/day" class="flex-1 min-w-0 flex items-center gap-3">
        <div class="w-8 h-8 rounded-full bg-brand-cream-deep flex items-center justify-center font-bold text-sm text-brand-sky-deep shrink-0" aria-hidden="true">
            {view.initial}
        </div>
        <div class="flex-1 min-w-0">
            <p class="text-sm text-brand-ink truncate">
                <span class="font-bold">{view.name}</span>
                {view.doneLabel && <span class="text-brand-ink-soft"> · {view.doneLabel}</span>}
                {view.overdueChip && (
                    <span class="ml-1 inline-block rounded-full bg-red-100 text-red-700 px-1.5 py-0.5 text-[10px] font-bold">{view.overdueChip}</span>
                )}
            </p>
            {view.meter.show ? (
                <div class="mt-1.5 h-1.5 rounded-full bg-brand-ink/10 flex overflow-hidden" role="img" aria-label={es ? "Pago de la semana" : "Weekly pay"}>
                    <span class="bg-emerald-500" style={`width:${view.meter.greenPct}%`}></span>
                    <span class="bg-red-400" style={`width:${view.meter.redPct}%`}></span>
                </div>
            ) : view.doneLabel ? (
                <div class="mt-1.5 h-1.5 rounded-full bg-brand-ink/10 overflow-hidden">
                    <span class="block h-full bg-brand-sky-deep" style={`width:${view.progressPct}%`}></span>
                </div>
            ) : null}
            {view.goalLine && <p class="text-[11px] text-brand-ink-soft mt-1 truncate">{view.goalLine}</p>}
        </div>
    </a>
    {view.nudge.kind === "done" && <span class="text-xs font-extrabold text-emerald-700 whitespace-nowrap">{label}</span>}
    {showButton && (
        <button type="button" data-nudge-btn disabled={view.nudge.kind === "cooldown"}
            class="shrink-0 rounded-xl border px-2.5 py-1.5 text-xs font-bold whitespace-nowrap border-orange-300 bg-orange-50 text-orange-700 hover:bg-orange-100 disabled:border-brand-ink/10 disabled:bg-brand-cream-deep disabled:text-brand-ink-soft disabled:font-semibold">
            {label}
        </button>
    )}
</li>

<script>
    import { NUDGE_COOLDOWN_MS, nudgeLabel } from "../../lib/parentHub";
    import { showToast } from "../../lib/toast";

    function initNudges() {
        const lang = document.documentElement.lang === "es" ? "es" : "en";
        const es = lang === "es";
        document.querySelectorAll<HTMLButtonElement>("[data-nudge-btn]").forEach((btn) => {
            if (btn.dataset.bound === "1") return;
            btn.dataset.bound = "1";
            btn.addEventListener("click", async () => {
                if (btn.disabled) return;
                const row = btn.closest<HTMLElement>("[data-kid-row]");
                const id = row?.dataset.kidId;
                const name = row?.dataset.kidName ?? "";
                if (!id) return;
                btn.disabled = true;
                let res: Response;
                try {
                    res = await fetch(`/api/oversight/nudge/${encodeURIComponent(id)}`, { method: "POST" });
                } catch {
                    showToast(es ? "No se pudo enviar. Intenta de nuevo." : "Couldn't send. Try again.", "error");
                    btn.disabled = false;
                    return;
                }
                if (res.ok) {
                    btn.textContent = es ? "Enviado · ahora" : "Sent · just now";
                    showToast(es ? `Recordatorio enviado a ${name}` : `Reminder sent to ${name}`, "success");
                    return;
                }
                const body = await res.json().catch(() => null);
                if (res.status === 429) {
                    const retry = Number(body?.retry_after_seconds ?? 0);
                    const hoursAgo = Math.max(0, Math.floor((NUDGE_COOLDOWN_MS / 1000 - retry) / 3600));
                    btn.textContent = nudgeLabel({ kind: "cooldown", hoursAgo }, lang) ?? "";
                    return;
                }
                if (res.status === 409) {
                    showToast(es ? `Nada pendiente para ${name}` : `Nothing left for ${name}`, "info");
                    btn.remove();
                    return;
                }
                showToast(es ? "No se pudo enviar. Intenta de nuevo." : "Couldn't send. Try again.", "error");
                btn.disabled = false;
            });
        });
    }

    document.addEventListener("astro:page-load", initNudges);
    if (document.readyState !== "loading") initNudges();
</script>
```

- [ ] **Step 3: Create `SetupCard.astro`**

```astro
---
/**
 * "Configura tu familia" (UX-C2): replaces the old onboarding widget and the
 * gigs intro banner. Shown only while setup is incomplete and not dismissed
 * (the page decides). The first-task step keeps its guided-mission button;
 * the missions script in parent/index.astro consumes [data-mission].
 */
import { t } from "../../lib/i18n";

interface Props {
    onboarding: { task_created: boolean; reward_created: boolean; child_invited: boolean; points_awarded: boolean };
    lang: "es" | "en";
    showModuleStarter: boolean;
}
const { onboarding, lang, showModuleStarter } = Astro.props;
const es = lang === "es";
const steps = [
    { done: onboarding.task_created, label: t(lang, "pd_onb_task") as string, href: "/parent/tasks", mission: "first-task" },
    { done: onboarding.reward_created, label: t(lang, "pd_onb_reward") as string, href: "/parent/rewards", mission: null },
    { done: onboarding.child_invited, label: t(lang, "pd_onb_invite") as string, href: "/parent/members#invite", mission: null },
    {
        done: onboarding.points_awarded,
        label: t(lang, "pd_onb_approve") as string,
        href: onboarding.child_invited ? "/parent/approvals" : null,
        mission: null,
    },
];
const done = steps.filter((s) => s.done).length;
const pct = Math.round((done / steps.length) * 100);
---

<section id="onboarding-widget" aria-labelledby="setup-heading"
    class="mb-6 rounded-2xl border border-brand-coral/30 bg-brand-coral/10 p-4 shadow-[var(--shadow-card)]">
    <div class="flex items-center justify-between gap-2">
        <h2 id="setup-heading" class="font-bold text-brand-ink text-sm">
            {es ? `Configura tu familia · ${done} de 4` : `Set up your family · ${done} of 4`}
        </h2>
        <button id="dismiss-onboarding" type="button" aria-label={es ? "Ocultar" : "Hide"}
            class="text-brand-ink-soft hover:text-brand-ink text-xl leading-none px-1 disabled:opacity-50">×</button>
    </div>
    <div class="mt-2 h-2 rounded-full bg-brand-cream-deep overflow-hidden" role="progressbar"
        aria-valuenow={done} aria-valuemin={0} aria-valuemax={4} aria-label={t(lang, "onboarding_progress_label") as string}>
        <div class="h-full bg-brand-coral rounded-full" style={`width:${pct}%`}></div>
    </div>
    <a href="/parent/starter-packs"
        class="mt-3 flex items-center justify-between gap-3 rounded-xl bg-brand-sky-deep/10 border border-brand-sky-deep/30 px-3 py-2 text-sm font-semibold text-brand-ink hover:bg-brand-sky-deep/20">
        <span>📦 {es ? "Empieza en minutos con un paquete por edad" : "Start in minutes with an age starter pack"}</span>
        <span class="text-brand-sky-deep" aria-hidden="true">→</span>
    </a>
    {showModuleStarter && (
        <a href="/parent/settings/family#modules-section"
            class="mt-2 flex items-center justify-between gap-3 rounded-xl bg-brand-mint/10 border border-brand-mint-deep/30 px-3 py-2 text-sm font-semibold text-brand-ink hover:bg-brand-mint/20">
            <span>🎛️ {es ? "¿Solo tareas y domingo, o la app completa? Elige tus módulos" : "Just chores & allowance, or the full app? Pick your modules"}</span>
            <span class="text-brand-mint-deep" aria-hidden="true">→</span>
        </a>
    )}
    <ol class="mt-3 space-y-1.5 text-sm">
        {steps.map((s) => (
            <li class="flex items-center gap-2">
                <span aria-hidden="true">{s.done ? "✅" : "◻"}</span>
                <span class={s.done ? "line-through text-brand-ink-soft" : "text-brand-ink"}>{s.label}</span>
                {!s.done && s.mission && (
                    <button type="button" data-mission={s.mission} class="ml-auto text-xs font-semibold text-brand-sky-deep hover:underline">
                        🧭 {t(lang, "pd_onb_task_cta")}
                    </button>
                )}
                {!s.done && s.href && (
                    <a href={s.href} aria-label={s.label}
                        class={`${s.mission ? "" : "ml-auto "}text-xs font-semibold text-brand-sky-deep hover:underline`}>›</a>
                )}
            </li>
        ))}
    </ol>
    <p class="mt-3 text-xs text-brand-ink-soft">
        {es ? "¿Cómo funcionan puntos y dinero?" : "How do points and money work?"}
        <a href={es ? "/ayuda" : "/help"} class="font-semibold text-brand-sky-deep hover:underline">{es ? "Ver guía" : "Read the guide"}</a>
    </p>
</section>

<script>
    import { showToast } from "../../lib/toast";

    function initSetupDismiss() {
        const btn = document.getElementById("dismiss-onboarding") as HTMLButtonElement | null;
        if (!btn || btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", async () => {
            btn.disabled = true;
            try {
                const r = await fetch("/api/families/onboarding/dismiss", { method: "POST" });
                if (r.ok) {
                    document.getElementById("onboarding-widget")?.remove();
                    return;
                }
            } catch {
                /* fall through to the retry toast */
            }
            btn.disabled = false;
            showToast(
                document.documentElement.lang === "es" ? "No se pudo ocultar. Intenta de nuevo." : "Couldn't hide it. Try again.",
                "error",
            );
        });
    }

    document.addEventListener("astro:page-load", initSetupDismiss);
    if (document.readyState !== "loading") initSetupDismiss();
</script>
```

- [ ] **Step 4: Type-check**

Run: `npm run check`
Expected: `0 errors`.

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/pages/api/oversight/[...path].ts" frontend/src/components/home/KidRow.astro frontend/src/components/home/SetupCard.astro
git commit -m "feat(parent-hub): kid rows with capped nudge, oversight proxy, setup card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Hub layout and the new `/parent`

**Files:**
- Create: `frontend/src/components/home/ParentHub.astro`
- Rewrite: `frontend/src/pages/parent/index.astro`
- Delete: `frontend/src/components/GigsIntroBanner.astro`

**Interfaces:**
- Consumes: Task 3 `buildReviewQueue`, `ReviewItem`; Task 4 `kidRowView`, `KidRowView`, `budgetGlanceView`, `BudgetGlance`, `greetingDate`, `monthLabel`, `firstName`; Task 5 `ReviewSection`; Task 6 `KidRow`, `SetupCard`; C1 `TaskDeck` (props `cards, lang, variant, heading, counter`) and `buildDeck(progress, lang)` from `lib/deck`; `formatCurrency(cents)` from `lib/api/budget`.
- Produces: the new `/parent` page.

- [ ] **Step 1: Create `ParentHub.astro`**

```astro
---
/**
 * Parent "Today" hub layout (UX-C2), top to bottom: setup card, review,
 * kids today, to pay, my chores, budget glance, Family Cup. Each section
 * renders only when it has content. Behavior lives in the child components.
 * No scan button here — CLAUDE.md: exactly two visible scan triggers.
 */
import ReviewSection from "./ReviewSection.astro";
import KidRow from "./KidRow.astro";
import SetupCard from "./SetupCard.astro";
import TaskDeck from "../deck/TaskDeck.astro";
import { formatCurrency } from "../../lib/api/budget";
import type { ReviewItem } from "../../lib/reviewQueue";
import type { BudgetGlance, KidRowView } from "../../lib/parentHub";
import type { buildDeck } from "../../lib/deck";

interface Props {
    lang: "es" | "en";
    tz: string | null;
    userId: string;
    setup: { onboarding: any; showModuleStarter: boolean } | null;
    reviewItems: ReviewItem[];
    kidRows: KidRowView[];
    pay: { owedCents: number; cashCents: number; paychecksCents: number; href: string; paidNames: string[] };
    myDeck: ReturnType<typeof buildDeck> | null;
    budget: { view: Extract<BudgetGlance, { show: true }>; monthName: string } | null;
    boss: any | null;
}
const { lang, tz, userId, setup, reviewItems, kidRows, pay, myDeck, budget, boss } = Astro.props;
const es = lang === "es";
const fmtMoney = (cents: number) => `$${(cents / 100).toFixed(2)}`;
const paidLine = pay.paidNames.length
    ? es
        ? `${pay.paidNames.join(", ")} ${pay.paidNames.length === 1 ? "recibió" : "recibieron"} su pago del Banco Familiar.`
        : `${pay.paidNames.join(", ")} got their Family Bank payday.`
    : null;
const showPay = pay.owedCents > 0 || paidLine !== null;
const bossName = boss ? (es ? boss.name_es : boss.name_en) : "";
const label = "text-xs font-extrabold uppercase tracking-wider text-brand-ink-soft";
---

<div class="max-w-md mx-auto w-full">
    {setup && <SetupCard onboarding={setup.onboarding} lang={lang} showModuleStarter={setup.showModuleStarter} />}

    <ReviewSection items={reviewItems} lang={lang} tz={tz} userId={userId} />

    <section class="mb-6" aria-labelledby="kids-heading">
        <h2 id="kids-heading" class={`${label} mb-2 px-1`}>{es ? "Hoy" : "Today"}</h2>
        {kidRows.length > 0 ? (
            <ul class="space-y-2">
                {kidRows.map((view) => <KidRow view={view} lang={lang} />)}
            </ul>
        ) : (
            <a href="/parent/members#invite" class="block rounded-xl bg-white border border-brand-ink/10 px-3 py-2 text-sm text-brand-ink-soft">
                {es ? "Invita a tus hijos para ver su día aquí ›" : "Invite your kids to see their day here ›"}
            </a>
        )}
    </section>

    {showPay && (
        <section class="mb-6" aria-labelledby="pay-heading">
            <h2 id="pay-heading" class={`${label} mb-2 px-1`}>{es ? "Por pagar" : "To pay"}</h2>
            <a href={pay.href}
                class="flex items-center justify-between gap-3 rounded-2xl bg-gradient-to-br from-emerald-700 to-emerald-600 text-white px-4 py-3 shadow-[var(--shadow-card)] hover:from-emerald-800 hover:to-emerald-700 transition-colors">
                <div class="min-w-0">
                    {pay.owedCents > 0 && (
                        <>
                            <p class="text-2xl font-extrabold tracking-tight">{fmtMoney(pay.owedCents)}</p>
                            <p class="text-xs text-emerald-100 mt-0.5">
                                Gigs {fmtMoney(pay.cashCents)} · {es ? "Cheques de tareas" : "Chore paychecks"} {fmtMoney(pay.paychecksCents)}
                            </p>
                        </>
                    )}
                    {paidLine && <p class="text-xs text-emerald-50 mt-1">🏦 {paidLine}</p>}
                </div>
                <span class="text-sm font-bold whitespace-nowrap">{es ? "Pagar ›" : "Pay ›"}</span>
            </a>
        </section>
    )}

    {myDeck && (
        <section class="mb-6">
            <TaskDeck
                cards={myDeck.cards}
                lang={lang}
                variant="compact"
                heading={es ? "Mis tareas de hoy" : "My tasks today"}
                counter={{ done: myDeck.doneToday, total: myDeck.totalToday, suffix: "" }}
            />
        </section>
    )}

    {budget && (
        <section class="mb-6" aria-labelledby="budget-heading">
            <div class="flex items-center justify-between mb-2 px-1">
                <h2 id="budget-heading" class={label}>{es ? "Presupuesto" : "Budget"} · {budget.monthName}</h2>
                <a href="/budget/month" class="text-xs font-semibold text-brand-sky-deep hover:underline">{es ? "Abrir ›" : "Open ›"}</a>
            </div>
            <div class="bg-white rounded-2xl border border-brand-ink/10 p-3 shadow-[var(--shadow-card)]">
                <p class="text-sm text-brand-ink flex justify-between gap-2">
                    <span>{es ? "Gastado" : "Spent"} <b>{formatCurrency(budget.view.spentCents)}</b></span>
                    {budget.view.budgetedCents > 0 && (
                        <span class="text-brand-ink-soft">{es ? "de" : "of"} {formatCurrency(budget.view.budgetedCents)}</span>
                    )}
                </p>
                {budget.view.budgetedCents > 0 && (
                    <div class="mt-2 h-1.5 rounded-full bg-brand-ink/10 overflow-hidden">
                        <span class={`block h-full ${budget.view.over ? "bg-red-500" : "bg-emerald-500"}`} style={`width:${budget.view.pct}%`}></span>
                    </div>
                )}
                {budget.view.draftsLine && (
                    <a href="/budget/receipt-drafts" class="mt-2 inline-block text-xs font-semibold text-brand-sky-deep hover:underline">{budget.view.draftsLine} ›</a>
                )}
            </div>
        </section>
    )}

    {boss?.active && (
        <a href="/family-cup" class="mb-6 block rounded-2xl bg-white border border-brand-ink/10 px-3 py-2 text-sm text-brand-ink shadow-[var(--shadow-card)]">
            🏆 <b>Family Cup</b> · {boss.emoji} {bossName} ·
            {boss.defeated ? (es ? " ¡Derrotado! 🎉" : " Defeated! 🎉") : ` ${boss.current_hp}/${boss.max_hp} HP`}
        </a>
    )}
</div>
```

- [ ] **Step 2: Rewrite `frontend/src/pages/parent/index.astro`**

Replace the whole file with the content below. It keeps, verbatim, the AI-consent card, the module-off/flash banners, the AI-consent handlers and the missions `<script>` from the current file; it drops the tile grid, the old kid cards, the payday banner, the top boss bar, the top push button, `GigsIntroBanner`, the onboarding widget and its dismiss handler (now in `SetupCard`).

```astro
---
import PageLayout from "@components/ui/PageLayout.astro";
import ParentHub from "../../components/home/ParentHub.astro";
import { apiFetch } from "../../lib/api";
import { t } from "../../lib/i18n";
import { buildDeck } from "../../lib/deck";
import { buildReviewQueue } from "../../lib/reviewQueue";
import { budgetGlanceView, firstName, greetingDate, kidRowView, monthLabel } from "../../lib/parentHub";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = (Astro.cookies.get("lang")?.value ?? "es") as "en" | "es";

const { data: user } = await apiFetch<any>("/api/auth/me", { token });
if (!user) {
    Astro.cookies.delete("access_token", { path: "/" });
    return Astro.redirect("/login");
}
if (user.role !== "parent") return Astro.redirect("/dashboard");

const tz: string | null = user.timezone ?? null;
const now = new Date();
const modOn = (m: string) => user.enabled_modules == null || user.enabled_modules.includes(m);

// Flash cookies set by /api/assignments/complete (next=/parent).
const flash = Astro.cookies.get("flash")?.value;
if (flash) Astro.cookies.delete("flash", { path: "/" });
const flashError = Astro.cookies.get("flash_error")?.value;
if (flashError) Astro.cookies.delete("flash_error", { path: "/" });

// Every fetch is fail-open (apiFetch never throws): a missing piece hides its section.
const [
    familyRes, progressRes, cupRes, oversightRes, bankFamilyRes, payoutRes,
    taskPendingRes, gigPendingRes, redemptionRes, onboardingRes,
] = await Promise.all([
    apiFetch<any>("/api/families/me", { token }),
    apiFetch<any>("/api/task-assignments/progress", { token }),
    apiFetch<any>("/api/family-cup/", { token }),
    apiFetch<any>("/api/oversight/summary", { token }),
    apiFetch<any[]>("/api/bank/family", { token }),
    apiFetch<any>("/api/bank/payout-summary", { token }),
    apiFetch<any[]>("/api/task-assignments/pending-approvals", { token }),
    apiFetch<any[]>("/api/gigs/claims/pending-approvals", { token }),
    apiFetch<any[]>("/api/rewards/redemptions/pending", { token }),
    apiFetch<any>("/api/families/onboarding", { token }),
]);
const family = familyRes.data;

// The parent's OWN chores — C1 compact deck, same rule as before (incl. overdue).
const myProgress = progressRes.data;
const myHasChores =
    (myProgress?.assignments ?? []).some((a: any) => a.status !== "cancelled") ||
    (myProgress?.overdue_assignments ?? []).length > 0;
const myDeck = myHasChores ? buildDeck(myProgress, lang) : null;

// Kids today: oversight summary + each kid's weekly paycheck (few kids → parallel).
const kids: any[] = oversightRes.data?.members ?? [];
const paychecks = await Promise.all(
    kids.map((k) => apiFetch<any>(`/api/bank/chore-paycheck/${k.user_id}`, { token })),
);
const kidRows = kids.map((k, i) => kidRowView(k, paychecks[i].data, now, lang));

// To pay: money owed + anyone whose Family Bank payday fired in the last 2 days.
const bankFamily = Array.isArray(bankFamilyRes.data) ? bankFamilyRes.data : [];
const paidNames = bankFamily
    .filter((k: any) => k.last_payday_at && now.getTime() - new Date(k.last_payday_at).getTime() < 2 * 24 * 3600 * 1000)
    .map((k: any) => String(k.name));
const payout = payoutRes.data;
const pay = {
    owedCents: payout?.outstanding_grand_total_cents ?? 0,
    cashCents: payout?.cash_total_cents ?? 0,
    paychecksCents: payout?.outstanding_paycheck_total_cents ?? 0,
    // With the gigs module off there is no payouts page (middleware bounces it).
    href: modOn("gigs") ? "/parent/payouts" : "/parent/settings/family-bank",
    paidNames,
};

// Review: the same three queues /parent/approvals lists, oldest first.
const reviewItems = buildReviewQueue(taskPendingRes.data, gigPendingRes.data, redemptionRes.data, lang);

// Setup card: only while setup is incomplete and not dismissed.
const onboarding = onboardingRes.data ?? null;
const setup =
    onboarding && !onboarding.dismissed && !onboarding.all_done
        ? { onboarding, showModuleStarter: user.enabled_modules == null }
        : null;

// Budget glance: same month + math as the budget dashboard. No scan button.
let budget: { view: any; monthName: string } | null = null;
if (modOn("budget")) {
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    const [monthRes, draftsRes] = await Promise.all([
        apiFetch<any>(`/api/budget/month/${year}/${month}`, { token }),
        apiFetch<{ count: number }>("/api/budget/receipt-drafts/count", { token }),
    ]);
    const view = budgetGlanceView(monthRes.data, draftsRes.data?.count ?? 0, lang);
    if (view.show) budget = { view, monthName: monthLabel(year, month, lang) };
}

const boss = cupRes.data?.boss ?? null;
const hello = firstName(user.name);
---

<PageLayout
    title={t(lang, "parent_dashboard") as string}
    role={user.role}
    active="parent"
    lang={lang}
    completedTour={user.completed_welcome_tour ?? true}
    tourUserKey={user.id}
>
    <header
        slot="header"
        class="bg-gradient-to-br from-slate-800 to-slate-700 text-white pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)]"
    >
        <p class="text-slate-300 text-sm mb-1">{greetingDate(now, lang, tz)}</p>
        <h1 class="text-2xl font-bold">{lang === "es" ? "Hola" : "Hi"}{hello ? `, ${hello}` : ""}</h1>
    </header>

    <Fragment slot="banner">
        {Astro.url.searchParams.get("module_off") === "1" && (
            <div class="mx-4 mt-3 rounded-xl border border-brand-ink/15 bg-brand-cream px-4 py-2.5 text-sm text-brand-ink-soft">
                {lang === "es"
                    ? "Esa sección está desactivada para tu familia. Puedes activarla en Ajustes → Módulos."
                    : "That section is switched off for your family. You can enable it in Settings → Modules."}
            </div>
        )}
        {flash && (
            <div class="mx-4 mt-3 rounded-xl border border-brand-mint-deep/30 bg-brand-mint/15 px-4 py-2.5 text-sm font-semibold text-brand-mint-deep" data-flash-success>
                {flash}
            </div>
        )}
        {flashError && (
            <div class="mx-4 mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-semibold text-red-700">
                {flashError}
            </div>
        )}
    </Fragment>

    {family && family.ai_processing_consent_at == null && (
        <div id="ai-consent-banner" class="max-w-md mx-auto w-full mb-6 bg-brand-sky/10 border border-brand-sky/30 rounded-2xl p-5 shadow-[var(--shadow-card)]">
            <h2 class="font-bold text-brand-ink text-base mb-1">
                {lang === "es" ? "¿Permitir IA con el contenido de tus hijos?" : "Allow AI on your kids' content?"}
            </h2>
            <p class="text-sm text-brand-ink-soft mb-3">
                {lang === "es"
                    ? "Permitir que la IA procese fotos de tareas y mensajes del chat familiar para validar pruebas automáticamente y ayudar al asistente. Si no lo permites, las pruebas siempre pasan a tu aprobación manual. Puedes cambiarlo cuando quieras en Ajustes de la familia. "
                    : "Allow AI to process task proof photos and family chat messages to auto-validate proofs and help the assistant. If you decline, proofs always go to your manual approval. You can change this anytime in Family settings. "}
                <a href="/privacidad" class="text-brand-sky-deep font-semibold hover:underline">
                    {lang === "es" ? "Aviso de privacidad" : "Privacy notice"}
                </a>
            </p>
            <div class="flex flex-wrap gap-2">
                <button
                    id="ai-consent-allow"
                    class="px-4 py-2 rounded-lg bg-brand-sky-deep text-white text-xs font-semibold hover:bg-brand-ink transition-colors cursor-pointer"
                >
                    {lang === "es" ? "Permitir" : "Allow"}
                </button>
                <button
                    id="ai-consent-decline"
                    class="px-4 py-2 rounded-lg bg-brand-cream-deep text-brand-ink text-xs font-semibold hover:bg-brand-cream border border-brand-ink/15 transition-colors cursor-pointer"
                >
                    {lang === "es" ? "No permitir" : "Don't allow"}
                </button>
            </div>
        </div>
    )}

    <ParentHub
        lang={lang}
        tz={tz}
        userId={user.id}
        setup={setup}
        reviewItems={reviewItems}
        kidRows={kidRows}
        pay={pay}
        myDeck={myDeck}
        budget={budget}
        boss={boss}
    />
</PageLayout>

<script>
    // One-time AI-processing consent prompt: either decision PATCHes the
    // family row (server stamps ai_processing_consent_at, so the banner never
    // shows again). On failure the banner stays for a retry.
    const aiConsentDecide = async (allow: boolean) => {
        try {
            const r = await fetch("/api/families/me", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ai_processing_consent: allow }),
            });
            if (r.ok) document.getElementById("ai-consent-banner")?.remove();
        } catch (e) {
            console.error("ai consent decision failed:", e);
        }
    };
    document.getElementById("ai-consent-allow")?.addEventListener("click", () => aiConsentDecide(true));
    document.getElementById("ai-consent-decline")?.addEventListener("click", () => aiConsentDecide(false));
</script>
```

Then append the **missions `<script>` block unchanged** — copy it verbatim from the current file (it starts with `<script>` / `import { buildMission } from "../../lib/tourSteps";` and ends with `if (document.readyState !== "loading") initMissions();` / `</script>`). Read it from git before overwriting: `git show HEAD:frontend/src/pages/parent/index.astro | sed -n '/import { buildMission }/,$p'` and paste it (with its opening `<script>` line) at the end of the new file.

- [ ] **Step 3: Delete the gigs intro banner**

```bash
git rm frontend/src/components/GigsIntroBanner.astro
grep -rn "GigsIntroBanner" frontend/src || echo "no references left"
```

Expected: `no references left`.

- [ ] **Step 4: Check the page for removed pieces and the scan rule**

```bash
cd frontend
grep -c "data-mission" src/components/home/SetupCard.astro        # expect ≥1
grep -n "scan" src/pages/parent/index.astro src/components/home/*.astro || echo "no scan trigger"
grep -n "parent/tasks\"\|grid grid-cols-2" src/pages/parent/index.astro || echo "tile grid gone"
```

Expected: `no scan trigger`, `tile grid gone`.

- [ ] **Step 5: Type-check, test, build**

Run (from `frontend/`): `npm run check && npx vitest run && npm run build`
Expected: `0 errors`, all vitest files pass, build completes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/home/ParentHub.astro frontend/src/pages/parent/index.astro
git commit -m "feat(parent-hub): /parent becomes the Today hub

Review top 3 inline, kids today with capped nudge, to pay, my chores,
budget glance (no scan button), Family Cup. Tiles, bottom kid cards,
payday banner, top boss bar and the gigs intro banner are gone.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Docs (user guides + CLAUDE.md)

**Files:**
- Modify: `docs/USER_GUIDE_ES.md`, `docs/USER_GUIDE_EN.md`, `CLAUDE.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Fix the stale "Gestion/Management" navigation**

The tile grid is gone; those pages are reached from **Más** / **More** (all of them are in the More sheet). Apply these exact replacements with a script that asserts each old string exists exactly once (fail loudly otherwise):

`docs/USER_GUIDE_ES.md`:
| Old | New |
|-----|-----|
| `1. Vaya a **Gestion** (\`/parent\`) → **Miembros** (\`/parent/members\`)` | `1. Abra **Más** → **Miembros** (\`/parent/members\`)` |
| `\| **Gestion** \| \`/parent\` \| Padres \|` | `\| **Inicio** \| \`/parent\` \| Padres \|` |
| `1. Vaya a **Gestion** → **Tareas** (\`/parent/tasks\`)` | `1. Abra **Más** → **Tareas** (\`/parent/tasks\`)` |
| `1. Vaya a **Gestion** → **Premios** (\`/parent/rewards\`)` | `1. Abra **Más** → **Premios** (\`/parent/rewards\`)` |
| `1. Vaya a **Gestion** → **Consecuencias** (\`/parent/consequences\`)` | `1. Abra **Más** → **Consecuencias** (\`/parent/consequences\`)` |
| `1. Vaya a **Gestion** → **Pantallas de pared** (\`/parent/kiosk\`)` | `1. Abra **Más** → **Pantallas de pared** (\`/parent/kiosk\`)` |
| `1. Vaya a **Gestion** (\`/parent\`)\n2. Abra **Configuracion**\n3. Toque **"Analitica"**` | `1. Abra **Más** → **Analitica** (\`/parent/analytics\`)` |
| `1. Vaya a **Gestion** (\`/parent\`) y abra **Jarvis** (\`/parent/jarvis\`)` | `1. Abra **Más** → **Jarvis** (\`/parent/jarvis\`)` |
| `Vaya a **Gestion** → **Miembros**.` | `Abra **Más** → **Miembros**.` |

`docs/USER_GUIDE_EN.md`:
| Old | New |
|-----|-----|
| `1. Go to **Management** (\`/parent\`) → **Members** (\`/parent/members\`)` | `1. Open **More** → **Members** (\`/parent/members\`)` |
| `\| **Management** \| \`/parent\` \| Parents \|` | `\| **Home** \| \`/parent\` \| Parents \|` |
| `1. Go to **Management** → **Tasks** (\`/parent/tasks\`)` | `1. Open **More** → **Tasks** (\`/parent/tasks\`)` |
| `1. Go to **Management** → **Rewards** (\`/parent/rewards\`)` | `1. Open **More** → **Rewards** (\`/parent/rewards\`)` |
| `1. Go to **Management** → **Consequences** (\`/parent/consequences\`)` | `1. Open **More** → **Consequences** (\`/parent/consequences\`)` |
| `1. Go to **Management** → **Wall displays** (\`/parent/kiosk\`)` | `1. Open **More** → **Wall displays** (\`/parent/kiosk\`)` |
| `1. Go to **Management** (\`/parent\`)\n2. Open **Settings**\n3. Tap **"Analytics"** (described as "PUP Score + completion trends")` | `1. Open **More** → **Analytics** (\`/parent/analytics\`)` |
| `1. Go to **Management** (\`/parent\`) and open **Jarvis** (\`/parent/jarvis\`).` | `1. Open **More** → **Jarvis** (\`/parent/jarvis\`).` |
| `Go to **Management** → **Members**.` | `Open **More** → **Members**.` |

Afterwards: `grep -n "\*\*Gestion\*\*" docs/USER_GUIDE_ES.md; grep -n "\*\*Management\*\*" docs/USER_GUIDE_EN.md` → no output.

- [ ] **Step 2: Describe the parent home**

In `docs/USER_GUIDE_ES.md`, directly before the heading `### Cambio de idioma` (section 1.5), insert:

```markdown
### Inicio de padres

**Inicio** (`/parent`) muestra lo que necesita su atención hoy, en este orden:

1. **Configura tu familia** — solo mientras falten pasos de configuración.
2. **Por revisar** — las 3 entregas más antiguas (tareas con foto, gigs y canjes de premios). **✓ Aprobar** decide con un toque; **Casi** da crédito parcial (25/50/75 %) y **No hecha** permite dejar una nota. "Ver todas" abre **Aprobar**.
3. **Hoy** — una fila por hijo: tareas hechas de hoy, atrasadas, la barra del pago semanal y su meta. **⏰ Recordar** le manda un aviso; solo se puede una vez cada 3 horas por hijo (entre ambos padres).
4. **Por pagar** — dinero pendiente (gigs y cheques de tareas).
5. **Mis tareas de hoy** — sus propias tareas.
6. **Presupuesto** — lo gastado del mes contra lo presupuestado y los tickets por revisar. Para escanear un ticket use el botón **Escanear** del presupuesto.
7. **Family Cup** — el jefe de la semana.
```

In `docs/USER_GUIDE_EN.md`, directly before `### Changing the language` (section 1.5), insert:

```markdown
### Parent home

**Home** (`/parent`) shows what needs you today, in this order:

1. **Set up your family** — only while setup steps are missing.
2. **To review** — the 3 oldest submissions (chores with a photo, gigs and reward redemptions). **✓ Approve** decides in one tap; **Almost** gives partial credit (25/50/75 %) and **Missed** lets you leave a note. "See all" opens **Approve**.
3. **Today** — one row per kid: today's chores done, overdue ones, the weekly pay bar and their goal. **⏰ Remind** sends them a notice; it works once every 3 hours per kid (shared by both parents).
4. **To pay** — money owed (gigs and chore paychecks).
5. **My tasks today** — your own chores.
6. **Budget** — this month's spending against the budget and receipts to review. To scan a receipt, use the budget's **Scan** button.
7. **Family Cup** — this week's boss.
```

- [ ] **Step 3: CLAUDE.md**

In `CLAUDE.md`, section "Frontend (Astro 5)" → "Key frontend pages", add as the first bullet:

```markdown
- `/parent` — parent "Today" hub (UX-C2): review top 3 inline (shared request code `lib/approvalActions.ts`, also used by `/parent/approvals`), per-kid rows with a nudge (`POST /api/oversight/nudge/{kid_id}`, one per kid per 3 h across both parents, `parent_nudge` notification that supersedes the previous one), to pay, own chores deck, budget glance (**no scan button** — the two-scan-triggers rule), Family Cup. The old tile grid is gone; every page it linked is in the More sheet.
```

- [ ] **Step 4: Commit**

```bash
git add docs/USER_GUIDE_ES.md docs/USER_GUIDE_EN.md CLAUDE.md
git commit -m "docs: parent home hub and More-sheet navigation in the guides

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Final verification (controller, after all tasks)

- Backend full suite with `TZ=UTC` (`run-backend-full` script pointed at this worktree), `ruff check app`.
- Frontend: `npx vitest run`, `npm run check`, `npm run build`.
- Whole-branch review, one fix wave, scoped re-review.
- Ship: PR → CI → merge → `./scripts/deploy-onprem.sh -y` → prod pass as the demo parent after confirming `family_id == b8312b5a-c9c0-469f-992f-8dbd412db4a7`: all hub sections render; one ✓ approval of a demo item; one nudge to `diego.demo` (button then shows the cooldown); `/parent/approvals` still approves; no console errors. Never touch family `1998e48d-2ef0-48b6-a437-cbb730ae935c`.
