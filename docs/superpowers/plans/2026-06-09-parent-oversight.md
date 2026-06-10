# Parent Oversight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 broken parent-oversight paths, then ship a unified command center: per-kid summary cards, merged approval queue, goal visibility, goal-reached parent notification.

**Architecture:** Phase A fixes broken plumbing (consequences form, gigs proxy, expiry sweep, analytics). Phase B adds read-only aggregation: `OversightService` + `/api/oversight` routes (parent-gated), `RewardGoalService.get_family_goals` batch query, parent fan-out in `check_nudge`, rewritten `/parent` hub and `/parent/approvals` pages. Approve/reject actions stay on existing endpoints.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL 15, Pydantic v2, Astro 5, Tailwind CSS v4.

**Spec:** `docs/superpowers/specs/2026-06-09-parent-oversight-design.md`

**Key facts (verified against repo):**
- Frontend role values are lowercase: `user.role === "parent"`, `m.role === "child" || m.role === "teen"`
- `ConsequenceCreate` requires `applied_to_user: UUID`, `restriction_type` (enum, required), accepts `severity` (default low), `duration_days` (1–30, default 1). NO `due_date` field. Response has `end_date`.
- `RestrictionType` values: `screen_time, rewards, extra_tasks, allowance, activities, custom`. `ConsequenceSeverity`: `low, medium, high`.
- `TaskAssignmentService._family_local_today(db, family_id) -> date` exists at task_assignment_service.py:1127 (async staticmethod).
- `settings.GIG_AUTO_APPROVE_STREAK` default 3.
- Test fixtures in conftest.py: `test_family`, `test_parent_user` (parent@test.com, points=0), `test_child_user` (child@test.com, points=100), `test_teen_user` (teen@test.local), `test_reward` (points_cost=100, icon 🎮), `db_session`, `client`.
- `GigCategory.CHORES` (uppercase members, lowercase values). `GigClaimStatus`: CLAIMED/COMPLETED/APPROVED/REJECTED. `ApprovalStatus`: NONE/PENDING/APPROVED/REJECTED.
- Test command: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -v` (coverage-threshold FAIL line at the end is pre-existing — ignore it; only test failures matter).

---

## File Map

**New files:**
- `frontend/src/pages/api/gigs/[...path].ts` — wildcard proxy
- `backend/app/schemas/oversight.py` — KidGoal, KidSummary, PendingCounts, OversightSummary, PendingApprovalItem
- `backend/app/services/oversight_service.py` — OversightService
- `backend/app/api/routes/oversight.py` — GET /summary, GET /pending-approvals
- `backend/tests/test_oversight.py` — all new tests

**Modified files:**
- `frontend/src/pages/parent/consequences.astro` — form fix + end_date render
- `frontend/src/pages/profile.astro` — end_date render
- `backend/app/services/consequence_service.py` — `check_expired_all`
- `backend/app/main.py` — sweep wiring + router registration
- `backend/app/services/analytics_service.py` — gig-board counting
- `backend/app/services/reward_goal_service.py` — `get_family_goals` + parent fan-out in `check_nudge`
- `frontend/src/pages/parent/index.astro` — command center cards
- `frontend/src/pages/parent/approvals.astro` — unified queue

---

## Task 1: Gigs wildcard proxy (fix A3)

**Files:**
- Create: `frontend/src/pages/api/gigs/[...path].ts`

- [ ] **Step 1: Create the proxy file**

Copy the budget proxy pattern exactly. Full file content:

```typescript
import type { APIRoute } from "astro";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

/**
 * Wildcard proxy for all /api/gigs/* requests.
 *
 * Browser-side JS cannot reach the backend directly (different port / internal
 * Docker hostname). This endpoint forwards every method (GET, POST, PUT,
 * DELETE, PATCH) transparently, preserving headers, body, and status codes.
 *
 * Route: /api/gigs/[...path]  →  <BACKEND>/api/gigs/<path>
 *
 * Redirect handling: FastAPI redirects e.g. POST /offerings → /offerings/
 * We follow 3xx redirects manually so the body is re-sent correctly on POST.
 */
async function proxy({ request, params }: { request: Request; params: Record<string, string | undefined> }): Promise<Response> {
    const path = params.path ?? "";
    const url = new URL(request.url);
    const backendUrl = `${BACKEND_URL}/api/gigs/${path}${url.search}`;

    // Forward all headers except Host (which must point to the backend)
    const forwardHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
        if (key.toLowerCase() === "host") continue;
        forwardHeaders.set(key, value);
    }

    // The access_token cookie is httpOnly so browser JS cannot read it.
    // Extract it server-side and inject as Authorization header if not already set.
    if (!forwardHeaders.has("Authorization")) {
        const cookieHeader = request.headers.get("cookie") ?? "";
        const match = cookieHeader.match(/(?:^|;\s*)access_token=([^;]+)/);
        if (match) {
            const token = decodeURIComponent(match[1]);
            forwardHeaders.set("Authorization", `Bearer ${token}`);
        }
    }

    const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
    const body = hasBody ? await request.arrayBuffer() : undefined;

    async function doFetch(targetUrl: string): Promise<Response> {
        const backendRes = await fetch(targetUrl, {
            method: request.method,
            headers: forwardHeaders,
            body: body,
            redirect: "manual", // handle redirects ourselves so POST body is preserved
        });

        // Follow 3xx redirects manually (preserves method + body)
        if (backendRes.status >= 300 && backendRes.status < 400) {
            const location = backendRes.headers.get("location");
            if (location) {
                const redirectUrl = location.startsWith("http")
                    ? location
                    : `${BACKEND_URL}${location}`;
                return doFetch(redirectUrl);
            }
        }

        const responseHeaders = new Headers();
        for (const [key, value] of backendRes.headers.entries()) {
            if (key.toLowerCase() === "transfer-encoding") continue;
            responseHeaders.set(key, value);
        }

        return new Response(backendRes.body, {
            status: backendRes.status,
            statusText: backendRes.statusText,
            headers: responseHeaders,
        });
    }

    try {
        return await doFetch(backendUrl);
    } catch (e: any) {
        console.error(`[api/gigs proxy] Error forwarding to ${backendUrl}:`, e?.message ?? e);
        return new Response(
            JSON.stringify({ error: "proxy_error", message: "Could not reach backend" }),
            { status: 502, headers: { "Content-Type": "application/json" } }
        );
    }
}

export const GET: APIRoute = proxy;
export const POST: APIRoute = proxy;
export const PUT: APIRoute = proxy;
export const DELETE: APIRoute = proxy;
export const PATCH: APIRoute = proxy;
```

- [ ] **Step 2: Type check**

```bash
cd /Users/jc/dev-2026/AgentIA/family-task-manager/frontend && npm run check 2>&1 | tail -5
```

Expected: `0 errors` (79 pre-existing hints OK)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/api/gigs/[...path].ts
git commit -m "fix(gigs): add missing Astro wildcard proxy for /api/gigs/*"
```

---

## Task 2: Consequences form + end_date fixes (A1 + A2)

**Files:**
- Modify: `frontend/src/pages/parent/consequences.astro`
- Modify: `frontend/src/pages/profile.astro`
- Create: `backend/tests/test_oversight.py` (first test)

- [ ] **Step 1: Write the route test (proves backend accepts the new payload)**

Create `backend/tests/test_oversight.py`:

```python
"""Tests for parent oversight: fixes + command center."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def parent_headers(client: AsyncClient, test_parent_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def child_headers(client: AsyncClient, test_child_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── A1: consequence create payload shape ─────────────────────────────────────

@pytest.mark.asyncio
async def test_consequence_create_new_payload_shape(
    client, parent_headers, test_family, test_child_user
):
    """The exact payload the fixed frontend form sends must succeed."""
    res = await client.post(
        "/api/consequences/",
        json={
            "title": "No tablet",
            "description": "Too much screen time",
            "applied_to_user": str(test_child_user.id),
            "restriction_type": "screen_time",
            "severity": "low",
            "duration_days": 3,
        },
        headers=parent_headers,
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    assert data["applied_to_user"] == str(test_child_user.id)
    assert data["restriction_type"] == "screen_time"
    assert data["end_date"] is not None
```

- [ ] **Step 2: Run — expect pass (backend already correct; this locks the contract)**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -v
```

Expected: `1 passed`

- [ ] **Step 3: Fix the create handler in `consequences.astro` frontmatter**

Replace the create-payload block (lines ~25-37):

```typescript
    if (action === "create") {
        const payload: any = {
            title: data.get("title"),
            description: data.get("description") || null,
            applied_to_user: data.get("applied_to_user"),
            restriction_type: data.get("restriction_type"),
            severity: data.get("severity") || "low",
            duration_days: parseInt(data.get("duration_days") as string, 10) || 3,
        };
        const { ok, error } = await apiFetch("/api/consequences/", {
            method: "POST",
            token,
            body: JSON.stringify(payload),
        });
        if (ok) {
            successMsg = t(lang, "pc_created");
        } else {
            errorMsg = error || "Error";
        }
    }
```

(The old block conditionally added `due_date` — that is gone.)

- [ ] **Step 4: Fix the form HTML**

In the create form section (lines ~125-194): rename the member select `name="user_id"` → `name="applied_to_user"`. Replace the due-date `<div>` (the one containing `<input type="date" name="due_date" ...>`) with three fields:

```astro
                        <div>
                            <label class="text-xs font-medium text-brand-ink-soft mb-1 block">
                                {lang === "es" ? "Restricción" : "Restriction"}
                            </label>
                            <select
                                name="restriction_type"
                                required
                                class="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm focus:ring-2 focus:ring-rose-500 outline-none bg-brand-cream"
                            >
                                <option value="screen_time">{lang === "es" ? "Tiempo de pantalla" : "Screen time"}</option>
                                <option value="rewards">{lang === "es" ? "Recompensas" : "Rewards"}</option>
                                <option value="extra_tasks">{lang === "es" ? "Tareas extra" : "Extra tasks"}</option>
                                <option value="allowance">{lang === "es" ? "Mesada" : "Allowance"}</option>
                                <option value="activities">{lang === "es" ? "Actividades" : "Activities"}</option>
                                <option value="custom">{lang === "es" ? "Otra" : "Custom"}</option>
                            </select>
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="text-xs font-medium text-brand-ink-soft mb-1 block">
                                {lang === "es" ? "Severidad" : "Severity"}
                            </label>
                            <select
                                name="severity"
                                class="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm focus:ring-2 focus:ring-rose-500 outline-none bg-brand-cream"
                            >
                                <option value="low">{lang === "es" ? "Baja" : "Low"}</option>
                                <option value="medium">{lang === "es" ? "Media" : "Medium"}</option>
                                <option value="high">{lang === "es" ? "Alta" : "High"}</option>
                            </select>
                        </div>
                        <div>
                            <label class="text-xs font-medium text-brand-ink-soft mb-1 block">
                                {lang === "es" ? "Duración (días)" : "Duration (days)"}
                            </label>
                            <input
                                type="number"
                                name="duration_days"
                                min="1"
                                max="30"
                                value="3"
                                class="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm focus:ring-2 focus:ring-rose-500 outline-none"
                            />
                        </div>
```

Note the structure: the restriction select replaces the date div inside the FIRST `grid grid-cols-2` (next to the member picker); severity + duration form a SECOND `grid grid-cols-2 gap-3` row right after it. Keep the existing closing `</div>` of the first grid in place.

- [ ] **Step 5: Fix expiry render in both files (A2)**

In `consequences.astro` list block (~line 232): change `c.due_date` → `c.end_date` (both the condition and `new Date(c.end_date)`). In the same card, after the title-row badges, add severity/restriction chips:

```astro
                                            <p class="text-xs text-brand-ink-soft mt-0.5">
                                                {c.restriction_type}
                                                <span class="mx-1">·</span>
                                                {c.severity}
                                            </p>
```

In `profile.astro` (~lines 154-161): change both `c.due_date` references → `c.end_date`.

- [ ] **Step 6: Type check + commit**

```bash
cd /Users/jc/dev-2026/AgentIA/family-task-manager/frontend && npm run check 2>&1 | tail -5
git add frontend/src/pages/parent/consequences.astro frontend/src/pages/profile.astro backend/tests/test_oversight.py
git commit -m "fix(consequences): form sends correct schema; render end_date"
```

---

## Task 3: Expired-consequence auto-resolve sweep (A4)

**Files:**
- Modify: `backend/app/services/consequence_service.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_oversight.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_oversight.py`:

```python
# ── A4: expired consequence sweep ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_expired_all_resolves_only_expired(
    db_session: AsyncSession, test_family, test_child_user
):
    from datetime import datetime, timedelta, timezone
    from app.models.consequence import Consequence, ConsequenceSeverity, RestrictionType
    from app.services.consequence_service import ConsequenceService

    now = datetime.now(timezone.utc)
    expired = Consequence(
        title="Expired one",
        severity=ConsequenceSeverity.LOW,
        restriction_type=RestrictionType.SCREEN_TIME,
        duration_days=1,
        applied_to_user=test_child_user.id,
        family_id=test_family.id,
        start_date=now - timedelta(days=3),
        end_date=now - timedelta(days=2),
        active=True,
        resolved=False,
    )
    current = Consequence(
        title="Still active",
        severity=ConsequenceSeverity.LOW,
        restriction_type=RestrictionType.REWARDS,
        duration_days=5,
        applied_to_user=test_child_user.id,
        family_id=test_family.id,
        start_date=now,
        end_date=now + timedelta(days=5),
        active=True,
        resolved=False,
    )
    db_session.add_all([expired, current])
    await db_session.commit()

    n = await ConsequenceService.check_expired_all(db_session)
    assert n == 1

    await db_session.refresh(expired)
    await db_session.refresh(current)
    assert expired.active is False
    assert expired.resolved is True
    assert expired.resolved_at is not None
    assert current.active is True
    assert current.resolved is False
```

- [ ] **Step 2: Run — expect AttributeError (method missing)**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py::test_check_expired_all_resolves_only_expired -v 2>&1 | tail -5
```

- [ ] **Step 3: Add `check_expired_all` to ConsequenceService**

In `backend/app/services/consequence_service.py`, after `check_expired_consequences` (ends ~line 162), add (ensure `update` is in the sqlalchemy import line — add it if missing):

```python
    @staticmethod
    async def check_expired_all(db: AsyncSession) -> int:
        """Global sweep: auto-resolve every expired, still-active consequence
        across ALL families. Called from the hourly background loop."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(Consequence)
            .where(
                Consequence.active == True,
                Consequence.resolved == False,
                Consequence.end_date < now,
            )
            .values(active=False, resolved=True, resolved_at=now)
        )
        await db.commit()
        return int(result.rowcount or 0)
```

- [ ] **Step 4: Wire into the hourly sweep in `main.py`**

In `_overdue_sweep_loop` (main.py:31-45), inside the `async with AsyncSessionLocal() as session:` block, after the `if flipped:` log line, add:

```python
                resolved = await ConsequenceService.check_expired_all(session)
                if resolved:
                    logger.info("Consequence sweep auto-resolved %d", resolved)
```

Add the import near the other service imports at the top of main.py:

```python
from app.services.consequence_service import ConsequenceService
```

- [ ] **Step 5: Run both tests + commit**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -v
```

Expected: `2 passed`

```bash
git add backend/app/services/consequence_service.py backend/app/main.py backend/tests/test_oversight.py
git commit -m "fix(consequences): hourly auto-resolve of expired consequences"
```

---

## Task 4: Analytics counts new gig board (A6)

**Files:**
- Modify: `backend/app/services/analytics_service.py`
- Modify: `backend/tests/test_oversight.py`

- [ ] **Step 1: Write failing test**

Append to `test_oversight.py`:

```python
# ── A6: analytics includes gig-board claims ───────────────────────────────────

@pytest.mark.asyncio
async def test_analytics_gigs_completed_includes_gig_board(
    db_session: AsyncSession, test_family, test_parent_user, test_child_user
):
    from datetime import datetime, timezone
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus, GigCategory
    from app.services.analytics_service import AnalyticsService

    offering = GigOffering(
        family_id=test_family.id,
        created_by=test_parent_user.id,
        title="Wash car",
        points=30,
        difficulty=1,
        category=GigCategory.CHORES,
    )
    db_session.add(offering)
    await db_session.commit()
    await db_session.refresh(offering)

    claim = GigClaim(
        gig_id=offering.id,
        family_id=test_family.id,
        claimed_by=test_child_user.id,
        status=GigClaimStatus.APPROVED,
        points_awarded=30,
        approved_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(claim)
    await db_session.commit()

    rows = await AnalyticsService.per_member_completion_rate(
        db_session, test_family.id
    )
    kid_row = next(r for r in rows if r["user_id"] == str(test_child_user.id))
    assert kid_row["gigs_completed"] >= 1
```

- [ ] **Step 2: Run — expect failure (gigs_completed == 0)**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py::test_analytics_gigs_completed_includes_gig_board -v 2>&1 | tail -5
```

- [ ] **Step 3: Extend `per_member_completion_rate`**

In `backend/app/services/analytics_service.py`:

Add to imports:
```python
from app.models.gig import GigClaim, GigClaimStatus
```

After `start = today - timedelta(weeks=lookback_weeks)` (line ~40), add:
```python
        start_dt = datetime.combine(start, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
```

Inside the member loop, after `gigs_done = int((await db.execute(gig_q)).scalar() or 0)` (line ~87), add:

```python
            # New gig board (gig_claims) — invisible to the legacy is_bonus path.
            board_q = (
                select(func.count())
                .select_from(GigClaim)
                .where(
                    and_(
                        GigClaim.family_id == family_id,
                        GigClaim.claimed_by == m.id,
                        GigClaim.status == GigClaimStatus.APPROVED,
                        GigClaim.approved_at >= start_dt,
                    )
                )
            )
            gigs_done += int((await db.execute(board_q)).scalar() or 0)
```

- [ ] **Step 4: Run all + commit**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -v
```

Expected: `3 passed`. Also run `pytest tests/ -q -k analytics 2>&1 | tail -3` — no regressions.

```bash
git add backend/app/services/analytics_service.py backend/tests/test_oversight.py
git commit -m "fix(analytics): count new gig-board claims in gigs_completed"
```

---

## Task 5: `RewardGoalService.get_family_goals` (TDD)

**Files:**
- Modify: `backend/app/services/reward_goal_service.py`
- Modify: `backend/tests/test_oversight.py`

- [ ] **Step 1: Write failing tests**

Append to `test_oversight.py`:

```python
# ── B1: get_family_goals ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_family_goals_returns_active_goals_keyed_by_user(
    db_session: AsyncSession, test_family, test_child_user, test_teen_user, test_reward
):
    from app.services.reward_goal_service import RewardGoalService

    await RewardGoalService.set_goal(
        test_child_user.id, test_family.id, test_reward.id, db_session
    )
    goals = await RewardGoalService.get_family_goals(test_family.id, db_session)

    assert test_child_user.id in goals
    assert test_teen_user.id not in goals
    gp = goals[test_child_user.id]
    assert gp.reward_title == test_reward.title
    assert gp.balance == 100
    assert gp.affordable is True


@pytest.mark.asyncio
async def test_get_family_goals_excludes_achieved(
    db_session: AsyncSession, test_family, test_child_user, test_reward
):
    from app.services.reward_goal_service import RewardGoalService

    await RewardGoalService.set_goal(
        test_child_user.id, test_family.id, test_reward.id, db_session
    )
    await RewardGoalService.mark_achieved(test_child_user.id, test_reward.id, db_session)
    await db_session.commit()

    goals = await RewardGoalService.get_family_goals(test_family.id, db_session)
    assert test_child_user.id not in goals


@pytest.mark.asyncio
async def test_get_family_goals_cross_family_isolated(
    db_session: AsyncSession, test_family, test_child_user, test_reward
):
    from app.models.family import Family
    from app.services.reward_goal_service import RewardGoalService

    other = Family(name="Other Family")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    await RewardGoalService.set_goal(
        test_child_user.id, test_family.id, test_reward.id, db_session
    )
    goals = await RewardGoalService.get_family_goals(other.id, db_session)
    assert goals == {}
```

- [ ] **Step 2: Run — expect AttributeError**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -k family_goals -v 2>&1 | tail -6
```

- [ ] **Step 3: Implement**

In `backend/app/services/reward_goal_service.py`, after `get_active_goal`, add:

```python
    @staticmethod
    async def get_family_goals(
        family_id: UUID,
        db: AsyncSession,
    ) -> dict[UUID, GoalProgress]:
        """All active goals in the family, keyed by user_id. One JOIN query —
        balance comes from the joined User row (no per-row lookups)."""
        rows = (
            await db.execute(
                select(UserRewardGoal, Reward, User)
                .join(Reward, UserRewardGoal.reward_id == Reward.id)
                .join(User, UserRewardGoal.user_id == User.id)
                .where(
                    UserRewardGoal.family_id == family_id,
                    UserRewardGoal.achieved_at.is_(None),
                )
            )
        ).all()
        out: dict[UUID, GoalProgress] = {}
        for goal, reward, user in rows:
            balance = int(user.points or 0)
            pts_to_go = max(0, reward.points_cost - balance)
            progress_pct = (
                min(100, round(balance / reward.points_cost * 100))
                if reward.points_cost > 0
                else 100
            )
            out[goal.user_id] = GoalProgress(
                reward_id=reward.id,
                reward_title=reward.title,
                reward_icon=reward.icon,
                points_cost=reward.points_cost,
                balance=balance,
                progress_pct=progress_pct,
                pts_to_go=pts_to_go,
                affordable=balance >= reward.points_cost,
                set_at=goal.set_at,
            )
        return out
```

(`User`, `Reward`, `UserRewardGoal`, `GoalProgress`, `select` already imported in this file.)

- [ ] **Step 4: Run all + commit**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -v
```

Expected: `6 passed`. Also `pytest tests/test_reward_goals.py -q` → `21 passed` (no regression).

```bash
git add backend/app/services/reward_goal_service.py backend/tests/test_oversight.py
git commit -m "feat(oversight): RewardGoalService.get_family_goals batch query"
```

---

## Task 6: Oversight schemas + `OversightService.get_summary` (TDD)

**Files:**
- Create: `backend/app/schemas/oversight.py`
- Create: `backend/app/services/oversight_service.py`
- Modify: `backend/tests/test_oversight.py`

- [ ] **Step 1: Create schemas file**

```python
# backend/app/schemas/oversight.py
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class KidGoal(BaseModel):
    reward_title: str
    reward_icon: Optional[str] = None
    progress_pct: int
    pts_to_go: int
    affordable: bool


class KidSummary(BaseModel):
    user_id: UUID
    name: str
    role: str  # serialized UserRole value (lowercase, e.g. "child")
    points: int
    gig_trust_streak: int
    auto_approve_active: bool
    goal: Optional[KidGoal] = None
    pending_approvals: int  # this kid's items across BOTH queues
    open_today: int  # PENDING assignments dated family-local today
    active_consequences: int


class PendingCounts(BaseModel):
    tasks: int
    gig_claims: int
    total: int


class OversightSummary(BaseModel):
    members: list[KidSummary]
    pending_counts: PendingCounts


class PendingApprovalItem(BaseModel):
    kind: Literal["task", "gig_claim"]
    id: UUID  # assignment_id or claim_id
    title: str
    kid_id: UUID
    kid_name: str
    points: int
    completed_at: Optional[datetime] = None
    proof_text: Optional[str] = None
    proof_image_url: Optional[str] = None
    ai_score: Optional[float] = None  # tasks only; gig claims have no AI validation
```

- [ ] **Step 2: Write failing tests**

Append to `test_oversight.py`:

```python
# ── B2: OversightService.get_summary ──────────────────────────────────────────

async def _make_pending_task(db, family, parent, kid, title="Chore", points=20):
    """TaskAssignment awaiting parent approval (legacy gig path)."""
    from datetime import date, timedelta, datetime, timezone
    from app.models.task_template import TaskTemplate
    from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus

    template = TaskTemplate(
        family_id=family.id,
        created_by=parent.id,
        title=title,
        is_bonus=True,
        points=points,
        blocks_rewards=False,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)

    today = date.today()
    week_monday = today - timedelta(days=today.weekday())
    assignment = TaskAssignment(
        family_id=family.id,
        template_id=template.id,
        assigned_to=kid.id,
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.PENDING,
        assigned_date=today,
        week_of=week_monday,
        completed_at=datetime.now(timezone.utc),
        proof_text="done",
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def _make_pending_claim(db, family, parent, kid, title="Gig", points=15):
    """GigClaim awaiting parent approval (new gig board)."""
    from datetime import datetime, timezone
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus, GigCategory

    offering = GigOffering(
        family_id=family.id,
        created_by=parent.id,
        title=title,
        points=points,
        difficulty=1,
        category=GigCategory.CHORES,
    )
    db.add(offering)
    await db.commit()
    await db.refresh(offering)

    claim = GigClaim(
        gig_id=offering.id,
        family_id=family.id,
        claimed_by=kid.id,
        status=GigClaimStatus.COMPLETED,
        completed_at=datetime.now(timezone.utc),
        proof_text="did it",
    )
    db.add(claim)
    await db.commit()
    await db.refresh(claim)
    return claim


@pytest.mark.asyncio
async def test_summary_pending_counts_across_both_queues(
    db_session, test_family, test_parent_user, test_child_user, test_teen_user
):
    from app.services.oversight_service import OversightService

    await _make_pending_task(db_session, test_family, test_parent_user, test_child_user)
    await _make_pending_claim(db_session, test_family, test_parent_user, test_child_user)
    await _make_pending_claim(db_session, test_family, test_parent_user, test_teen_user)

    summary = await OversightService.get_summary(db_session, test_family.id)

    assert summary.pending_counts.tasks == 1
    assert summary.pending_counts.gig_claims == 2
    assert summary.pending_counts.total == 3

    child_card = next(m for m in summary.members if m.user_id == test_child_user.id)
    teen_card = next(m for m in summary.members if m.user_id == test_teen_user.id)
    assert child_card.pending_approvals == 2  # 1 task + 1 claim
    assert teen_card.pending_approvals == 1


@pytest.mark.asyncio
async def test_summary_consequences_and_goal(
    db_session, test_family, test_parent_user, test_child_user, test_reward
):
    from datetime import datetime, timedelta, timezone
    from app.models.consequence import Consequence, ConsequenceSeverity, RestrictionType
    from app.services.oversight_service import OversightService
    from app.services.reward_goal_service import RewardGoalService

    now = datetime.now(timezone.utc)
    db_session.add(
        Consequence(
            title="Grounded",
            severity=ConsequenceSeverity.MEDIUM,
            restriction_type=RestrictionType.ACTIVITIES,
            duration_days=2,
            applied_to_user=test_child_user.id,
            family_id=test_family.id,
            start_date=now,
            end_date=now + timedelta(days=2),
            active=True,
            resolved=False,
        )
    )
    await db_session.commit()
    await RewardGoalService.set_goal(
        test_child_user.id, test_family.id, test_reward.id, db_session
    )

    summary = await OversightService.get_summary(db_session, test_family.id)
    card = next(m for m in summary.members if m.user_id == test_child_user.id)

    assert card.active_consequences == 1
    assert card.goal is not None
    assert card.goal.reward_title == test_reward.title
    assert card.goal.affordable is True


@pytest.mark.asyncio
async def test_summary_auto_approve_flag_and_member_filter(
    db_session, test_family, test_parent_user, test_child_user, test_teen_user
):
    from app.services.oversight_service import OversightService

    test_child_user.gig_trust_streak = 5  # ≥ threshold (3)
    test_teen_user.is_active = False
    await db_session.commit()

    summary = await OversightService.get_summary(db_session, test_family.id)
    ids = [m.user_id for m in summary.members]

    assert test_parent_user.id not in ids       # parents excluded
    assert test_teen_user.id not in ids          # inactive excluded
    child_card = next(m for m in summary.members if m.user_id == test_child_user.id)
    assert child_card.auto_approve_active is True
    assert child_card.points == 100
```

- [ ] **Step 3: Run — expect ModuleNotFoundError**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -k summary -v 2>&1 | tail -6
```

- [ ] **Step 4: Create the service**

```python
# backend/app/services/oversight_service.py
"""
OversightService — read-only aggregations for the parent command center.

Per-kid summary cards and a unified pending-approval queue spanning both
review systems (legacy task-assignment gigs + new gig board). Approve/reject
actions stay on their existing endpoints; this service never mutates.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.consequence import Consequence
from app.models.gig import GigClaim, GigClaimStatus
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.user import User, UserRole
from app.schemas.oversight import (
    KidGoal,
    KidSummary,
    OversightSummary,
    PendingApprovalItem,
    PendingCounts,
)
from app.services.reward_goal_service import RewardGoalService
from app.services.task_assignment_service import TaskAssignmentService

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class OversightService:

    @staticmethod
    async def get_summary(db: AsyncSession, family_id: UUID) -> OversightSummary:
        """Per-kid cards + unified pending counts. Six fixed queries, no N+1."""
        kids = list(
            (
                await db.execute(
                    select(User)
                    .where(
                        User.family_id == family_id,
                        User.role.in_([UserRole.CHILD, UserRole.TEEN]),
                        User.is_active.is_(True),
                    )
                    .order_by(User.name)
                )
            ).scalars().all()
        )

        task_counts = dict(
            (
                await db.execute(
                    select(TaskAssignment.assigned_to, func.count())
                    .where(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.approval_status == ApprovalStatus.PENDING,
                    )
                    .group_by(TaskAssignment.assigned_to)
                )
            ).all()
        )

        claim_counts = dict(
            (
                await db.execute(
                    select(GigClaim.claimed_by, func.count())
                    .where(
                        GigClaim.family_id == family_id,
                        GigClaim.status == GigClaimStatus.COMPLETED,
                    )
                    .group_by(GigClaim.claimed_by)
                )
            ).all()
        )

        consequence_counts = dict(
            (
                await db.execute(
                    select(Consequence.applied_to_user, func.count())
                    .where(
                        Consequence.family_id == family_id,
                        Consequence.active.is_(True),
                    )
                    .group_by(Consequence.applied_to_user)
                )
            ).all()
        )

        today = await TaskAssignmentService._family_local_today(db, family_id)
        open_today_counts = dict(
            (
                await db.execute(
                    select(TaskAssignment.assigned_to, func.count())
                    .where(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.status == AssignmentStatus.PENDING,
                        TaskAssignment.assigned_date == today,
                    )
                    .group_by(TaskAssignment.assigned_to)
                )
            ).all()
        )

        goals = await RewardGoalService.get_family_goals(family_id, db)

        threshold = max(1, settings.GIG_AUTO_APPROVE_STREAK)
        members: list[KidSummary] = []
        for kid in kids:
            gp = goals.get(kid.id)
            streak = int(kid.gig_trust_streak or 0)
            members.append(
                KidSummary(
                    user_id=kid.id,
                    name=kid.name,
                    role=kid.role.value if hasattr(kid.role, "value") else str(kid.role),
                    points=int(kid.points or 0),
                    gig_trust_streak=streak,
                    auto_approve_active=streak >= threshold,
                    goal=KidGoal(
                        reward_title=gp.reward_title,
                        reward_icon=gp.reward_icon,
                        progress_pct=gp.progress_pct,
                        pts_to_go=gp.pts_to_go,
                        affordable=gp.affordable,
                    )
                    if gp
                    else None,
                    pending_approvals=int(task_counts.get(kid.id, 0))
                    + int(claim_counts.get(kid.id, 0)),
                    open_today=int(open_today_counts.get(kid.id, 0)),
                    active_consequences=int(consequence_counts.get(kid.id, 0)),
                )
            )

        total_tasks = sum(int(v) for v in task_counts.values())
        total_claims = sum(int(v) for v in claim_counts.values())
        return OversightSummary(
            members=members,
            pending_counts=PendingCounts(
                tasks=total_tasks,
                gig_claims=total_claims,
                total=total_tasks + total_claims,
            ),
        )
```

- [ ] **Step 5: Run + commit**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -v
```

Expected: `9 passed`

```bash
git add backend/app/schemas/oversight.py backend/app/services/oversight_service.py backend/tests/test_oversight.py
git commit -m "feat(oversight): schemas + OversightService.get_summary"
```

---

## Task 7: `OversightService.get_pending_approvals` (TDD)

**Files:**
- Modify: `backend/app/services/oversight_service.py`
- Modify: `backend/tests/test_oversight.py`

- [ ] **Step 1: Write failing tests**

Append to `test_oversight.py`:

```python
# ── B2: unified pending-approvals queue ───────────────────────────────────────

@pytest.mark.asyncio
async def test_pending_approvals_union_both_kinds_sorted(
    db_session, test_family, test_parent_user, test_child_user
):
    from app.services.oversight_service import OversightService

    await _make_pending_task(
        db_session, test_family, test_parent_user, test_child_user, title="Task A", points=20
    )
    await _make_pending_claim(
        db_session, test_family, test_parent_user, test_child_user, title="Gig B", points=15
    )

    items = await OversightService.get_pending_approvals(db_session, test_family.id)

    assert len(items) == 2
    kinds = {i.kind for i in items}
    assert kinds == {"task", "gig_claim"}
    # sorted by completed_at asc
    assert items[0].completed_at <= items[1].completed_at
    for i in items:
        assert i.kid_name == "Test Child"
        assert i.points > 0


@pytest.mark.asyncio
async def test_pending_approvals_ai_score_only_on_tasks(
    db_session, test_family, test_parent_user, test_child_user
):
    from app.services.oversight_service import OversightService

    a = await _make_pending_task(
        db_session, test_family, test_parent_user, test_child_user
    )
    a.ai_validation_score = 0.85
    await db_session.commit()
    await _make_pending_claim(
        db_session, test_family, test_parent_user, test_child_user
    )

    items = await OversightService.get_pending_approvals(db_session, test_family.id)
    task_item = next(i for i in items if i.kind == "task")
    claim_item = next(i for i in items if i.kind == "gig_claim")

    assert task_item.ai_score == 0.85
    assert claim_item.ai_score is None
```

- [ ] **Step 2: Run — expect AttributeError**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -k pending_approvals -v 2>&1 | tail -6
```

- [ ] **Step 3: Add the method to OversightService**

```python
    @staticmethod
    async def get_pending_approvals(
        db: AsyncSession, family_id: UUID
    ) -> list[PendingApprovalItem]:
        """Normalized union of both review queues, sorted by completed_at asc."""
        from app.services.gig_claim_service import GigClaimService

        rows = await TaskAssignmentService.list_pending_approvals(db, family_id)
        user_ids = list({r.assigned_to for r in rows})
        user_names: dict = {}
        if user_ids:
            q = select(User.id, User.name).where(User.id.in_(user_ids))
            user_names = {uid: name for uid, name in (await db.execute(q)).all()}

        items = [
            PendingApprovalItem(
                kind="task",
                id=r.id,
                title=r.template.title if r.template else "",
                kid_id=r.assigned_to,
                kid_name=user_names.get(r.assigned_to, ""),
                points=int(
                    r.template.award_points_per_completer if r.template else 0
                ),
                completed_at=r.completed_at,
                proof_text=r.proof_text,
                proof_image_url=r.proof_image_url,
                ai_score=r.ai_validation_score,
            )
            for r in rows
        ]

        claims = await GigClaimService.get_pending_approvals(db, family_id)
        for item in claims:
            c = item["claim"]
            items.append(
                PendingApprovalItem(
                    kind="gig_claim",
                    id=c.id,
                    title=item["gig_title"],
                    kid_id=c.claimed_by,
                    kid_name=item["claimer_name"],
                    points=int(item["gig_points"] or 0),
                    completed_at=c.completed_at,
                    proof_text=c.proof_text,
                    proof_image_url=c.proof_image_url,
                    ai_score=None,
                )
            )

        items.sort(key=lambda i: (i.completed_at is None, i.completed_at or _EPOCH))
        return items
```

- [ ] **Step 4: Run + commit**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -v
```

Expected: `11 passed`

```bash
git add backend/app/services/oversight_service.py backend/tests/test_oversight.py
git commit -m "feat(oversight): unified pending-approvals queue"
```

---

## Task 8: Routes + registration (TDD)

**Files:**
- Create: `backend/app/api/routes/oversight.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_oversight.py`

- [ ] **Step 1: Write failing route tests**

Append to `test_oversight.py`:

```python
# ── B2: HTTP routes ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_oversight_summary_route_parent_ok(
    client, parent_headers, test_family, test_child_user
):
    res = await client.get("/api/oversight/summary", headers=parent_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert "members" in data
    assert "pending_counts" in data
    assert data["pending_counts"]["total"] == 0


@pytest.mark.asyncio
async def test_oversight_summary_route_kid_403(client, child_headers, test_family):
    res = await client.get("/api/oversight/summary", headers=child_headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_oversight_pending_route_kid_403(client, child_headers, test_family):
    res = await client.get("/api/oversight/pending-approvals", headers=child_headers)
    assert res.status_code == 403
```

- [ ] **Step 2: Run — expect 404s**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -k route -v 2>&1 | tail -6
```

- [ ] **Step 3: Create the routes file**

First check the exact import paths used by `backend/app/api/routes/gigs.py` for `get_db`, `require_parent_role`, `to_uuid_required` — copy those import lines verbatim. Then:

```python
# backend/app/api/routes/oversight.py
"""Parent oversight: read-only aggregations for the command center."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.utils import to_uuid_required
from app.models.user import User
from app.schemas.oversight import OversightSummary, PendingApprovalItem
from app.services.oversight_service import OversightService

router = APIRouter()


@router.get("/summary", response_model=OversightSummary)
async def oversight_summary(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Per-kid summary cards + unified pending counts. Parents only."""
    return await OversightService.get_summary(
        db, to_uuid_required(current_user.family_id)
    )


@router.get("/pending-approvals", response_model=list[PendingApprovalItem])
async def oversight_pending_approvals(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Unified approval queue: task assignments + gig claims. Parents only."""
    return await OversightService.get_pending_approvals(
        db, to_uuid_required(current_user.family_id)
    )
```

(If `get_db`/`to_uuid_required` live elsewhere per gigs.py, adjust imports to match.)

- [ ] **Step 4: Register in `main.py`**

Add `oversight` to the routes import in main.py (find the existing `from app.api.routes import ...` block), then register near the analytics router line:

```python
app.include_router(oversight.router, prefix="/api/oversight", tags=["Oversight"])
```

- [ ] **Step 5: Run all + commit**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py -v
```

Expected: `14 passed`

```bash
git add backend/app/api/routes/oversight.py backend/app/main.py backend/tests/test_oversight.py
git commit -m "feat(oversight): GET /api/oversight/summary + /pending-approvals"
```

---

## Task 9: Goal-reached parent fan-out (B3, TDD)

**Files:**
- Modify: `backend/app/services/reward_goal_service.py`
- Modify: `backend/tests/test_oversight.py`

- [ ] **Step 1: Write failing test**

Append to `test_oversight.py`:

```python
# ── B3: goal-reached parent fan-out ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_nudge_notifies_parents_too(
    db_session, test_family, test_parent_user, test_child_user, test_reward
):
    from app.models.notification import Notification as Notif
    from app.services.reward_goal_service import RewardGoalService

    await RewardGoalService.set_goal(
        test_child_user.id, test_family.id, test_reward.id, db_session
    )
    await RewardGoalService.check_nudge(
        test_child_user.id, test_family.id, 100, db_session
    )

    parent_notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_parent_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert parent_notif is not None
    assert parent_notif.link == "/parent"
    assert "Test Child" in parent_notif.title

    kid_notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert kid_notif is not None  # kid nudge unaffected
```

- [ ] **Step 2: Run — expect failure (parent_notif is None)**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py::test_check_nudge_notifies_parents_too -v 2>&1 | tail -5
```

- [ ] **Step 3: Add fan-out to `check_nudge`**

In `backend/app/services/reward_goal_service.py`, `check_nudge` currently ends:

```python
        except Exception:
            log.warning("check_nudge: notification failed", exc_info=True)
            return
        goal.nudge_sent_at = datetime.now(timezone.utc)
        await db.commit()
```

Insert the parent fan-out between the `except` block and the `goal.nudge_sent_at` line:

```python
        except Exception:
            log.warning("check_nudge: notification failed", exc_info=True)
            return
        # Parent fan-out — oversight signal. Failure must never block the kid
        # nudge nor nudge_sent_at (separate guard).
        try:
            from app.models.user import UserRole

            kid = await db.get(User, user_id)
            kid_name = kid.name if kid else "Kid"
            parents = (
                await db.scalars(
                    select(User).where(
                        User.family_id == family_id,
                        User.role == UserRole.PARENT,
                        User.is_active.is_(True),
                    )
                )
            ).all()
            for parent in parents:
                await NotificationService.create(
                    db,
                    family_id=family_id,
                    user_id=parent.id,
                    type=NT.GOAL_REACHED,
                    title=f"🎯 {kid_name} alcanzó su meta / reached their goal",
                    body=f"{reward.title} — {reward.points_cost} pts",
                    link="/parent",
                    push=True,
                )
        except Exception:
            log.warning("check_nudge: parent fan-out failed", exc_info=True)
        goal.nudge_sent_at = datetime.now(timezone.utc)
        await db.commit()
```

(`NotificationService` and `NT` are in scope — imported inside the first try block of the same function. `User` and `select` are module-level imports.)

- [ ] **Step 4: Run all goal + oversight tests + commit**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_oversight.py tests/test_reward_goals.py -v 2>&1 | tail -8
```

Expected: `15 + 21 = 36 passed` (existing reward-goal tests filter notifications by kid user_id — unaffected)

```bash
git add backend/app/services/reward_goal_service.py backend/tests/test_oversight.py
git commit -m "feat(oversight): notify parents when kid reaches reward goal"
```

---

## Task 10: `/parent` hub — command center cards (B4)

**Files:**
- Modify: `frontend/src/pages/parent/index.astro`

- [ ] **Step 1: Replace the pending-approvals fetch in frontmatter**

Current (lines ~27-32):

```astro
// Pending gig approvals count for the badge on the Approvals tile.
const { data: pending } = await apiFetch<any[]>(
    "/api/task-assignments/pending-approvals",
    { token }
);
const pendingApprovals = Array.isArray(pending) ? pending.length : 0;
```

Replace with:

```astro
// Oversight summary: per-kid cards + unified pending counts (both queues).
const { data: oversight } = await apiFetch<any>("/api/oversight/summary", { token });
const pendingApprovals = oversight?.pending_counts?.total ?? 0;
const kidCards: any[] = oversight?.members ?? [];
```

The Approvals tile badge (lines ~172-194) keeps using `pendingApprovals` — no change needed there.

- [ ] **Step 2: Replace the members-list section**

Replace the whole `{family?.members && family.members.length > 0 && (...)}` section (lines ~323-351) with:

```astro
            {
                kidCards.length > 0 && (
                    <section class="mt-6 bg-brand-cream rounded-2xl p-5 shadow-[var(--shadow-card)] border border-brand-ink/10">
                        <h2 class="font-bold text-brand-ink mb-3">
                            {t(lang, "parent_family_members")}
                        </h2>
                        <div class="space-y-4">
                            {kidCards.map((m: any) => (
                                <div class="rounded-xl border border-brand-ink/10 p-3">
                                    <div class="flex items-center gap-3">
                                        <div class="w-9 h-9 rounded-full bg-brand-cream-deep flex items-center justify-center text-brand-sky-deep font-bold text-sm">
                                            {m.name.charAt(0).toUpperCase()}
                                        </div>
                                        <div class="flex-1 min-w-0">
                                            <p class="font-medium text-brand-ink text-sm truncate">{m.name}</p>
                                            <p class="text-xs text-brand-ink-soft">
                                                {m.role}
                                                {m.gig_trust_streak > 0 && (
                                                    <span class="ml-1">
                                                        🔥{m.gig_trust_streak}
                                                        {m.auto_approve_active && (
                                                            <span class="ml-1 text-brand-mint-deep font-semibold">
                                                                {lang === "es" ? "auto" : "auto"}
                                                            </span>
                                                        )}
                                                    </span>
                                                )}
                                            </p>
                                        </div>
                                        <span class="text-sm font-bold text-brand-sun-deep whitespace-nowrap">
                                            {m.points} pts
                                        </span>
                                    </div>
                                    {m.goal && (
                                        <div class={`mt-2 rounded-lg px-3 py-2 ${m.goal.affordable ? "bg-brand-sun/20" : "bg-brand-cream-deep"}`}>
                                            <div class="flex items-center gap-2">
                                                <span class="text-sm">{m.goal.reward_icon ?? "🎯"}</span>
                                                <p class="text-xs font-semibold text-brand-ink flex-1 truncate">
                                                    {m.goal.reward_title}
                                                </p>
                                                <span class="text-xs text-brand-ink-soft whitespace-nowrap">
                                                    {m.goal.affordable
                                                        ? (lang === "es" ? "¡Lista!" : "Ready!")
                                                        : `${m.goal.pts_to_go} pts`}
                                                </span>
                                            </div>
                                            {!m.goal.affordable && (
                                                <div class="w-full bg-brand-ink/10 rounded-full h-1.5 mt-1.5 overflow-hidden">
                                                    <div
                                                        class="h-1.5 bg-brand-sky-deep rounded-full"
                                                        style={`width: ${m.goal.progress_pct}%`}
                                                    ></div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    <div class="flex gap-2 mt-2 flex-wrap">
                                        {m.pending_approvals > 0 && (
                                            <a
                                                href="/parent/approvals"
                                                class="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800"
                                            >
                                                {lang === "es"
                                                    ? `${m.pending_approvals} por aprobar`
                                                    : `${m.pending_approvals} to approve`}
                                            </a>
                                        )}
                                        {m.open_today > 0 && (
                                            <span class="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-brand-cream-deep text-brand-ink-soft">
                                                {lang === "es"
                                                    ? `${m.open_today} tareas hoy`
                                                    : `${m.open_today} tasks today`}
                                            </span>
                                        )}
                                        {m.active_consequences > 0 && (
                                            <a
                                                href="/parent/consequences"
                                                class="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-rose-100 text-rose-700"
                                            >
                                                {lang === "es"
                                                    ? `${m.active_consequences} consecuencia${m.active_consequences > 1 ? "s" : ""}`
                                                    : `${m.active_consequences} consequence${m.active_consequences > 1 ? "s" : ""}`}
                                            </a>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </section>
                )
            }
```

- [ ] **Step 3: Type check + commit**

```bash
cd /Users/jc/dev-2026/AgentIA/family-task-manager/frontend && npm run check 2>&1 | tail -5
git add frontend/src/pages/parent/index.astro
git commit -m "feat(oversight): parent hub command-center kid cards"
```

---

## Task 11: `/parent/approvals` unified queue (B5)

**Files:**
- Modify: `frontend/src/pages/parent/approvals.astro`

- [ ] **Step 1: Swap data source in frontmatter**

Replace:

```astro
const { data: rows } = await apiFetch<any[]>(
    "/api/task-assignments/pending-approvals",
    { token }
);
const items: any[] = rows ?? [];
```

With:

```astro
const { data: rows } = await apiFetch<any[]>(
    "/api/oversight/pending-approvals",
    { token }
);
const items: any[] = rows ?? [];
```

- [ ] **Step 2: Update row rendering**

The unified shape is `{kind, id, title, kid_id, kid_name, points, completed_at, proof_text, proof_image_url, ai_score}`. In the `items.map((row: any) => (...))` block:

- `data-id={row.assignment_id}` → `data-id={row.id}` and add `data-kind={row.kind}`
- `{row.template_title}` → `{row.title}`
- `{row.assigned_to_name}` → `{row.kid_name}`
- `row.ai_validation_score` → `row.ai_score` (all 4 references in the AI chip block)
- Remove the `row.ai_validation_notes` sub-paragraph (field not in unified shape)
- After the title `<h3>`, add a kind tag:

```astro
                                    {row.kind === "gig_claim" && (
                                        <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-brand-sky-deep/10 text-brand-sky-deep uppercase tracking-wide">
                                            Gig
                                        </span>
                                    )}
```

(Place it inside the existing `<div class="min-w-0">` right before the `<h3>`, wrapping both in a `flex items-center gap-2` div, or simply above the h3 — match surrounding style.)

- [ ] **Step 3: Update the client script for dual endpoints**

Replace the fetch block inside the button click handler:

```typescript
                        const kind = li.dataset.kind;
                        let r: Response;
                        if (kind === "gig_claim") {
                            r = await fetch(`/api/gigs/claims/${id}/approve`, {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                    approved: approve,
                                    notes: notes?.value.trim() || null,
                                }),
                            });
                        } else {
                            r = await fetch("/api/assignments/approve", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                    assignment_id: id,
                                    approve,
                                    notes: notes?.value.trim() || null,
                                }),
                            });
                        }
```

(The gig path works through the Task 1 proxy. Backend gig approve body is `{approved, notes}` — note the field name difference from the task path's `{approve}`.)

- [ ] **Step 4: Type check + commit**

```bash
cd /Users/jc/dev-2026/AgentIA/family-task-manager/frontend && npm run check 2>&1 | tail -5
git add frontend/src/pages/parent/approvals.astro
git commit -m "feat(oversight): unified approval queue — tasks + gig claims"
```

---

## Task 12: Final verification

- [ ] **Step 1: Full backend suite**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q 2>&1 | tail -6
```

Expected: 15 new passes in test_oversight.py, total ≥922 passed, same 5 pre-existing failures, zero new failures.

- [ ] **Step 2: Frontend check**

```bash
cd /Users/jc/dev-2026/AgentIA/family-task-manager/frontend && npm run check 2>&1 | tail -5
```

Expected: 0 errors.

- [ ] **Step 3: Local smoke (containers running)**

```bash
curl -s http://localhost:8003/api/oversight/summary -H "Authorization: Bearer invalid" | head -1
```

Expected: 401 JSON (route registered, auth enforced).

---

## Post-implementation checklist

- [ ] `./scripts/deploy-gcp.sh --skip-backup -y` (no migration in this feature — schema untouched)
- [ ] Log in as parent at gcp-family.agent-ia.mx → `/parent` shows kid cards with points/streak/goal/chips
- [ ] `/parent/approvals` shows both queue kinds; approve a gig claim from it
- [ ] Create a consequence from `/parent/consequences` — verify no 422, expiry date renders
- [ ] Kid reaches goal → parent gets push
