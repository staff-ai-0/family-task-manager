# UX-C1 Swipe-Deck Home + New-Gig Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every member a one-card-at-a-time "what do I do now" deck (kids at `/dashboard`, parents' own chores on `/parent`), a cash-first kid home, and notify kids when a gig is posted.

**Architecture:** Pure, vitest-covered TS modules build the deck and the kid-home view models from existing endpoints. One shared `TaskDeck.astro` component owns swipe/buttons/keyboard/proof/completion (completing via a new JSON mode of the existing `/api/assignments/complete` proxy). `KidHeader.astro` + `KidHome.astro` replace the old kid dashboard markup; `/parent` swaps its "Mis tareas de hoy" list for a compact `TaskDeck`. Backend adds one best-effort notification helper wired into the three places a gig becomes visible, plus two timestamps on the offering response.

**Tech Stack:** Astro 7 SSR · vanilla TS client scripts · Tailwind v4 · vitest · FastAPI · SQLAlchemy async · pytest

**Spec:** `docs/superpowers/specs/2026-09-28-ux-c1-teen-home-design.md`

## Global Constraints

- Work only in the worktree `/Users/jc/dev-2026/AgentIA/family-task-manager/.claude/worktrees/ux-c1-teen-home` (branch `feat/ux-c1-teen-home`). Never `cd` to the main checkout. Never use `git stash`.
- **Backend tests:** ONLY targeted files, foreground, via
  `/private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad/run-backend-tests-c1.sh tests/<file>.py [-k expr]`
  (runs in UTC against an ephemeral Postgres on 5435). **Never the full backend suite** — the controller runs it.
- **Frontend checks** from `frontend/`: `npx vitest run [test/<file>.test.ts]`, `npx astro check`. vitest only collects `frontend/test/**/*.test.ts`. Do not start a dev server.
- Every user-visible string ships ES + EN; ES is the default when `lang` is missing.
- **Teen/kid pay meter rule (binding):** never render a moving dollar figure for the chore paycheck — only the weekly goal (`cap_cents`) and the green/red/grey bar (spec `2026-07-21-teen-paycheck-meter-redesign-design.md`).
- **Star mode (CHILD) hides pesos:** no cash pill, no gigs row, points goal instead of cash goal.
- No new dependencies. No migrations.
- Every new test is mutation-checked (break the guarded line, see it fail, restore).
- Commit after each task; conventional message ending with the trailer
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not touch production.

## Review Focus

1. A member with only overdue chores (nothing assigned today) must still get cards, oldest first, and completing a grouped overdue card completes the **oldest** instance — pinned in Task 2.
2. A double-tap / slow network on "Hecho" must not double-complete or leave a card half-removed: one in-flight action at a time; card removed only on success — pinned by the `busy` guard in Task 6 and the JSON contract tests in Task 4.
3. A gig posted to a family must never notify another family's kids, a pending (unapproved) signup, the parent who posted it, or the kid who proposed it — pinned in Task 1.
4. `allowed_roles` stored as `["teen"]` must hide the gig from a CHILD's "Gana extra" row and from the CHILD's notifications — pinned in Tasks 1 and 3.
5. A pay meter whose `pct + discounted_pct` rounds past 100 must still render a bar that fits (green + red ≤ 100) — pinned in Task 3.

## Plan-time refinements of the spec (controller rulings)

- **Counts update client-side; meter and newly unlocked bonus refresh on reload.** After each successful non-bonus completion the deck bumps every `[data-today-counter]`; when the last actionable card is done and a locked bonus card remains, the celebration shows "Bonus desbloqueado" with a **"Ver bonus"** button that reloads the page (the server decides the unlock). Avoids a client-side re-render of cards.
- **Kid page split:** `KidHeader.astro` fills PageLayout's `header` slot; `KidHome.astro` is the body.
- **Prior-day gigs awaiting a parent decision** (old page's `recentSubmittedGigs`) survive as a compact "⏳ N en revisión" chip linking to `/notifications` (count = today's awaiting-approval + prior-day pending). Rejections still arrive as notifications.
- **Payday surface** and **GigsIntroBanner** are dropped from `/dashboard` (payday lives on `/bank`; explainer lives in help/tours), per the spec's removal list.

---

### Task 1: Backend — new-gig notifications + offering timestamps

**Files:**
- Modify: `backend/app/models/notification.py` (add constant)
- Modify: `backend/app/services/notification_service.py` (`_COPY` entry)
- Modify: `backend/app/services/gig_offering_service.py` (helper + 3 call sites)
- Modify: `backend/app/api/routes/gigs.py` (`GigOfferingResponse` fields)
- Test: `backend/tests/test_gig_published_notifications.py` (create)

**Interfaces:**
- Produces: `NotificationType.GIG_PUBLISHED = "gig_published"`; copy key `gig_published` (params `title`, `pesos`); `GigOfferingService._notify_gig_published(db, offering, actor_id) -> int` (never raises); `GigOfferingResponse.created_at: Optional[datetime]`, `GigOfferingResponse.reviewed_at: Optional[datetime]` (consumed by Task 3's `isNewGig`).

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_gig_published_notifications.py`:

```python
"""A gig becoming claimable notifies the kids who may claim it (UX-C1).

Three paths make a gig visible: a parent posts it (create), a parent approves
a kid proposal (review_proposal), or a parent edits a pending proposal live
(update with is_active=True — implicit approval). Recipients: participating
members (active AND parent-approved) whose role the gig allows (default
teen+child), never the actor, never the proposer (who already gets
"propuesta aprobada"), never another family.
"""
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.notification import Notification, NotificationType as NT
from app.models.user import User, UserRole
from app.services.gig_offering_service import GigOfferingService


async def _published_for(db, user_id) -> list[Notification]:
    return list((await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == NT.GIG_PUBLISHED,
        )
    )).scalars().all())


async def _member(db, family_id, email, role, **over) -> User:
    user = User(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0],
        role=role,
        family_id=family_id,
        email_verified=True,
        **over,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _post(db, family_id, parent_id, **over):
    return await GigOfferingService.create(
        db, family_id=family_id, created_by=parent_id,
        title=over.pop("title", "Lavar auto"), points=over.pop("points", 80), **over,
    )


class TestGigPublishedRecipients:
    async def test_parent_post_notifies_kids_not_parents(
        self, db_session, test_family, test_parent_user, test_parent_user_2,
        test_teen_user, test_child_user,
    ):
        await _post(db_session, test_family.id, test_parent_user.id)
        for kid in (test_teen_user, test_child_user):
            rows = await _published_for(db_session, kid.id)
            assert len(rows) == 1
            assert "Lavar auto" in rows[0].title
            assert rows[0].link == "/gigs"
            assert "80" in (rows[0].body or "")
        for parent in (test_parent_user, test_parent_user_2):
            assert await _published_for(db_session, parent.id) == []

    async def test_allowed_roles_limit_recipients(
        self, db_session, test_family, test_parent_user, test_teen_user, test_child_user,
    ):
        await _post(db_session, test_family.id, test_parent_user.id, allowed_roles=["teen"])
        assert len(await _published_for(db_session, test_teen_user.id)) == 1
        assert await _published_for(db_session, test_child_user.id) == []

    async def test_inactive_and_pending_members_skipped(
        self, db_session, test_family, test_parent_user,
    ):
        gone = await _member(db_session, test_family.id, "gone.kid@test.com", UserRole.CHILD, is_active=False)
        waiting = await _member(db_session, test_family.id, "waiting.kid@test.com", UserRole.CHILD, approval_status="pending")
        await _post(db_session, test_family.id, test_parent_user.id)
        assert await _published_for(db_session, gone.id) == []
        assert await _published_for(db_session, waiting.id) == []

    async def test_other_family_never_notified(
        self, db_session, test_family, test_parent_user, other_family,
    ):
        stranger = await _member(db_session, other_family.id, "stranger.kid@test.com", UserRole.TEEN)
        await _post(db_session, test_family.id, test_parent_user.id)
        assert await _published_for(db_session, stranger.id) == []


class TestGigPublishedPaths:
    async def test_approved_proposal_notifies_others_not_proposer(
        self, db_session, test_family, test_parent_user, test_teen_user, test_child_user,
    ):
        proposal = await GigOfferingService.propose(
            db_session, family_id=test_family.id, created_by=test_teen_user.id,
            title="Pintar barda", points=120,
        )
        assert await _published_for(db_session, test_child_user.id) == []
        await GigOfferingService.review_proposal(
            db_session, proposal.id, test_family.id, reviewer_id=test_parent_user.id, approve=True,
        )
        assert len(await _published_for(db_session, test_child_user.id)) == 1
        assert await _published_for(db_session, test_teen_user.id) == []

    async def test_rejected_proposal_notifies_nobody(
        self, db_session, test_family, test_parent_user, test_teen_user, test_child_user,
    ):
        proposal = await GigOfferingService.propose(
            db_session, family_id=test_family.id, created_by=test_teen_user.id,
            title="Pintar barda", points=120,
        )
        await GigOfferingService.review_proposal(
            db_session, proposal.id, test_family.id, reviewer_id=test_parent_user.id, approve=False,
        )
        assert await _published_for(db_session, test_child_user.id) == []

    async def test_implicit_approval_via_update_notifies(
        self, db_session, test_family, test_parent_user, test_teen_user, test_child_user,
    ):
        proposal = await GigOfferingService.propose(
            db_session, family_id=test_family.id, created_by=test_teen_user.id,
            title="Pintar barda", points=120,
        )
        await GigOfferingService.update(
            db_session, proposal.id, test_family.id,
            acting_user_id=test_parent_user.id, is_active=True,
        )
        assert len(await _published_for(db_session, test_child_user.id)) == 1
        assert await _published_for(db_session, test_teen_user.id) == []

    async def test_plain_edit_of_live_gig_does_not_renotify(
        self, db_session, test_family, test_parent_user, test_child_user,
    ):
        gig = await _post(db_session, test_family.id, test_parent_user.id)
        await GigOfferingService.update(
            db_session, gig.id, test_family.id, acting_user_id=test_parent_user.id, points=90,
        )
        assert len(await _published_for(db_session, test_child_user.id)) == 1

    async def test_notification_failure_never_blocks_the_post(
        self, db_session, test_family, test_parent_user, test_child_user,
    ):
        with patch(
            "app.services.notification_service.NotificationService.create_localized",
            side_effect=RuntimeError("smtp down"),
        ):
            gig = await _post(db_session, test_family.id, test_parent_user.id)
        assert gig.id is not None and gig.is_active is True
        assert await _published_for(db_session, test_child_user.id) == []


async def test_offering_list_exposes_timestamps(
    client: AsyncClient, auth_headers, db_session, test_family, test_parent_user,
):
    await _post(db_session, test_family.id, test_parent_user.id)
    r = await client.get("/api/gigs/offerings", headers=auth_headers)
    assert r.status_code == 200
    offering = r.json()[0]["offering"]
    assert offering["created_at"]
    assert "reviewed_at" in offering
```

- [ ] **Step 2: Run to verify they fail**

Run: `…/run-backend-tests-c1.sh tests/test_gig_published_notifications.py`
Expected: FAIL — `AttributeError: type object 'NotificationType' has no attribute 'GIG_PUBLISHED'` at collection (and, once that exists, notifications missing / `created_at` missing).

- [ ] **Step 3: Implement**

`backend/app/models/notification.py` — in `class NotificationType`, after `GIG_COMMENT = "gig_comment"`, add:

```python
    GIG_PUBLISHED = "gig_published"
```

`backend/app/services/notification_service.py` — in `_COPY`, after the `"gig_proposal_rejected"` entry, add:

```python
    "gig_published": {
        "type": NT.GIG_PUBLISHED,
        "title": {"es": "💵 Nuevo: {title}", "en": "💵 New: {title}"},
        "body": {
            "es": "${pesos} MXN · tócalo para apartarlo",
            "en": "${pesos} MXN · tap to claim",
        },
    },
```

`backend/app/services/gig_offering_service.py` — add this static method inside `class GigOfferingService` (right after `create`):

```python
    @staticmethod
    async def _notify_gig_published(
        db: AsyncSession, offering: GigOffering, actor_id: Optional[UUID]
    ) -> int:
        """Tell the kids who may claim it that a gig is on the board (UX-C1).

        Recipients: participating members (active AND parent-approved) whose
        role the gig allows (``allowed_roles``, default teen + child), never
        the actor and never the gig's creator — a proposer already got
        "propuesta aprobada". Best-effort: a failure is logged and never
        fails or rolls back the post. Returns how many were notified.
        """
        import logging

        try:
            from app.models.user import User
            from app.services.notification_service import NotificationService
            from app.services.task_assignment_service import TaskAssignmentService

            allowed = {str(r).lower() for r in (offering.allowed_roles or ["teen", "child"])}
            members = (
                await db.execute(
                    select(User.id, User.role).where(
                        and_(
                            User.family_id == offering.family_id,
                            TaskAssignmentService._participating_member_clause(),
                        )
                    )
                )
            ).all()
            skip = {actor_id, offering.created_by}
            sent = 0
            for user_id, role in members:
                role_value = str(getattr(role, "value", role)).lower()
                if user_id in skip or role_value not in allowed:
                    continue
                await NotificationService.create_localized(
                    db,
                    family_id=offering.family_id,
                    key="gig_published",
                    user_id=user_id,
                    params={"title": offering.title, "pesos": offering.points},
                    link="/gigs",
                )
                sent += 1
            return sent
        except Exception:
            logging.getLogger(__name__).warning(
                "gig_published fan-out failed for offering %s", offering.id, exc_info=True
            )
            return 0
```

Call sites (each directly before that method's final `return offering`):
- In `create(...)`: `await GigOfferingService._notify_gig_published(db, offering, created_by)`
- In `update(...)`: 
  ```python
          if implicit_approval:
              await GigOfferingService._notify_gig_published(db, offering, acting_user_id)
  ```
- In `review_proposal(...)`:
  ```python
          if approve:
              await GigOfferingService._notify_gig_published(db, offering, reviewer_id)
  ```

`backend/app/api/routes/gigs.py` — in `class GigOfferingResponse`, after `created_by: Optional[UUID] = None`, add:

```python
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
```

(`datetime` is already imported at the top of `gigs.py`.)

- [ ] **Step 4: Run to verify they pass**

Run: `…/run-backend-tests-c1.sh tests/test_gig_published_notifications.py tests/test_gig_board.py tests/test_notifications.py`
Expected: all PASS.

- [ ] **Step 5: Mutation checks** — (a) remove `offering.created_by` from `skip`: `test_approved_proposal_notifies_others_not_proposer` must fail. (b) replace `TaskAssignmentService._participating_member_clause()` with `True`: `test_inactive_and_pending_members_skipped` must fail. (c) delete the `update()` call site: `test_implicit_approval_via_update_notifies` must fail. Restore all.

- [ ] **Step 6: Lint + commit**

Run: `cd backend && ruff check app` → clean.

```bash
git add backend/app/models/notification.py backend/app/services/notification_service.py backend/app/services/gig_offering_service.py backend/app/api/routes/gigs.py backend/tests/test_gig_published_notifications.py
git commit -m "feat(gigs): notify eligible kids when a gig goes live; expose offering timestamps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Deck model (`lib/deck.ts`)

**Files:**
- Create: `frontend/src/lib/deck.ts`
- Test: `frontend/test/deck.test.ts`

**Interfaces:**
- Consumes: `GET /api/task-assignments/progress` payload (`assignments[]`, `overdue_assignments[]`, `bonus_unlocked`, `required_completed`, `required_total`; assignment fields `id`, `template_id`, `template_title`, `template_title_es`, `template_points`, `template_is_bonus`, `template_requires_proof`, `status`, `approval_status`, `due_date`, `assigned_date`).
- Produces: `interface DeckCard`, `interface Deck`, `buildDeck(progress: unknown, lang: string): Deck` (used by Tasks 6–8).

- [ ] **Step 1: Write the failing test** — create `frontend/test/deck.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { buildDeck } from "../src/lib/deck";

const a = (over: Record<string, unknown>) => ({
    id: "a",
    template_id: "t",
    template_title: "Chore",
    template_title_es: "Tarea",
    template_points: 10,
    template_is_bonus: false,
    template_requires_proof: false,
    status: "pending",
    approval_status: "none",
    assigned_date: "2026-09-28",
    due_date: null,
    ...over,
});

const progress = (over: Record<string, unknown>) => ({
    required_total: 0,
    required_completed: 0,
    bonus_unlocked: false,
    assignments: [],
    overdue_assignments: [],
    ...over,
});

describe("buildDeck", () => {
    it("returns an empty deck for a missing payload", () => {
        expect(buildDeck(null, "es")).toEqual({ cards: [], doneToday: 0, totalToday: 0, inReview: 0 });
    });

    it("puts overdue first, grouped per chore, completing the oldest instance", () => {
        const deck = buildDeck(progress({
            overdue_assignments: [
                a({ id: "o2", template_id: "dishes", assigned_date: "2026-09-26" }),
                a({ id: "o3", template_id: "bed", assigned_date: "2026-09-27" }),
                a({ id: "o1", template_id: "dishes", assigned_date: "2026-09-25" }),
            ],
            assignments: [a({ id: "r1", template_id: "trash" })],
        }), "es");
        expect(deck.cards.map((c) => c.id)).toEqual(["o1", "o3", "r1"]);
        expect(deck.cards[0]).toMatchObject({ overdue: true, overdueCount: 2 });
        expect(deck.cards[1]).toMatchObject({ overdue: true, overdueCount: 1 });
        expect(deck.cards[2].overdue).toBe(false);
    });

    it("works when only overdue chores exist", () => {
        const deck = buildDeck(progress({ overdue_assignments: [a({ id: "o1" })] }), "es");
        expect(deck.cards.map((c) => c.id)).toEqual(["o1"]);
    });

    it("keeps only pending required chores and localizes titles", () => {
        const deck = buildDeck(progress({
            assignments: [
                a({ id: "r1" }),
                a({ id: "r2", status: "completed" }),
                a({ id: "r3", template_title_es: null, template_title: "Walk dog" }),
            ],
        }), "es");
        expect(deck.cards.map((c) => [c.id, c.title])).toEqual([["r1", "Tarea"], ["r3", "Walk dog"]]);
        expect(buildDeck(progress({ assignments: [a({ id: "r1" })] }), "en").cards[0].title).toBe("Chore");
    });

    it("shows unlocked bonus tasks after required ones", () => {
        const deck = buildDeck(progress({
            bonus_unlocked: true,
            assignments: [a({ id: "b1", template_is_bonus: true }), a({ id: "r1" })],
        }), "es");
        expect(deck.cards.map((c) => c.id)).toEqual(["r1", "b1"]);
        expect(deck.cards[1]).toMatchObject({ isBonus: true, locked: false });
    });

    it("collapses gated bonus tasks into one locked card", () => {
        const deck = buildDeck(progress({
            bonus_unlocked: false,
            assignments: [
                a({ id: "r1" }),
                a({ id: "b1", template_is_bonus: true }),
                a({ id: "b2", template_is_bonus: true }),
            ],
        }), "es");
        expect(deck.cards).toHaveLength(2);
        expect(deck.cards[1]).toMatchObject({ id: "locked", locked: true, lockedCount: 2 });
    });

    it("carries proof and points onto cards", () => {
        const deck = buildDeck(progress({
            assignments: [a({ id: "r1", template_requires_proof: true, template_points: 25 })],
        }), "es");
        expect(deck.cards[0]).toMatchObject({ requiresProof: true, points: 25 });
    });

    it("counts today's progress and items awaiting approval", () => {
        const deck = buildDeck(progress({
            required_total: 5,
            required_completed: 2,
            assignments: [
                a({ id: "x", status: "completed", approval_status: "pending" }),
                a({ id: "y", status: "completed", approval_status: "approved" }),
            ],
        }), "es");
        expect(deck).toMatchObject({ doneToday: 2, totalToday: 5, inReview: 1 });
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run test/deck.test.ts`
Expected: FAIL — cannot resolve `../src/lib/deck`.

- [ ] **Step 3: Implement** — create `frontend/src/lib/deck.ts`:

```ts
/**
 * The swipe deck's cards, built from GET /api/task-assignments/progress
 * (UX-C1). Order: overdue chores (one card per chore, completing the OLDEST
 * instance) → today's required → today's bonus, or one locked card while
 * bonus is gated. Done and awaiting-approval assignments are not cards.
 */
export interface DeckCard {
    /** Assignment id to complete ("locked" for the gated-bonus placeholder). */
    id: string;
    title: string;
    points: number;
    isBonus: boolean;
    requiresProof: boolean;
    overdue: boolean;
    /** Instances behind a grouped overdue card (0 for non-overdue cards). */
    overdueCount: number;
    locked: boolean;
    /** Bonus tasks behind the locked card. */
    lockedCount: number;
}

export interface Deck {
    cards: DeckCard[];
    doneToday: number;
    totalToday: number;
    /** Today's completed assignments waiting for a parent decision. */
    inReview: number;
}

interface Assignment {
    id: string;
    template_id?: string | null;
    template_title?: string | null;
    template_title_es?: string | null;
    template_points?: number | null;
    template_is_bonus?: boolean | null;
    template_requires_proof?: boolean | null;
    status?: string | null;
    approval_status?: string | null;
    due_date?: string | null;
    assigned_date?: string | null;
}

const toCard = (a: Assignment, lang: string, extra: Partial<DeckCard> = {}): DeckCard => ({
    id: String(a.id),
    title: (lang === "es" && a.template_title_es) || a.template_title || "",
    points: a.template_points ?? 0,
    isBonus: Boolean(a.template_is_bonus),
    requiresProof: Boolean(a.template_requires_proof),
    overdue: false,
    overdueCount: 0,
    locked: false,
    lockedCount: 0,
    ...extra,
});

const when = (a: Assignment) => String(a.due_date ?? a.assigned_date ?? "");

export function buildDeck(progress: unknown, lang: string): Deck {
    const p = (progress ?? {}) as Record<string, any>;
    const assignments: Assignment[] = Array.isArray(p.assignments) ? p.assignments : [];
    const overdue: Assignment[] = Array.isArray(p.overdue_assignments) ? p.overdue_assignments : [];

    const groups = new Map<string, Assignment[]>();
    for (const item of overdue) {
        const key = String(item.template_id ?? item.template_title);
        const list = groups.get(key);
        if (list) list.push(item);
        else groups.set(key, [item]);
    }
    const overdueCards = [...groups.values()]
        .map((items) => [...items].sort((x, y) => when(x).localeCompare(when(y))))
        .sort((x, y) => when(x[0]).localeCompare(when(y[0])))
        .map((sorted) => toCard(sorted[0], lang, { overdue: true, overdueCount: sorted.length }));

    const isPending = (a: Assignment) => a.status === "pending";
    const required = assignments.filter((a) => !a.template_is_bonus && isPending(a)).map((a) => toCard(a, lang));
    const bonusPending = assignments.filter((a) => a.template_is_bonus && isPending(a));
    const bonus: DeckCard[] = p.bonus_unlocked
        ? bonusPending.map((a) => toCard(a, lang))
        : bonusPending.length > 0
            ? [{
                id: "locked", title: "", points: 0, isBonus: true, requiresProof: false,
                overdue: false, overdueCount: 0, locked: true, lockedCount: bonusPending.length,
            }]
            : [];

    return {
        cards: [...overdueCards, ...required, ...bonus],
        doneToday: p.required_completed ?? 0,
        totalToday: p.required_total ?? 0,
        inReview: assignments.filter((a) => a.status === "completed" && a.approval_status === "pending").length,
    };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run test/deck.test.ts` → PASS.

- [ ] **Step 5: Mutation checks** — (a) replace `sorted[0]` with `sorted[sorted.length - 1]`: the grouping test must fail. (b) change `p.bonus_unlocked ?` to `true ?`: the locked-card test must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/deck.ts frontend/test/deck.test.ts
git commit -m "feat(deck): pure deck builder over the daily progress payload

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Kid-home view models (`lib/kidHome.ts`)

**Files:**
- Create: `frontend/src/lib/kidHome.ts`
- Test: `frontend/test/kid-home.test.ts`

**Interfaces:**
- Consumes: `GET /api/gigs/offerings` items `{ offering: {id,title,points,is_active,status,allowed_roles,allow_multiple,created_at,reviewed_at}, my_claim, active_claimers[] }` (timestamps from Task 1); `GET /api/bank/chore-paycheck/{id}` (`mode`, `cap_cents`, `pct`, `discounted_pct`, `already_released`).
- Produces: `NEW_GIG_WINDOW_MS`, `isNewGig(offering, now?)`, `interface GigChip`, `claimableGigs(items, role, now?, max?)`, `type PayMeter`, `payMeterView(paycheck)` (used by Task 7).

- [ ] **Step 1: Write the failing test** — create `frontend/test/kid-home.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { claimableGigs, isNewGig, payMeterView } from "../src/lib/kidHome";

const NOW = new Date("2026-09-28T12:00:00Z");
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3600 * 1000).toISOString();

const item = (over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
    offering: {
        id: "g1", title: "Lavar auto", points: 80, is_active: true, status: "approved",
        allowed_roles: null, allow_multiple: false, created_at: hoursAgo(100), reviewed_at: null,
        ...over,
    },
    my_claim: null,
    active_claimers: [],
    ...extra,
});

describe("isNewGig", () => {
    it("is new within 48h of being posted", () => {
        expect(isNewGig({ created_at: hoursAgo(47) }, NOW)).toBe(true);
        expect(isNewGig({ created_at: hoursAgo(49) }, NOW)).toBe(false);
    });
    it("uses the approval time for approved proposals", () => {
        expect(isNewGig({ created_at: hoursAgo(200), reviewed_at: hoursAgo(2) }, NOW)).toBe(true);
    });
    it("is not new without a usable timestamp", () => {
        expect(isNewGig({}, NOW)).toBe(false);
        expect(isNewGig({ created_at: "garbage" }, NOW)).toBe(false);
        expect(isNewGig(null, NOW)).toBe(false);
    });
});

describe("claimableGigs", () => {
    it("keeps active approved gigs the role may claim, newest first, capped", () => {
        const items = Array.from({ length: 8 }, (_, i) => item({ id: `g${i}`, created_at: hoursAgo(i) }));
        const chips = claimableGigs(items, "teen", NOW, 6);
        expect(chips).toHaveLength(6);
        expect(chips[0]).toEqual({ id: "g0", title: "Lavar auto", pesos: 80, isNew: true });
    });
    it("honors allowed_roles", () => {
        const items = [item({ id: "t", allowed_roles: ["teen"] }), item({ id: "all" })];
        expect(claimableGigs(items, "child", NOW).map((g) => g.id)).toEqual(["all"]);
        expect(claimableGigs(items, "teen", NOW).map((g) => g.id).sort()).toEqual(["all", "t"]);
    });
    it("drops gigs I already claimed and single-slot gigs someone else holds", () => {
        const items = [
            item({ id: "mine" }, { my_claim: { status: "claimed" } }),
            item({ id: "taken" }, { active_claimers: ["Sofia"] }),
            item({ id: "multi", allow_multiple: true }, { active_claimers: ["Sofia"] }),
            item({ id: "inactive", is_active: false }),
            item({ id: "pending", status: "pending" }),
        ];
        expect(claimableGigs(items, "teen", NOW).map((g) => g.id)).toEqual(["multi"]);
    });
    it("returns [] for a non-array payload", () => {
        expect(claimableGigs(null, "teen", NOW)).toEqual([]);
    });
});

describe("payMeterView", () => {
    it("shows only for chore_proportional with a positive goal", () => {
        expect(payMeterView({ mode: "flat", cap_cents: 25000 })).toEqual({ show: false });
        expect(payMeterView({ mode: "chore_proportional", cap_cents: 0 })).toEqual({ show: false });
        expect(payMeterView(null)).toEqual({ show: false });
    });
    it("maps the bar segments and release flag", () => {
        expect(payMeterView({
            mode: "chore_proportional", cap_cents: 25000, pct: 45, discounted_pct: 8, already_released: true,
        })).toEqual({ show: true, capCents: 25000, greenPct: 45, redPct: 8, released: true });
    });
    it("never lets the bar overflow", () => {
        const m = payMeterView({ mode: "chore_proportional", cap_cents: 100, pct: 96, discounted_pct: 7 });
        expect(m.show && m.greenPct + m.redPct).toBe(100);
        const n = payMeterView({ mode: "chore_proportional", cap_cents: 100, pct: 140, discounted_pct: -5 });
        expect(n).toMatchObject({ greenPct: 100, redPct: 0 });
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run test/kid-home.test.ts`
Expected: FAIL — cannot resolve `../src/lib/kidHome`.

- [ ] **Step 3: Implement** — create `frontend/src/lib/kidHome.ts`:

```ts
/**
 * View models for the kid home (UX-C1): which gigs to show in "Gana extra",
 * which are "Nuevo", and the weekly pay meter. Pure — vitest-covered.
 */
export const NEW_GIG_WINDOW_MS = 48 * 3600 * 1000;

/** When a gig reached the board: approval time for proposals, else creation. */
function publishedAt(offering: any): number | null {
    const raw = offering?.reviewed_at ?? offering?.created_at;
    if (!raw) return null;
    const t = new Date(raw).getTime();
    return Number.isNaN(t) ? null : t;
}

export function isNewGig(offering: any, now: Date = new Date()): boolean {
    const t = publishedAt(offering);
    return t !== null && now.getTime() - t < NEW_GIG_WINDOW_MS;
}

export interface GigChip {
    id: string;
    title: string;
    pesos: number;
    isNew: boolean;
}

/** Active, approved gigs this role may claim right now, newest first. */
export function claimableGigs(items: unknown, role: string, now: Date = new Date(), max = 6): GigChip[] {
    if (!Array.isArray(items)) return [];
    return items
        .filter((item: any) => {
            const o = item?.offering;
            if (!o || !o.is_active || (o.status ?? "approved") !== "approved") return false;
            if (Array.isArray(o.allowed_roles) && o.allowed_roles.length > 0 && !o.allowed_roles.includes(role)) {
                return false;
            }
            if (item.my_claim) return false;
            const takenBy = Array.isArray(item.active_claimers) ? item.active_claimers : [];
            return Boolean(o.allow_multiple) || takenBy.length === 0;
        })
        .sort((x: any, y: any) => (publishedAt(y.offering) ?? 0) - (publishedAt(x.offering) ?? 0))
        .slice(0, max)
        .map((item: any) => ({
            id: String(item.offering.id),
            title: item.offering.title,
            pesos: item.offering.points,
            isNew: isNewGig(item.offering, now),
        }));
}

export type PayMeter =
    | { show: false }
    | { show: true; capCents: number; greenPct: number; redPct: number; released: boolean };

const clampPct = (n: unknown) => {
    const v = Math.round(Number(n));
    return Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : 0;
};

/** Weekly chore-paycheck meter: goal + bar only — never a moving $ figure. */
export function payMeterView(paycheck: any): PayMeter {
    if (paycheck?.mode !== "chore_proportional" || !((paycheck?.cap_cents ?? 0) > 0)) {
        return { show: false };
    }
    const greenPct = clampPct(paycheck.pct);
    const redPct = Math.min(clampPct(paycheck.discounted_pct), 100 - greenPct);
    return {
        show: true,
        capCents: paycheck.cap_cents,
        greenPct,
        redPct,
        released: Boolean(paycheck.already_released),
    };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run test/kid-home.test.ts` → PASS.

- [ ] **Step 5: Mutation checks** — (a) change `< NEW_GIG_WINDOW_MS` to `<= NEW_GIG_WINDOW_MS * 2`: the 49h case must fail. (b) delete `, 100 - greenPct` (making `redPct` unbounded): the overflow test must fail. (c) delete the `allowed_roles` check: the allowed-roles test must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/kidHome.ts frontend/test/kid-home.test.ts
git commit -m "feat(kid-home): gig chips, new-gig window and pay meter view models

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: JSON mode for `/api/assignments/complete`

**Files:**
- Create: `frontend/src/lib/completeMessages.ts`
- Modify: `frontend/src/pages/api/assignments/complete.ts` (full replacement below)
- Test: `frontend/test/complete-route.test.ts`

**Interfaces:**
- Produces: `completeErrorMessage(status, detail, es)`, `completeSuccessMessage(assignment, es)`; the route answers requests with `Accept: application/json` with JSON `{ ok: true, message, approval_status }` (200) or `{ ok: false, message }` (backend status / 400 / 401 / 500). Form posts keep the 302 + flash-cookie behavior unchanged. Consumed by Task 6.

- [ ] **Step 1: Write the failing test** — create `frontend/test/complete-route.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "../src/pages/api/assignments/complete";
import { completeErrorMessage } from "../src/lib/completeMessages";

const cookies = (vals: Record<string, string>) => ({
    get: (k: string) => (k in vals ? { value: vals[k] } : undefined),
});

function req(fields: Record<string, string>, json = true): Request {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);
    return new Request("http://localhost/api/assignments/complete", {
        method: "POST",
        body: fd,
        headers: json ? { accept: "application/json" } : {},
    });
}

const backend = (status: number, body: unknown) =>
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

const call = (request: Request, c = cookies({ access_token: "t", lang: "es" })) =>
    POST({ request, cookies: c, redirect: () => new Response(null) } as any);

afterEach(() => vi.unstubAllGlobals());

describe("POST /api/assignments/complete — JSON mode", () => {
    it("returns ok + a friendly message on success", async () => {
        vi.stubGlobal("fetch", backend(200, { template_title: "Lavar", template_title_es: "Lavar trastes", approval_status: "pending" }));
        const res = await call(req({ assignment_id: "a1" }));
        expect(res.status).toBe(200);
        const body = await res.json();
        expect(body).toMatchObject({ ok: true, approval_status: "pending" });
        expect(body.message).toContain("Lavar trastes");
    });

    it("maps a backend 4xx to the backend status with friendly copy", async () => {
        vi.stubGlobal("fetch", backend(400, { detail: "Complete all mandatory tasks first" }));
        const res = await call(req({ assignment_id: "a1" }));
        expect(res.status).toBe(400);
        const body = await res.json();
        expect(body.ok).toBe(false);
        expect(body.message).toContain("obligatorias");
    });

    it("rejects a missing assignment id with 400", async () => {
        vi.stubGlobal("fetch", backend(200, {}));
        const res = await call(req({}));
        expect(res.status).toBe(400);
        expect((await res.json()).ok).toBe(false);
    });

    it("answers 401 JSON without a session", async () => {
        const res = await call(req({ assignment_id: "a1" }), cookies({}));
        expect(res.status).toBe(401);
        expect((await res.json()).ok).toBe(false);
    });

    it("answers 500 JSON when the backend is unreachable", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED"); }));
        const res = await call(req({ assignment_id: "a1" }));
        expect(res.status).toBe(500);
        expect((await res.json()).ok).toBe(false);
    });
});

describe("POST /api/assignments/complete — form mode (unchanged)", () => {
    it("still redirects with a flash cookie", async () => {
        vi.stubGlobal("fetch", backend(200, { template_title: "Lavar", approval_status: "approved" }));
        const res = await call(req({ assignment_id: "a1", next: "/parent" }, false));
        expect(res.status).toBe(302);
        expect(res.headers.get("location")).toBe("/parent");
        expect(res.headers.get("set-cookie")).toContain("flash=");
    });
});

describe("completeErrorMessage", () => {
    it("picks a side of bilingual backend copy", () => {
        expect(completeErrorMessage(400, "Hola / Hello", true)).toBe("Hola");
        expect(completeErrorMessage(400, "Hola / Hello", false)).toBe("Hello");
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run test/complete-route.test.ts`
Expected: FAIL — cannot resolve `../src/lib/completeMessages`.

- [ ] **Step 3: Implement** — create `frontend/src/lib/completeMessages.ts`:

```ts
/**
 * Kid-facing copy for completing an assignment. Never surface the raw backend
 * `detail` (English, technical); map known cases to bilingual copy. Shared by
 * the form (302 + flash) and JSON (deck) modes of /api/assignments/complete.
 */
export function completeErrorMessage(status: number, detail: string, es: boolean): string {
    if (detail.includes(" / ")) {
        // Backend already ships bilingual "es / en" copy — pick a side.
        const [esPart, enPart] = detail.split(" / ");
        return es ? esPart : (enPart ?? esPart);
    }
    if (/cannot be completed/i.test(detail) && /completed/i.test(detail)) {
        return es
            ? "¡Esa tarea ya estaba registrada! Tus puntos ya cuentan."
            : "That task was already saved! Your points are already counted.";
    }
    if (/mandatory/i.test(detail)) {
        return es
            ? "Primero termina tus tareas obligatorias (incluye las atrasadas)."
            : "Finish your required chores first (including overdue ones).";
    }
    if (/proof text/i.test(detail)) {
        return es ? "Cuéntanos qué hiciste para enviar este gig." : "Tell us what you did to submit this gig.";
    }
    if (status >= 400 && status < 500) {
        return es ? "No se pudo guardar la tarea. Intenta de nuevo." : "Couldn't save the task. Please try again.";
    }
    return es ? "Algo salió mal. Intenta de nuevo en un momento." : "Something went wrong. Please try again in a moment.";
}

export function completeSuccessMessage(assignment: any, es: boolean): string {
    const title = (es && assignment?.template_title_es) || assignment?.template_title || "";
    // approval_status alone is authoritative: auto-approved gigs (trust
    // streak / AI validation) come back "approved" with points credited.
    if (!title) return "🎉";
    return assignment?.approval_status === "pending"
        ? (es ? `"${title}" enviada para aprobación 🎉` : `"${title}" submitted for approval 🎉`)
        : (es ? `¡"${title}" completada! 🎉` : `"${title}" completed! 🎉`);
}
```

Replace `frontend/src/pages/api/assignments/complete.ts` entirely with:

```ts
import type { APIRoute } from "astro";

import { completeErrorMessage, completeSuccessMessage } from "../../../lib/completeMessages";

/**
 * POST /api/assignments/complete — marks an assignment completed.
 *
 * Two response modes:
 * - Form posts (default): 302 back to `next` with a flash cookie (legacy
 *   pages).
 * - `Accept: application/json` (the swipe deck, UX-C1): JSON
 *   `{ ok, message, approval_status? }` with the backend's status, so the
 *   deck can keep a card on failure instead of navigating.
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const wantsJson = (request.headers.get("accept") ?? "").includes("application/json");
    const json = (status: number, body: Record<string, unknown>) =>
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    const token = cookies.get("access_token")?.value;
    const es = (cookies.get("lang")?.value ?? "es") === "es";

    if (!token) {
        return wantsJson
            ? json(401, { ok: false, message: es ? "Inicia sesión de nuevo." : "Please sign in again." })
            : new Response(null, { status: 302, headers: { Location: "/login" } });
    }

    let returnTo = "/dashboard";
    try {
        const formData = await request.formData();
        const assignmentId = formData.get("assignment_id")?.toString();
        const proofTextRaw = formData.get("proof_text")?.toString();
        const proofText = proofTextRaw && proofTextRaw.trim().length > 0 ? proofTextRaw.trim() : null;
        const proofImageRaw = formData.get("proof_image_url")?.toString();
        const proofImageUrl = proofImageRaw && proofImageRaw.trim().length > 0 ? proofImageRaw.trim() : null;
        // Where to land after completing — parents complete their own tasks
        // from /parent, kids from /dashboard. Same-origin relative paths only:
        // reject protocol-relative (//) and backslashes (browsers normalize
        // "\" to "/" in Location, so "/\evil.com" would become "//evil.com").
        const nextRaw = formData.get("next")?.toString() ?? "";
        returnTo =
            nextRaw.startsWith("/") && !nextRaw.startsWith("//") && !nextRaw.includes("\\")
                ? nextRaw
                : "/dashboard";

        if (!assignmentId) {
            const msg = es ? "Falta la tarea." : "Assignment ID is required";
            if (wantsJson) return json(400, { ok: false, message: msg });
            const headers = new Headers({ Location: returnTo });
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent(msg)}; Path=/`);
            return new Response(null, { status: 302, headers });
        }

        const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://backend:8000";
        const response = await fetch(`${apiUrl}/api/task-assignments/${assignmentId}/complete`, {
            method: "PATCH",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ proof_text: proofText, proof_image_url: proofImageUrl }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}) as any);
            const detail = typeof error?.detail === "string" ? error.detail : "";
            const msg = completeErrorMessage(response.status, detail, es);
            if (wantsJson) return json(response.status, { ok: false, message: msg });
            const headers = new Headers({ Location: returnTo });
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent(msg)}; Path=/`);
            return new Response(null, { status: 302, headers });
        }

        const assignment = await response.json().catch(() => ({}) as any);
        const msg = completeSuccessMessage(assignment, es);
        if (wantsJson) {
            return json(200, { ok: true, message: msg, approval_status: assignment?.approval_status ?? null });
        }
        // Success flash drives the page's celebration ([data-flash-success]).
        const headers = new Headers({ Location: returnTo });
        headers.append("Set-Cookie", `flash=${encodeURIComponent(msg)}; Path=/; Max-Age=15`);
        return new Response(null, { status: 302, headers });
    } catch (e) {
        console.error("Complete assignment error:", e);
        const msg = completeErrorMessage(500, "", es);
        if (wantsJson) return json(500, { ok: false, message: msg });
        const headers = new Headers({ Location: returnTo });
        headers.append("Set-Cookie", `flash_error=${encodeURIComponent(msg)}; Path=/`);
        return new Response(null, { status: 302, headers });
    }
};
```

(Behavior note: the old success path read the language as `lang === "es"` (default English) while errors defaulted to Spanish; both now default to Spanish, matching the project-wide ES default.)

- [ ] **Step 4: Run checks**

Run: `cd frontend && npx vitest run && npx astro check` → all PASS, 0 errors.

- [ ] **Step 5: Mutation checks** — (a) make `wantsJson` always `false`: the JSON success test must fail. (b) in the JSON error branch return status `200`: the 4xx test must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/completeMessages.ts frontend/src/pages/api/assignments/complete.ts frontend/test/complete-route.test.ts
git commit -m "feat(assignments): JSON mode for the complete proxy (deck), shared copy helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `celebrate.ts` + EnablePushButton `label` prop

**Files:**
- Create: `frontend/src/lib/celebrate.ts`
- Modify: `frontend/src/components/EnablePushButton.astro` (add `label` prop)

**Interfaces:**
- Produces: `fireConfetti(): void`, `celebrate(): void` (confetti + `navigator.vibrate(30)`; both no-ops under `prefers-reduced-motion` / missing APIs); `EnablePushButton` prop `label?: string` (button text override). Consumed by Tasks 6–7.

- [ ] **Step 1: Create `frontend/src/lib/celebrate.ts`** — move the confetti implementation verbatim from `frontend/src/pages/dashboard.astro` (the `function fireConfetti() { … }` block at the top of the first `<script>`; do NOT delete it from dashboard.astro yet — Task 7 rewrites that file):

```ts
/**
 * Lightweight, dependency-free confetti burst + a short haptic buzz, used when
 * a member empties their deck (UX-C1). Both respect reduced-motion / missing
 * APIs and never throw.
 */
export function fireConfetti(): void {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (document.getElementById("confetti-canvas")) return;
    const canvas = document.createElement("canvas");
    canvas.id = "confetti-canvas";
    canvas.style.cssText = "position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:9999";
    document.body.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    if (!ctx) { canvas.remove(); return; }
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const colors = ["#4FB8E6", "#FFC857", "#6BCB77", "#FF6B6B", "#A78BFA"];
    const parts = Array.from({ length: 90 }, () => ({
        x: canvas.width / 2,
        y: canvas.height / 3,
        vx: (Math.random() - 0.5) * 14,
        vy: Math.random() * -15 - 4,
        size: Math.random() * 7 + 4,
        color: colors[Math.floor(Math.random() * colors.length)],
        rot: Math.random() * Math.PI,
        vr: (Math.random() - 0.5) * 0.3,
    }));
    let frame = 0;
    const tick = () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        parts.forEach((p) => {
            p.vy += 0.4; // gravity
            p.x += p.vx; p.y += p.vy; p.rot += p.vr;
            ctx.save();
            ctx.translate(p.x, p.y); ctx.rotate(p.rot);
            ctx.fillStyle = p.color;
            ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size);
            ctx.restore();
        });
        frame++;
        if (frame < 110) requestAnimationFrame(tick);
        else canvas.remove();
    };
    requestAnimationFrame(tick);
}

export function celebrate(): void {
    fireConfetti();
    try {
        if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) navigator.vibrate?.(30);
    } catch {
        // vibrate is optional (iOS Safari lacks it)
    }
}
```

- [ ] **Step 2: EnablePushButton label** — in `frontend/src/components/EnablePushButton.astro`:
  - add `label?: string;` to `interface Props` and destructure it (`const { lang, userId, class: rootClass, label } = Astro.props;` — keep whatever names the file already uses for `userId` and `class`);
  - change the button's text from `{L.enable}` to `{label ?? L.enable}`.
  No other change (the script's status strings keep using `L`).

- [ ] **Step 3: Run checks**

Run: `cd frontend && npx astro check && npx vitest run` → 0 errors, all PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/celebrate.ts frontend/src/components/EnablePushButton.astro
git commit -m "refactor: extract celebrate() for the deck; EnablePushButton label prop

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `TaskDeck.astro` — the shared swipe deck

**Files:**
- Create: `frontend/src/components/deck/TaskDeck.astro`

**Interfaces:**
- Consumes: `DeckCard` (Task 2); JSON mode of `/api/assignments/complete` (Task 4); `/api/assignments/proof-upload` (existing, returns `{ proof_image_url }`, 413 too big, 415 bad type); `showToast(message, type, ms)` from `lib/toast.ts`; `celebrate()` (Task 5).
- Produces: component props `{ cards: DeckCard[]; lang: "en" | "es"; variant?: "full" | "compact"; choreMode?: boolean; heading: string; counter?: { done: number; total: number; suffix: string } | null }`. Emits DOM events on the deck root (bubbling): `ftm:deck-completed` (`detail: { isBonus }`) and `ftm:deck-empty`. Updates every `[data-today-counter]` element (reads `data-done`, `data-total`, `data-suffix`) after each successful non-bonus completion.

- [ ] **Step 1: Create the component** — `frontend/src/components/deck/TaskDeck.astro`:

```astro
---
/**
 * One-card-at-a-time task deck (UX-C1), used by the kid home and the parent's
 * "Mis tareas de hoy". Swipe right / "Hecho →" / → completes the top card;
 * swipe left / "← Después" / ← sends it to the back (this page session only).
 * Proof-required and bonus cards open the photo/note sheet first. A card is
 * removed only after the server says OK; failures spring it back with a toast.
 */
import type { DeckCard } from "../../lib/deck";

interface Props {
    cards: DeckCard[];
    lang: "en" | "es";
    variant?: "full" | "compact";
    choreMode?: boolean;
    heading: string;
    counter?: { done: number; total: number; suffix: string } | null;
}
const { cards, lang, variant = "full", choreMode = false, heading, counter = null } = Astro.props;
const es = lang === "es";

const L = {
    later: es ? "Después" : "Later",
    done: es ? "Hecho" : "Done",
    overdue: es ? "Atrasada" : "Overdue",
    photo: es ? "📷 requiere foto" : "📷 photo needed",
    pay: es ? "Cuenta para tu pago de la semana" : "Counts toward this week's pay",
    lockedTitle: es ? "Termina las de hoy" : "Finish today's first",
    lockedBody: (n: number) => (es ? `${n} bonus te esperan` : `${n} bonus waiting`),
    idle: es ? "Nada pendiente hoy" : "Nothing due today",
    seeBonus: es ? "Ver bonus" : "See bonus",
    cancel: es ? "Cancelar" : "Cancel",
    send: es ? "Enviar" : "Send",
};
const i18n = {
    of: es ? "de" : "of",
    dayDone: es ? "¡Día completo!" : "Day complete!",
    bonusUnlocked: es ? "Bonus desbloqueado" : "Bonus unlocked",
    failed: es ? "No se pudo guardar. Intenta de nuevo." : "Couldn't save. Try again.",
    network: es ? "Sin conexión. Intenta de nuevo." : "No connection. Try again.",
    photoRequired: es ? "📸 Foto del trabajo terminado (requerida)" : "📸 Photo of the finished work (required)",
    photoOptional: es ? "📸 Foto (opcional)" : "📸 Photo (optional)",
    noteBonus: es ? "¿Qué hiciste? (requerido)" : "What did you do? (required)",
    noteOptional: es ? "Nota (opcional)" : "Note (optional)",
    needNote: es ? "Cuéntanos qué hiciste." : "Tell us what you did.",
    needPhoto: es ? "📸 Esta tarea requiere una foto." : "📸 This task needs a photo.",
    uploading: es ? "Subiendo…" : "Uploading…",
    tooBig: es ? "📸 Foto muy pesada (máx 15MB)." : "📸 Photo too large (max 15MB).",
    badType: es ? "Formato no soportado (JPEG, PNG o WebP)." : "Unsupported format (JPEG, PNG or WebP).",
    uploadFailed: es ? "Error al subir la foto" : "Upload failed",
};
const stackHeight = variant === "compact" ? "h-40" : "h-44";
---

<section
    data-deck
    data-variant={variant}
    data-tour={variant === "full" ? "today-tasks" : undefined}
    aria-label={heading}
    tabindex="0"
    class="outline-none focus-visible:ring-2 focus-visible:ring-brand-sky rounded-2xl"
>
    <div class="flex items-baseline justify-between px-1 mb-2 gap-2">
        <h2 class="text-xs font-extrabold uppercase tracking-wider text-brand-ink-soft">
            {heading}
            {counter && (
                <span
                    class="ml-1 normal-case tracking-normal font-bold"
                    data-today-counter
                    data-done={counter.done}
                    data-total={counter.total}
                    data-suffix={counter.suffix}
                >· {counter.done}/{counter.total}{counter.suffix ? ` ${counter.suffix}` : ""}</span>
            )}
        </h2>
        <span class="text-xs font-bold text-brand-ink-soft" data-deck-pos></span>
    </div>

    <div class={`relative ${stackHeight}`} data-deck-stack hidden={cards.length === 0}>
        {cards.map((c, i) => (
            <article
                data-deck-card
                data-id={c.id}
                data-title={c.title}
                data-locked={c.locked ? "1" : "0"}
                data-proof={c.requiresProof ? "1" : "0"}
                data-bonus={c.isBonus ? "1" : "0"}
                class="absolute inset-0 rounded-[var(--radius-card)] border-2 border-brand-ink bg-white p-4 shadow-[var(--shadow-card)] select-none touch-pan-y will-change-transform"
                style={`z-index:${cards.length - i}`}
            >
                <div class="flex flex-wrap gap-1.5">
                    {c.overdue && (
                        <span class="text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-red-100 text-red-700">
                            {L.overdue}{c.overdueCount > 1 ? ` ×${c.overdueCount}` : ""}
                        </span>
                    )}
                    {c.isBonus && !c.locked && (
                        <span class="text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">Bonus</span>
                    )}
                    {!c.locked && c.points > 0 && (
                        <span class="text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">+{c.points} pts</span>
                    )}
                    {c.requiresProof && (
                        <span class="text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-sky-100 text-sky-700">{L.photo}</span>
                    )}
                </div>
                {c.locked ? (
                    <>
                        <p class="mt-2 text-lg font-extrabold leading-tight text-brand-ink">🔒 {L.lockedTitle}</p>
                        <p class="text-xs text-brand-ink-soft mt-0.5">{L.lockedBody(c.lockedCount)}</p>
                    </>
                ) : (
                    <>
                        <p class="mt-2 text-lg font-extrabold leading-tight text-brand-ink line-clamp-2">{c.title}</p>
                        {choreMode && !c.isBonus && <p class="text-xs text-brand-ink-soft mt-0.5">{L.pay}</p>}
                    </>
                )}
                <div class="absolute left-4 right-4 bottom-4 flex gap-2">
                    <button type="button" data-deck-later class="flex-1 rounded-xl bg-brand-cream-deep py-2.5 text-sm font-bold text-brand-ink disabled:opacity-40">← {L.later}</button>
                    {!c.locked && (
                        <button type="button" data-deck-done class="flex-1 rounded-xl bg-brand-mint-deep py-2.5 text-sm font-extrabold text-white">{L.done} →</button>
                    )}
                </div>
            </article>
        ))}
    </div>
    <p class="mt-3 text-center text-xs tracking-[0.3em] text-brand-ink-soft" data-deck-dots aria-hidden="true"></p>

    <div data-deck-empty class={cards.length ? "hidden" : ""}>
        <div data-deck-idle class="rounded-2xl border border-brand-ink/10 bg-white p-5 text-center text-sm font-semibold text-brand-ink-soft">
            {L.idle}
        </div>
        <div data-deck-party class="hidden text-center py-4">
            <p class="text-4xl" aria-hidden="true">🔥</p>
            <p class="font-extrabold text-lg text-brand-ink" data-deck-party-title></p>
            <p class="text-sm text-brand-ink-soft" data-deck-party-sub></p>
            <button type="button" data-deck-reload class="hidden mt-3 rounded-xl bg-brand-sun px-4 py-2 text-sm font-extrabold text-brand-ink border-2 border-brand-ink shadow-[var(--shadow-card)]">{L.seeBonus}</button>
        </div>
    </div>

    <dialog data-proof-dialog class="rounded-2xl p-0 backdrop:bg-black/40 max-w-md w-[calc(100%-2rem)] border-2 border-brand-ink bg-brand-cream">
        <div class="p-5 space-y-3">
            <h3 class="text-lg font-bold text-brand-ink" data-proof-title></h3>
            <label class="block text-xs text-brand-ink-soft" data-proof-photo-label for="deck-proof-file"></label>
            <input id="deck-proof-file" type="file" accept="image/*" data-proof-file class="block w-full text-sm" />
            <textarea data-proof-text rows="3" maxlength="4000" class="w-full rounded-xl border border-brand-ink/20 bg-white p-2 text-sm"></textarea>
            <p data-proof-status class="text-xs text-brand-ink-soft" aria-live="polite"></p>
            <div class="flex justify-end gap-2">
                <button type="button" data-proof-cancel class="px-4 py-2 rounded-lg bg-brand-cream-deep text-brand-ink font-semibold text-sm">{L.cancel}</button>
                <button type="button" data-proof-submit class="px-4 py-2 rounded-lg bg-brand-mint-deep text-white font-semibold text-sm shadow-[var(--shadow-card)]">{L.send}</button>
            </div>
        </div>
    </dialog>

    <script type="application/json" data-deck-i18n set:html={JSON.stringify(i18n)}></script>
</section>

<script>
    import { showToast } from "../../lib/toast";
    import { celebrate } from "../../lib/celebrate";

    const SWIPE_RATIO = 0.3;

    function bumpCounters() {
        document.querySelectorAll<HTMLElement>("[data-today-counter]").forEach((el) => {
            const done = Math.min(Number(el.dataset.done ?? 0) + 1, Number(el.dataset.total ?? 0));
            el.dataset.done = String(done);
            const suffix = el.dataset.suffix ? ` ${el.dataset.suffix}` : "";
            const prefix = el.textContent?.trim().startsWith("·") ? "· " : "";
            el.textContent = `${prefix}${done}/${el.dataset.total}${suffix}`;
        });
    }

    function initDeck(root: HTMLElement) {
        if (root.dataset.deckReady) return;
        root.dataset.deckReady = "1";
        const t: Record<string, string> = JSON.parse(
            root.querySelector<HTMLScriptElement>("script[data-deck-i18n]")?.textContent || "{}",
        );
        const stack = root.querySelector<HTMLElement>("[data-deck-stack]")!;
        const pos = root.querySelector<HTMLElement>("[data-deck-pos]");
        const dots = root.querySelector<HTMLElement>("[data-deck-dots]");
        const emptyBox = root.querySelector<HTMLElement>("[data-deck-empty]")!;
        const idle = root.querySelector<HTMLElement>("[data-deck-idle]");
        const party = root.querySelector<HTMLElement>("[data-deck-party]");
        const partyTitle = root.querySelector<HTMLElement>("[data-deck-party-title]");
        const partySub = root.querySelector<HTMLElement>("[data-deck-party-sub]");
        const reloadBtn = root.querySelector<HTMLButtonElement>("[data-deck-reload]");
        let order: HTMLElement[] = [...root.querySelectorAll<HTMLElement>("[data-deck-card]")];
        let busy = false;

        function layout() {
            order.forEach((card, i) => {
                card.style.zIndex = String(order.length - i);
                card.hidden = i > 2;
                card.style.transition = "transform 200ms ease, opacity 200ms ease";
                card.style.transform = i === 0 ? "" : `translate(${i * 6}px, ${i * 6}px)`;
                card.style.opacity = i === 0 ? "1" : "0.55";
                card.style.pointerEvents = i === 0 ? "auto" : "none";
                card.setAttribute("aria-hidden", i === 0 ? "false" : "true");
                card.querySelectorAll("button").forEach((b) => (b.tabIndex = i === 0 ? 0 : -1));
            });
            const laterBtn = order[0]?.querySelector<HTMLButtonElement>("[data-deck-later]");
            if (laterBtn) laterBtn.disabled = order.length < 2;
            if (pos) pos.textContent = order.length ? `1 ${t.of} ${order.length}` : "";
            if (dots) dots.textContent = order.length > 1 ? "●" + "○".repeat(Math.min(order.length - 1, 6)) : "";
        }

        const springBack = (card: HTMLElement) => {
            card.style.transition = "transform 200ms ease";
            card.style.transform = "";
        };

        function later() {
            if (busy || order.length < 2) return;
            order.push(order.shift()!);
            layout();
        }

        function flyOff(card: HTMLElement) {
            card.style.transition = "transform 250ms ease, opacity 250ms ease";
            card.style.transform = "translateX(120%) rotate(12deg)";
            card.style.opacity = "0";
            setTimeout(() => card.remove(), 260);
        }

        function finish(bonusUnlocked: boolean) {
            stack.hidden = true;
            if (dots) dots.textContent = "";
            if (pos) pos.textContent = "";
            emptyBox.classList.remove("hidden");
            idle?.classList.add("hidden");
            party?.classList.remove("hidden");
            if (partyTitle) partyTitle.textContent = t.dayDone;
            if (partySub) partySub.textContent = bonusUnlocked ? t.bonusUnlocked : "";
            reloadBtn?.classList.toggle("hidden", !bonusUnlocked);
            celebrate();
            root.dispatchEvent(new CustomEvent("ftm:deck-empty", { bubbles: true }));
        }

        async function complete(card: HTMLElement, proofText = "", proofImageUrl = "") {
            busy = true;
            const fd = new FormData();
            fd.append("assignment_id", card.dataset.id ?? "");
            fd.append("proof_text", proofText);
            fd.append("proof_image_url", proofImageUrl);
            try {
                const r = await fetch("/api/assignments/complete", {
                    method: "POST",
                    body: fd,
                    headers: { Accept: "application/json" },
                });
                const body = await r.json().catch(() => ({}) as any);
                if (!r.ok || !body.ok) {
                    springBack(card);
                    showToast(body.message || t.failed, "error");
                    return;
                }
                const isBonus = card.dataset.bonus === "1";
                order = order.filter((c) => c !== card);
                flyOff(card);
                showToast(body.message || "🎉", "success", 2500);
                if (!isBonus) bumpCounters();
                root.dispatchEvent(new CustomEvent("ftm:deck-completed", { bubbles: true, detail: { isBonus } }));
                const actionable = order.filter((c) => c.dataset.locked !== "1");
                if (actionable.length === 0) {
                    finish(order.length > 0);
                } else {
                    order = [...actionable, ...order.filter((c) => c.dataset.locked === "1")];
                    layout();
                }
            } catch {
                springBack(card);
                showToast(t.network, "error");
            } finally {
                busy = false;
            }
        }

        // ── Proof sheet ──────────────────────────────────────────────
        const dialog = root.querySelector<HTMLDialogElement>("[data-proof-dialog]");
        const fileInput = root.querySelector<HTMLInputElement>("[data-proof-file]");
        const textInput = root.querySelector<HTMLTextAreaElement>("[data-proof-text]");
        const status = root.querySelector<HTMLElement>("[data-proof-status]");
        const photoLabel = root.querySelector<HTMLElement>("[data-proof-photo-label]");
        const proofTitle = root.querySelector<HTMLElement>("[data-proof-title]");
        let proofCard: HTMLElement | null = null;

        function openProof(card: HTMLElement) {
            if (!dialog) return;
            proofCard = card;
            const isBonus = card.dataset.bonus === "1";
            if (proofTitle) proofTitle.textContent = card.dataset.title ?? "";
            if (photoLabel) photoLabel.textContent = card.dataset.proof === "1" ? t.photoRequired : t.photoOptional;
            if (textInput) {
                textInput.value = "";
                textInput.placeholder = isBonus ? t.noteBonus : t.noteOptional;
            }
            if (fileInput) fileInput.value = "";
            if (status) {
                status.textContent = "";
                status.classList.remove("text-red-600");
            }
            dialog.showModal();
        }

        const cancelProof = () => {
            if (proofCard) springBack(proofCard);
            proofCard = null;
        };
        root.querySelector("[data-proof-cancel]")?.addEventListener("click", () => {
            dialog?.close();
            cancelProof();
        });
        dialog?.addEventListener("cancel", cancelProof);

        root.querySelector("[data-proof-submit]")?.addEventListener("click", async () => {
            if (!proofCard || busy) return;
            const card = proofCard;
            const fail = (msg: string) => {
                if (status) {
                    status.textContent = msg;
                    status.classList.add("text-red-600");
                }
            };
            const text = textInput?.value.trim() ?? "";
            if (card.dataset.bonus === "1" && !text) return fail(t.needNote);
            if (card.dataset.proof === "1" && !fileInput?.files?.length) return fail(t.needPhoto);
            let imageUrl = "";
            if (fileInput?.files?.length) {
                if (status) {
                    status.textContent = t.uploading;
                    status.classList.remove("text-red-600");
                }
                try {
                    const up = new FormData();
                    up.append("file", fileInput.files[0]);
                    const r = await fetch("/api/assignments/proof-upload", { method: "POST", body: up });
                    if (!r.ok) {
                        return fail(r.status === 413 ? t.tooBig : r.status === 415 ? t.badType : `${t.uploadFailed} (${r.status})`);
                    }
                    imageUrl = (await r.json()).proof_image_url ?? "";
                } catch {
                    return fail(t.network);
                }
            }
            proofCard = null;
            dialog?.close();
            await complete(card, text, imageUrl);
        });

        function done() {
            const card = order[0];
            if (!card || busy || card.dataset.locked === "1") return;
            if (card.dataset.proof === "1" || card.dataset.bonus === "1") openProof(card);
            else void complete(card);
        }

        // ── Buttons, keys, swipe ─────────────────────────────────────
        root.addEventListener("click", (e) => {
            const target = e.target as HTMLElement;
            if (target.closest("[data-deck-later]")) later();
            else if (target.closest("[data-deck-done]")) done();
            else if (target.closest("[data-deck-reload]")) location.reload();
        });
        root.addEventListener("keydown", (e) => {
            if ((e.target as HTMLElement).closest("dialog")) return;
            if (e.key === "ArrowRight") { e.preventDefault(); done(); }
            else if (e.key === "ArrowLeft") { e.preventDefault(); later(); }
        });

        let startX = 0;
        let dx = 0;
        let dragging: HTMLElement | null = null;
        stack.addEventListener("pointerdown", (e) => {
            const target = e.target as HTMLElement;
            const card = target.closest<HTMLElement>("[data-deck-card]");
            if (!card || card !== order[0] || busy || target.closest("button")) return;
            dragging = card;
            startX = e.clientX;
            dx = 0;
            card.style.transition = "none";
            card.setPointerCapture(e.pointerId);
        });
        stack.addEventListener("pointermove", (e) => {
            if (!dragging) return;
            dx = e.clientX - startX;
            dragging.style.transform = `translateX(${dx}px) rotate(${dx / 20}deg)`;
        });
        const endDrag = () => {
            if (!dragging) return;
            const card = dragging;
            dragging = null;
            const threshold = card.offsetWidth * SWIPE_RATIO;
            if (dx > threshold && card.dataset.locked !== "1") done();
            else if (dx < -threshold && order.length > 1) later();
            else springBack(card);
        };
        stack.addEventListener("pointerup", endDrag);
        stack.addEventListener("pointercancel", endDrag);

        layout();
    }

    function initAll() {
        document.querySelectorAll<HTMLElement>("[data-deck]").forEach(initDeck);
    }
    document.addEventListener("astro:page-load", initAll);
    if (document.readyState !== "loading") initAll();
</script>
```

- [ ] **Step 2: Run checks**

Run: `cd frontend && npx astro check && npx vitest run` → 0 errors, all PASS. (The component is not mounted yet; Tasks 7–8 mount it.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/deck/TaskDeck.astro
git commit -m "feat(deck): TaskDeck component — swipe/buttons/keys, proof sheet, JSON completion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Kid home — `KidHeader`, `KidHome`, `/dashboard` rewrite

**Files:**
- Create: `frontend/src/components/home/KidHeader.astro`
- Create: `frontend/src/components/home/KidHome.astro`
- Modify: `frontend/src/pages/dashboard.astro` (full replacement below)

**Interfaces:**
- Consumes: `buildDeck` + `DeckCard` + `Deck` (Task 2), `claimableGigs`/`GigChip`/`payMeterView`/`PayMeter` (Task 3), `TaskDeck` (Task 6), `celebrate` (Task 5), `EnablePushButton` props `{ lang, userId, class?, label? }`, `pickDashboardRoutines`/`routineName`/`routineProgress`/`DashboardRoutine` (`lib/routines.ts`), `PetAvatar` (`components/pet/PetAvatar.astro`, props `species`, `stage`, `status`, `size`).
- Produces: nothing consumed later.

- [ ] **Step 1: Create `frontend/src/components/home/KidHeader.astro`:**

```astro
---
/** Kid home header (UX-C1): greeting, balance pill, weekly pay meter. */
import type { PayMeter } from "../../lib/kidHome";

interface Props {
    name: string;
    lang: "en" | "es";
    skin: "teen" | "child";
    starMode: boolean;
    cashCents: number;
    points: number;
    meter: PayMeter;
    counter: { done: number; total: number; suffix: string };
}
const { name, lang, skin, starMode, cashCents, points, meter, counter } = Astro.props;
const es = lang === "es";
const money = (cents: number) =>
    `$${Math.round(cents / 100).toLocaleString(es ? "es-MX" : "en-US")}`;
const bg = skin === "teen" ? "bg-[#1E2230]" : "bg-brand-sky-deep";
---

<header class={`${bg} text-white pt-12 pb-5 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)]`}>
    <div class="flex items-center justify-between gap-3">
        <div class="min-w-0">
            <p class="text-xs opacity-75">{es ? "Hola," : "Hi,"}</p>
            <h1 class="text-2xl font-extrabold leading-tight truncate">{name}</h1>
        </div>
        <a
            href={starMode ? "/rewards" : "/bank"}
            data-points-badge
            class="shrink-0 rounded-full bg-white/15 border border-white/25 px-3 py-1.5 text-sm font-extrabold"
        >
            {starMode ? `⭐ ${points}` : money(cashCents)}
        </a>
    </div>
    {meter.show && (
        <div class="mt-4 rounded-2xl bg-white/10 border border-white/15 px-4 py-3">
            <div class="flex justify-between gap-2 text-[11px] opacity-90">
                <span>💵 {es ? "Pago de la semana" : "This week's pay"} · {es ? "meta" : "goal"} {money(meter.capCents)}</span>
                <span data-today-counter data-done={counter.done} data-total={counter.total} data-suffix={counter.suffix}>
                    {counter.done}/{counter.total} {counter.suffix}
                </span>
            </div>
            <div
                class="mt-2 h-2 rounded-full bg-white/15 flex overflow-hidden"
                role="img"
                aria-label={es ? "Avance de tu pago de la semana" : "Progress toward this week's pay"}
            >
                <div class="h-full bg-brand-mint-deep" style={`width:${meter.greenPct}%`}></div>
                <div class="h-full bg-red-400" style={`width:${meter.redPct}%`}></div>
            </div>
            {meter.released && (
                <p class="text-[11px] mt-1.5 opacity-90">{es ? "¡Pago de esta semana liberado! 🎉" : "This week's pay is released! 🎉"}</p>
            )}
        </div>
    )}
</header>
```

- [ ] **Step 2: Create `frontend/src/components/home/KidHome.astro`:**

```astro
---
/**
 * Kid home body (UX-C1): routines strip, task deck, in-review chip, "Gana
 * extra" gigs row with push opt-in, and the goal / Family Cup / pet tiles.
 */
import TaskDeck from "../deck/TaskDeck.astro";
import EnablePushButton from "../EnablePushButton.astro";
import PetAvatar from "../pet/PetAvatar.astro";
import type { Deck } from "../../lib/deck";
import type { GigChip } from "../../lib/kidHome";
import { routineName, routineProgress, type DashboardRoutine } from "../../lib/routines";

interface Props {
    lang: "en" | "es";
    userId: string;
    deck: Deck;
    choreMode: boolean;
    /** Shown in the deck heading only when the header has no pay meter. */
    deckCounter: { done: number; total: number; suffix: string } | null;
    inReview: number;
    routines: DashboardRoutine[];
    gigs: GigChip[];
    showGigs: boolean;
    goal:
        | { kind: "cash"; name: string; emoji: string; savedCents: number; targetCents: number; pct: number }
        | { kind: "points"; title: string; icon: string; pct: number; ptsToGo: number }
        | { kind: "none"; href: string };
    cup: { rank: number; bossName: string; bossHp: number; bossMaxHp: number; defeated: boolean } | null;
    pet: { name: string; species: string; stage: string; status: string } | null;
}
const { lang, userId, deck, choreMode, deckCounter, inReview, routines, gigs, showGigs, goal, cup, pet } = Astro.props;
const es = lang === "es";
const money = (cents: number) => `$${Math.round(cents / 100).toLocaleString(es ? "es-MX" : "en-US")}`;
---

<div class="space-y-5" data-kid-home>
    {routines.length > 0 && (
        <div class="space-y-2">
            {routines.map((r) => (
                <a href="/routines" class="press flex items-center gap-3 rounded-2xl bg-white border border-brand-ink/10 px-4 py-3 shadow-[var(--shadow-card)]">
                    <span class="text-2xl leading-none" aria-hidden="true">{r.icon || "⭐"}</span>
                    <span class="flex-1 font-bold text-brand-ink">{routineName(r, lang)}</span>
                    <span class="text-sm font-extrabold tabular-nums text-brand-ink">{routineProgress(r)}</span>
                </a>
            ))}
        </div>
    )}

    <TaskDeck
        cards={deck.cards}
        lang={lang}
        variant="full"
        choreMode={choreMode}
        heading={es ? "Tus tareas" : "Your tasks"}
        counter={deckCounter}
    />

    {inReview > 0 && (
        <a href="/notifications" class="inline-flex items-center gap-1.5 rounded-full bg-sky-100 text-sky-800 px-3 py-1 text-xs font-bold">
            ⏳ {inReview} {es ? "en revisión" : "in review"}
        </a>
    )}

    {showGigs && gigs.length > 0 && (
        <section data-kid-gigs>
            <div class="flex items-baseline justify-between px-1 mb-2">
                <h2 class="text-xs font-extrabold uppercase tracking-wider text-brand-ink-soft">{es ? "Gana extra" : "Earn extra"}</h2>
                <a href="/gigs" class="text-xs font-bold text-brand-sky-deep">{es ? "ver todos ›" : "see all ›"}</a>
            </div>
            <div class="flex gap-2 overflow-x-auto pb-1 snap-x">
                {gigs.map((g) => (
                    <a href="/gigs" class="snap-start shrink-0 w-32 rounded-2xl border border-brand-ink/10 bg-white p-3 shadow-[var(--shadow-card)]">
                        {g.isNew && (
                            <span class="inline-block mb-1 text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">{es ? "Nuevo" : "New"}</span>
                        )}
                        <p class="text-sm font-bold text-brand-ink leading-tight line-clamp-2">{g.title}</p>
                        <p class="text-base font-extrabold text-emerald-700 mt-1">${g.pesos}</p>
                    </a>
                ))}
            </div>
            <EnablePushButton
                lang={lang}
                userId={userId}
                class="mt-2 px-1"
                label={es ? "🔔 Avísame de gigs nuevos" : "🔔 Tell me about new gigs"}
            />
        </section>
    )}

    <div class="grid grid-cols-2 gap-2">
        {goal.kind === "cash" && (
            <a href="/bank" class="rounded-2xl bg-white border border-brand-ink/10 p-3 shadow-[var(--shadow-card)]">
                <p class="text-xs font-bold text-brand-ink truncate">{goal.emoji || "🎯"} {goal.name}</p>
                <p class="text-sm font-extrabold text-brand-ink mt-0.5">{money(goal.savedCents)} / {money(goal.targetCents)}</p>
                <div class="h-1.5 rounded-full bg-brand-cream-deep mt-1.5 overflow-hidden"><div class="h-full bg-amber-400" style={`width:${goal.pct}%`}></div></div>
            </a>
        )}
        {goal.kind === "points" && (
            <a href="/rewards" class="rounded-2xl bg-white border border-brand-ink/10 p-3 shadow-[var(--shadow-card)]">
                <p class="text-xs font-bold text-brand-ink truncate">{goal.icon || "🎯"} {goal.title}</p>
                <p class="text-sm font-extrabold text-brand-ink mt-0.5">{goal.ptsToGo} ⭐ {es ? "para lograrlo" : "to go"}</p>
                <div class="h-1.5 rounded-full bg-brand-cream-deep mt-1.5 overflow-hidden"><div class="h-full bg-amber-400" style={`width:${goal.pct}%`}></div></div>
            </a>
        )}
        {goal.kind === "none" && (
            <a href={goal.href} class="rounded-2xl bg-white border border-dashed border-brand-ink/20 p-3 text-sm font-bold text-brand-sky-deep flex items-center">
                🎯 {es ? "Elige una meta →" : "Pick a goal →"}
            </a>
        )}
        {cup ? (
            <a href="/family-cup" class="rounded-2xl bg-white border border-brand-ink/10 p-3 shadow-[var(--shadow-card)]">
                <p class="text-xs font-bold text-brand-ink">🏆 {es ? "Copa familiar" : "Family Cup"}</p>
                <p class="text-sm font-extrabold text-brand-ink mt-0.5">
                    {cup.rank > 0 ? `${cup.rank}º` : "—"} · {cup.defeated ? (es ? "¡Jefe vencido!" : "Boss beaten!") : `${cup.bossHp}/${cup.bossMaxHp} HP`}
                </p>
                <p class="text-[11px] text-brand-ink-soft truncate">{cup.bossName}</p>
            </a>
        ) : <div></div>}
        {pet && (
            <a href="/pet/quests" class="col-span-2 flex items-center gap-3 rounded-2xl bg-white border border-brand-ink/10 p-3 shadow-[var(--shadow-card)]">
                <PetAvatar species={pet.species} stage={pet.stage} status={pet.status} size="sm" />
                <div class="min-w-0 flex-1">
                    <p class="text-sm font-extrabold text-brand-ink truncate">🐾 {pet.name}</p>
                    <p class="text-xs text-brand-ink-soft">
                        {pet.status === "starving"
                            ? (es ? "¡Tiene hambre!" : "Hungry!")
                            : pet.status === "sad"
                                ? (es ? "Te extraña" : "Misses you")
                                : (es ? "Cuídala con tus tareas" : "Care for it with your chores")}
                    </p>
                </div>
            </a>
        )}
    </div>
</div>
```

(If `PetAvatar` has no `size="sm"`, use the smallest size it accepts — check its `Props`.)

- [ ] **Step 3: Replace `frontend/src/pages/dashboard.astro` entirely with:**

```astro
---
import PageLayout from "@components/ui/PageLayout.astro";
import VerifyEmailBanner from "../components/VerifyEmailBanner.astro";
import KidHeader from "../components/home/KidHeader.astro";
import KidHome from "../components/home/KidHome.astro";
import { apiFetch } from "../lib/api";
import { t } from "../lib/i18n";
import { buildDeck } from "../lib/deck";
import { claimableGigs, payMeterView } from "../lib/kidHome";
import { pickDashboardRoutines } from "../lib/routines";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = (Astro.cookies.get("lang")?.value ?? "es") as "en" | "es";
const es = lang === "es";

const [{ data: user, ok: userOk }, { data: progress }, { data: familyCup }, { data: routinesToday }] = await Promise.all([
    apiFetch<any>("/api/auth/me", { token }),
    apiFetch<any>("/api/task-assignments/progress", { token }),
    apiFetch<any>("/api/family-cup/", { token }),
    // Icon tap-through routines. apiFetch never throws; null → no strip.
    apiFetch<any>("/api/routines/today", { token }),
]);
if (!userOk) {
    Astro.cookies.delete("access_token", { path: "/" });
    return Astro.redirect("/login");
}

// Parents' home is /parent — their own chores render there as a compact deck.
// module_off survives the hop so the "section switched off" banner still shows.
if (user.role === "parent") {
    const moduleOff = Astro.url.searchParams.get("module_off") === "1";
    return Astro.redirect(`/parent${moduleOff ? "?module_off=1" : ""}`);
}

// ── Kid home (TEEN + CHILD), UX-C1 ────────────────────────────────────────
const skin = user.role === "teen" ? "teen" : "child";
const isChild = user.role === "child";
const starMode = isChild && (user.star_mode ?? false);
const modOn = (k: string) => user.enabled_modules == null || user.enabled_modules.includes(k);
const none = Promise.resolve({ data: null as any });

// Anchor the prior-day "in review" lookup on YESTERDAY so a gig submitted
// yesterday is found even when today is Monday (yesterday = previous week).
const todayStr = String(progress?.date ?? new Date().toISOString().slice(0, 10));
const y = new Date(`${todayStr}T00:00:00`);
y.setDate(y.getDate() - 1);
const yesterdayStr = [y.getFullYear(), String(y.getMonth() + 1).padStart(2, "0"), String(y.getDate()).padStart(2, "0")].join("-");

const [{ data: paycheck }, { data: bankGoal }, { data: rewardGoal }, { data: offerings }, { data: pet }, { data: weekDone }] =
    await Promise.all([
        apiFetch<any>(`/api/bank/chore-paycheck/${user.id}`, { token }),
        starMode ? none : apiFetch<any>("/api/bank/goals/me", { token }),
        starMode ? apiFetch<any>("/api/rewards/goal", { token }) : none,
        modOn("gigs") && !starMode ? apiFetch<any>("/api/gigs/offerings", { token }) : none,
        isChild && modOn("pet") ? apiFetch<any>("/api/pet/", { token }) : none,
        apiFetch<any>(`/api/task-assignments/week?week_of=${yesterdayStr}&status=completed&user_id=${user.id}`, { token }),
    ]);

const deck = buildDeck(progress, lang);
const meter = payMeterView(paycheck);
const counter = { done: deck.doneToday, total: deck.totalToday, suffix: es ? "hoy" : "today" };
const priorInReview = (Array.isArray(weekDone) ? weekDone : []).filter(
    (a: any) => a.template_is_bonus && String(a.assigned_date) < todayStr && a.approval_status === "pending",
).length;

const goal = starMode
    ? (rewardGoal && !rewardGoal.affordable
        ? { kind: "points" as const, title: rewardGoal.reward_title, icon: rewardGoal.reward_icon ?? "🎯", pct: rewardGoal.progress_pct ?? 0, ptsToGo: rewardGoal.pts_to_go ?? 0 }
        : { kind: "none" as const, href: "/rewards" })
    : (bankGoal && bankGoal.status !== "cancelled"
        ? { kind: "cash" as const, name: bankGoal.name, emoji: bankGoal.emoji ?? "🎯", savedCents: bankGoal.saved_cents ?? 0, targetCents: bankGoal.target_cents ?? 0, pct: bankGoal.progress_pct ?? 0 }
        : { kind: "none" as const, href: "/bank" });

const boss = familyCup?.boss ?? null;
const board: any[] = Array.isArray(familyCup?.leaderboard) ? familyCup.leaderboard : [];
const rank = board.findIndex((e: any) => String(e.user_id) === String(user.id)) + 1;
const cup = boss
    ? { rank, bossName: (es ? boss.name_es : boss.name_en) ?? "", bossHp: boss.current_hp ?? 0, bossMaxHp: boss.max_hp ?? 0, defeated: Boolean(boss.defeated) }
    : null;

const flash = Astro.cookies.get("flash")?.value;
if (flash) Astro.cookies.delete("flash", { path: "/" });
const flashError = Astro.cookies.get("flash_error")?.value;
if (flashError) Astro.cookies.delete("flash_error", { path: "/" });
---

<PageLayout
    title={t(lang, "dashboard_page_title") as string}
    role={user.role}
    active="tasks"
    lang={lang}
    completedTour={user.completed_welcome_tour ?? true}
    tourUserKey={user.id}
>
    <KidHeader
        slot="header"
        name={user.name}
        lang={lang}
        skin={skin}
        starMode={starMode}
        cashCents={user.cash_cents ?? 0}
        points={user.points ?? 0}
        meter={meter}
        counter={counter}
    />

    <Fragment slot="banner">
        {Astro.url.searchParams.get("module_off") === "1" && (
            <div class="mx-4 mt-3 rounded-xl border border-brand-ink/15 bg-brand-cream px-4 py-2.5 text-sm text-brand-ink-soft">
                {es
                    ? "Esa sección está desactivada para tu familia. Un padre puede activarla en Ajustes → Módulos."
                    : "That section is switched off for your family. A parent can enable it in Settings → Modules."}
            </div>
        )}
        <VerifyEmailBanner lang={lang} show={!(user.email_verified ?? true)} userId={user.id} />
        {flash && (
            <div data-flash-success class="mx-4 mt-4 p-3 bg-brand-mint/20 border border-brand-mint text-brand-mint-deep text-sm rounded-xl">
                {flash}
            </div>
        )}
        {flashError && (
            <div class="mx-4 mt-4 p-3 bg-red-100 border border-red-200 text-red-700 text-sm rounded-xl">
                {flashError}
            </div>
        )}
    </Fragment>

    <KidHome
        lang={lang}
        userId={user.id}
        deck={deck}
        choreMode={meter.show}
        deckCounter={meter.show ? null : counter}
        inReview={deck.inReview + priorInReview}
        routines={pickDashboardRoutines(routinesToday?.routines)}
        gigs={claimableGigs(offerings, user.role)}
        showGigs={modOn("gigs") && !starMode}
        goal={goal}
        cup={cup}
        pet={pet ? { name: pet.name, species: pet.species, stage: pet.evolution_stage, status: pet.status_label } : null}
    />

    <script>
        import { celebrate } from "../lib/celebrate";
        import { buildMission } from "../lib/tourSteps";
        import { runMission } from "../lib/missionRunner";

        function onLoad() {
            if ((window as any).__ftmKidHomeInit) return;
            (window as any).__ftmKidHomeInit = true;
            // Legacy redirects (e.g. gig claims) still land here with a success flash.
            if (document.querySelector("[data-flash-success]")) celebrate();
            // /dashboard hosts none of the current mission targets, so this is the
            // "user wandered off mid-flow" degrade path: the runner finds no element
            // for the active step and ends gracefully.
            const lang = document.documentElement.lang === "es" ? "es" : "en";
            for (const id of ["first-task", "first-gig"] as const) {
                if (sessionStorage.getItem("ftm_mission_" + id)) runMission(buildMission(id, lang), lang);
            }
        }
        document.addEventListener("astro:page-load", onLoad);
        // The one-shot astro:page-load fires on DOMContentLoaded; self-trigger if
        // the DOM is already ready (the init flag keeps this idempotent).
        if (document.readyState !== "loading") onLoad();
    </script>
</PageLayout>
```

- [ ] **Step 4: Run checks**

Run: `cd frontend && npx astro check && npx vitest run && npx astro build`
Expected: 0 errors, all PASS, build OK. Also: `grep -rn "GigsIntroBanner\|DifficultyChip\|BossBattleBar" src/pages/dashboard.astro` → no matches (dropped imports). Do not delete those components (other pages use them).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/home/KidHeader.astro frontend/src/components/home/KidHome.astro frontend/src/pages/dashboard.astro
git commit -m "feat(kid-home): swipe-deck home for teens and children (UX-C1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Parent's own chores as a compact deck

**Files:**
- Modify: `frontend/src/pages/parent/index.astro`

**Interfaces:**
- Consumes: `buildDeck` (Task 2), `TaskDeck` (Task 6, `variant="compact"`).

- [ ] **Step 1: Frontmatter** — in `frontend/src/pages/parent/index.astro`:
  - add imports `import TaskDeck from "../../components/deck/TaskDeck.astro";` and `import { buildDeck } from "../../lib/deck";`;
  - replace the three lines defining `myTasks`, `myPending`, `myDone` (right after the `myProgress` fetch) with:

```ts
const myDeck = buildDeck(myProgress, lang);
// Render the section only when the parent actually has chores today (or
// carried-over ones) — same rule as before, now incl. overdue.
const myHasChores =
    (myProgress?.assignments ?? []).some((a: any) => a.status !== "cancelled") ||
    (myProgress?.overdue_assignments ?? []).length > 0;
```

  - then `grep -n "myTasks\|myPending\|myDone" src/pages/parent/index.astro` — every remaining reference must be inside the markup block replaced in Step 2.

- [ ] **Step 2: Markup** — replace the whole `{myTasks.length > 0 && ( <section class="mb-6"> … </section> )}` block (heading "Mis tareas de hoy" + the per-task cards + the all-done card) with:

```astro
            {myHasChores && (
                <section class="mb-6">
                    <TaskDeck
                        cards={myDeck.cards}
                        lang={lang}
                        variant="compact"
                        heading={lang === "es" ? "Mis tareas de hoy" : "My tasks today"}
                        counter={{ done: myDeck.doneToday, total: myDeck.totalToday, suffix: "" }}
                    />
                </section>
            )}
```

- [ ] **Step 3: Remove the old parent proof flow** — delete the `<dialog id="parent-proof-modal" …> … </dialog>` element and the whole `<script>` block whose first comment line is `// "Mis tareas de hoy" completion. Photo-required chores open the proof` (from its `<script>` to the matching `</script>`). Then `grep -n "parent-proof\|data-parent-complete" src/pages/parent/index.astro` → no matches.

- [ ] **Step 4: Run checks**

Run: `cd frontend && npx astro check && npx vitest run && npx astro build` → 0 errors, all PASS, build OK.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/parent/index.astro
git commit -m "feat(parent): own chores render as the compact swipe deck

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Branch verification, PR, deploy (controller)

- [ ] **Step 1:** Full backend suite in background under UTC (`run-backend-tests-c1.sh tests/` via a longer-timeout copy) → read the log; 0 failures expected.
- [ ] **Step 2:** `cd backend && ruff check app`; `cd frontend && npx vitest run && npx astro check && npx astro build`.
- [ ] **Step 3:** Whole-branch review (most capable model) over `git merge-base origin/main HEAD..HEAD`, then one fix wave + scoped re-review if needed.
- [ ] **Step 4:** PR with `--body-file`, watch CI, merge explicitly (no `--auto`), sync main.
- [ ] **Step 5:** `./scripts/deploy-onprem.sh -y` from the clean main checkout; verify on prod (read-only as `diego.demo` TEEN, `sofia.demo` CHILD, demo parent): deck renders, swipe right/left + buttons + ←/→, proof sheet on a proof task, empty-deck celebration, gigs row with "Nuevo", push opt-in visibility, parent compact deck. The ONLY prod write: as the demo parent post a gig titled "Prueba UX-C1" in the demo family, confirm the demo teen and child get "💵 Nuevo: Prueba UX-C1", then archive it.
- [ ] **Step 6:** Update `logs/SESSION-WORKLOG.md` and the project memory `project_ux_program_2026_09.md` (C1 shipped; next C2 parent hub).
