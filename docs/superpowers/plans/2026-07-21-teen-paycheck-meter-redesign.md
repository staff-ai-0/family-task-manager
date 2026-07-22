# Teen Chore-Paycheck Meter Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop showing teens the live-shifting dollar/points numbers behind their weekly chore paycheck, replacing them with a static weekly-goal amount and a two-color (green/red) progress bar that only turns red on an explicit parent grading decision — never as a side effect of a task being added or edited mid-week.

**Architecture:** One new derived field (`discounted_pct`) computed server-side in the existing chore-paycheck projection math, from data already fetched in a single existing query (no new query, no migration). The teen-facing page (`bank.astro`) stops rendering the numbers that move and renders the new field as a bar segment instead. Parent-facing pages and every other payout code path are untouched.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), Astro 5 + Tailwind v4, vanilla server-rendered frontmatter (no client JS needed for this change).

## Global Constraints

- No database migration. No new column, no new query.
- No change to any payout math, cap, gate, or release logic (`_chore_paycheck_cents`, `_chore_paycheck_gated`, `_points_rate_cents`, `release_chore_paycheck`'s payout amount).
- No change to parent-facing screens (`frontend/src/pages/parent/payouts.astro`, `frontend/src/pages/parent/settings/family-bank.astro`).
- `discounted_pct` counts a loss ONLY on an explicit parent grading decision (`approval_status == REJECTED`, or `APPROVED` with `completion_grade == "partial"`). A `NOT_DONE`/`PENDING`-review task contributes 0 to it regardless of when it was added — it must never retroactively "turn red" just because a new task inflated the week's denominator.
- `pct` (existing field) is untouched — same computation as today.
- The existing "¡Pago liberado! 🎉" / "Paycheck released! 🎉" released-reveal text in `bank.astro` stays byte-for-byte identical — it already shows no dollar figure.
- Full spec: `docs/superpowers/specs/2026-07-21-teen-paycheck-meter-redesign-design.md`.

---

### Task 1: Backend — `discounted_pct` in the chore-paycheck projection

**Files:**
- Modify: `backend/app/services/bank_service.py:372-420` (`_chore_units`)
- Modify: `backend/app/services/bank_service.py:524-555` (`_paycheck_projection`)
- Modify: `backend/app/services/bank_service.py:557-579` (`chore_paycheck_preview`)
- Modify: `backend/app/services/bank_service.py:800-802` (`release_chore_paycheck`'s call to `_chore_units`)
- Modify: `backend/app/schemas/bank.py:67-79` (`ChorePaycheckPreview`)
- Modify: `backend/tests/test_chore_paycheck.py:111`, `:133` (existing `_chore_units` unpacking)
- Test: `backend/tests/test_chore_paycheck.py` (new tests, appended)

**Interfaces:**
- Produces: `BankService._chore_units(db, family_id, user_id, week_monday) -> tuple[int, int, int]` — now `(done_units, assigned_units, lost_units)`, was `(done_units, assigned_units)`.
- Produces: `BankService._paycheck_projection(...)` return dict gains key `"discounted_pct": int`.
- Produces: `BankService.chore_paycheck_preview(...)` return dict gains key `"discounted_pct": int`.
- Produces: `ChorePaycheckPreview` schema gains field `discounted_pct: int`, consumed by Task 2's frontend change via `GET /api/bank/chore-paycheck/{user_id}`.

- [ ] **Step 1: Write the failing tests**

Open `backend/tests/test_chore_paycheck.py`. Update the two existing `_chore_units` call sites to unpack three values (they will fail to run at all with a 3-tuple return until Step 3, which is the point — this locks in the new signature before it exists), and add new tests for `lost_units`/`discounted_pct`.

Replace line 111:
```python
    done, assigned = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    # Units = points × pct (×100 for full credit).
    assert done == 3000         # (20 + 10) × 100
    assert assigned == 6000     # (20+10+10+10+10) × 100 — cancelled & gig out
```
with:
```python
    done, assigned, lost = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    # Units = points × pct (×100 for full credit).
    assert done == 3000         # (20 + 10) × 100
    assert assigned == 6000     # (20+10+10+10+10) × 100 — cancelled & gig out
    assert lost == 1000         # the REJECTED 10-point task — full loss
```

Replace line 133 (inside `test_chore_units_partial_grade_scales_credit`):
```python
    done, assigned = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    assert done == 2500         # 20×100 + 10×50 + 0
    assert assigned == 4000     # (20+10+10) × 100
```
with:
```python
    done, assigned, lost = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    assert done == 2500         # 20×100 + 10×50 + 0
    assert assigned == 4000     # (20+10+10) × 100
    assert lost == 1500         # half's un-credited 50% (10×50) + missed's full loss (10×100)
```

Append these new tests at the end of the file:
```python
# ── discounted_pct (teen meter's red segment) ────────────────────────────

@pytest.mark.asyncio
async def test_lost_units_zero_when_all_full_credit(db):
    """No parent has graded anything negatively — nothing should be red."""
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _chore(db, fam, parent, kid, 20, AssignmentStatus.COMPLETED)
    await _chore(db, fam, parent, kid, 10, AssignmentStatus.PENDING)  # not done, still time

    done, assigned, lost = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    assert lost == 0

@pytest.mark.asyncio
async def test_lost_units_ignores_pending_review(db):
    """Awaiting the parent's decision is NOT a loss yet — only a REJECTED or
    partial-graded APPROVED decision counts."""
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _chore(db, fam, parent, kid, 15, AssignmentStatus.COMPLETED, ApprovalStatus.PENDING)

    done, assigned, lost = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    assert done == 0
    assert lost == 0
    assert assigned == 1500

@pytest.mark.asyncio
async def test_discounted_pct_reflects_graded_loss(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    full = await _chore(db, fam, parent, kid, 20, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    half = await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    missed = await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, ApprovalStatus.REJECTED)
    full.completion_grade = "full"
    half.completion_grade = "partial"
    half.partial_credit_pct = 50
    missed.completion_grade = "missed"
    await db.commit()

    p = await BankService.chore_paycheck_preview(db, kid, fam.id, week_of=WEEK)
    # assigned = (20+10+10)*100 = 4000; done = 20*100 + 10*50 = 2500 → pct = 63
    # lost = 10*50 (half's uncredited remainder) + 10*100 (missed) = 1500 → discounted_pct = 38
    assert p["pct"] == 63
    assert p["discounted_pct"] == 38

@pytest.mark.asyncio
async def test_lost_units_ignores_overdue_never_completed(db):
    """An OVERDUE task (day passed, kid never completed it, no parent review
    ever happened) stays neutral — red is reserved for an explicit parent
    grading decision, not a passive timeout."""
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _chore(db, fam, parent, kid, 25, AssignmentStatus.OVERDUE)

    done, assigned, lost = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    assert done == 0
    assert lost == 0
    assert assigned == 2500

@pytest.mark.asyncio
async def test_discounted_pct_zero_when_assigned_is_zero(db):
    fam = await _family(db)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, week_of=WEEK)
    assert p["assigned_points"] == 0
    assert p["discounted_pct"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_chore_paycheck.py -q --no-cov`
Expected: FAIL — `ValueError: not enough values to unpack` (the two updated call sites) and `AttributeError`/`KeyError: 'discounted_pct'` (the new tests), since `_chore_units` still returns a 2-tuple and neither `_paycheck_projection` nor `chore_paycheck_preview` nor the schema know about `discounted_pct` yet.

- [ ] **Step 3: Implement `lost_units` in `_chore_units`**

Replace the full `_chore_units` method body (`backend/app/services/bank_service.py:372-420`) with:
```python
    async def _chore_units(
        db: AsyncSession, family_id: UUID, user_id: UUID, week_monday: date
    ) -> tuple[int, int, int]:
        """(done_units, assigned_units, lost_units) of a kid's NON-gig chores
        for the week, where one unit = one template point × one percent
        (points × 100 = full credit for one task). Integer math end to end —
        no float cents.

        assigned_units: every non-cancelled regular assignment at 100%.
        done_units: COMPLETED work that cleared quality review (approval_status
        NONE = no review needed, or APPROVED), scaled by the parent's grade —
        'partial' contributes partial_credit_pct, everything else 100. PENDING
        (awaiting the parent) and REJECTED/missed contribute 0 — "de manera
        correcta". Gigs (is_bonus) pay their own cash and are excluded.
        lost_units: the portion of assigned_units a PARENT has explicitly
        graded away — REJECTED (full loss) or APPROVED+partial (the
        un-credited remainder). A not-yet-reviewed or not-yet-due task never
        contributes here — only an explicit grading decision creates a loss.
        Feeds the teen meter's red segment; done_units and lost_units are
        drawn from disjoint rows, so done_units + lost_units <= assigned_units
        always.
        """
        from app.models.task_assignment import (
            TaskAssignment, AssignmentStatus, ApprovalStatus,
        )
        from app.models.task_template import TaskTemplate

        rows = (await db.execute(
            select(
                TaskTemplate.points,
                TaskAssignment.status,
                TaskAssignment.approval_status,
                TaskAssignment.completion_grade,
                TaskAssignment.partial_credit_pct,
            )
            .select_from(TaskAssignment)
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.week_of == week_monday,
                TaskTemplate.is_bonus.is_(False),
                TaskAssignment.status != AssignmentStatus.CANCELLED,
            )
        )).all()

        done_units = 0
        assigned_units = 0
        lost_units = 0
        for points, status, approval, grade, pct in rows:
            pts = int(points or 0)
            assigned_units += pts * 100
            if status != AssignmentStatus.COMPLETED:
                continue
            if approval == ApprovalStatus.REJECTED:
                lost_units += pts * 100
                continue
            if approval not in (ApprovalStatus.NONE, ApprovalStatus.APPROVED):
                continue
            credit_pct = int(pct or 50) if grade == "partial" else 100
            done_units += pts * credit_pct
            if grade == "partial":
                lost_units += pts * (100 - credit_pct)
        return done_units, assigned_units, lost_units
```

- [ ] **Step 4: Update `_paycheck_projection` to compute and expose `discounted_pct`**

In `backend/app/services/bank_service.py`, inside `_paycheck_projection` (around line 532), replace:
```python
        done_u, assigned_u = await BankService._chore_units(
            db, family_id, acct.user_id, week_monday
        )
```
with:
```python
        done_u, assigned_u, lost_u = await BankService._chore_units(
            db, family_id, acct.user_id, week_monday
        )
```

Then replace the method's `return` block:
```python
        return {
            "week_of": week_monday,
            "cap_cents": cap,
            "amount_cents": amount,
            "done_points": round(done_u / 100) if done_u else 0,
            "assigned_points": assigned_u // 100,
            "pct": round(100 * done_u / assigned_u) if assigned_u else 0,
            "assigned_units": assigned_u,
        }
```
with:
```python
        return {
            "week_of": week_monday,
            "cap_cents": cap,
            "amount_cents": amount,
            "done_points": round(done_u / 100) if done_u else 0,
            "assigned_points": assigned_u // 100,
            "pct": round(100 * done_u / assigned_u) if assigned_u else 0,
            "discounted_pct": round(100 * lost_u / assigned_u) if assigned_u else 0,
            "assigned_units": assigned_u,
        }
```

- [ ] **Step 5: Pass `discounted_pct` through `chore_paycheck_preview`**

In `backend/app/services/bank_service.py`, inside `chore_paycheck_preview` (around line 569), replace:
```python
        return {
            "user_id": target_user.id,
            "week_of": p["week_of"],
            "mode": acct.allowance_mode,
            "cap_cents": p["cap_cents"],
            "done_points": p["done_points"],
            "assigned_points": p["assigned_points"],
            "pct": p["pct"],
            "projected_cents": p["amount_cents"],
            "already_released": acct.last_chore_paycheck_week == week_monday,
        }
```
with:
```python
        return {
            "user_id": target_user.id,
            "week_of": p["week_of"],
            "mode": acct.allowance_mode,
            "cap_cents": p["cap_cents"],
            "done_points": p["done_points"],
            "assigned_points": p["assigned_points"],
            "pct": p["pct"],
            "discounted_pct": p["discounted_pct"],
            "projected_cents": p["amount_cents"],
            "already_released": acct.last_chore_paycheck_week == week_monday,
        }
```

- [ ] **Step 6: Fix the third `_chore_units` caller (`release_chore_paycheck`)**

In `backend/app/services/bank_service.py`, around line 800, replace:
```python
        done, assigned = await BankService._chore_units(
            db, family_id, user.id, week_monday
        )
```
with:
```python
        done, assigned, _ = await BankService._chore_units(
            db, family_id, user.id, week_monday
        )
```

- [ ] **Step 7: Add `discounted_pct` to the schema**

In `backend/app/schemas/bank.py`, replace the `ChorePaycheckPreview` class body:
```python
class ChorePaycheckPreview(BaseModel):
    """Projected weekly chore paycheck — feeds the teen meter + parent review."""

    user_id: UUID
    week_of: date
    mode: str
    cap_cents: int
    done_points: int
    assigned_points: int
    pct: int
    projected_cents: int
    already_released: bool
```
with:
```python
class ChorePaycheckPreview(BaseModel):
    """Projected weekly chore paycheck — feeds the teen meter + parent review."""

    user_id: UUID
    week_of: date
    mode: str
    cap_cents: int
    done_points: int
    assigned_points: int
    pct: int
    discounted_pct: int
    projected_cents: int
    already_released: bool
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_chore_paycheck.py -q --no-cov`
Expected: PASS — all existing tests plus the 4 new ones.

If the backend container is serving a stale image (source isn't bind-mounted in local dev), rebuild and recreate first:
```bash
podman compose build backend
podman compose down backend frontend
podman compose up -d backend frontend
```
Then re-run the pytest command above.

- [ ] **Step 9: Lint**

Run: `cd backend && ruff check app`
Expected: `All checks passed!` (do NOT run `ruff check app tests` — the project's zero-tolerance lint gate is `app` only; `tests/` carries pre-existing unrelated debt).

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/bank_service.py backend/app/schemas/bank.py backend/tests/test_chore_paycheck.py
git commit -m "feat(bank): expose discounted_pct on the chore-paycheck projection

Derives the share of a week's assigned points a parent has explicitly
graded away (REJECTED, or APPROVED+partial) from the same per-row data
_chore_units already fetches — no new query, no migration. A
not-yet-reviewed or not-yet-due task never contributes, so this can't
retroactively 'go red' just because a task was added mid-week. Feeds
the teen meter's red segment (Task 2)."
```

---

### Task 2: Frontend — teen meter shows the bar, not the numbers

**Files:**
- Modify: `frontend/src/pages/bank.astro:1-129` (frontmatter + the `choreMode` section)

**Interfaces:**
- Consumes: `GET /api/bank/chore-paycheck/{user_id}` response now includes `discounted_pct: number` (Task 1). Existing fields `pct`, `cap_cents`, `already_released` unchanged; `projected_cents`, `done_points`, `assigned_points` are still fetched but no longer rendered to the teen.

- [ ] **Step 1: Compute the clamped bar segments in the frontmatter**

In `frontend/src/pages/bank.astro`, right after the existing line:
```js
const choreMode = paycheck?.mode === "chore_proportional" && (paycheck?.cap_cents ?? 0) > 0;
```
add:
```js
// Two-color bar for the teen meter: green = done (paycheck.pct), red = a
// PARENT-graded loss (paycheck.discounted_pct). Rounding two independent
// ratios from the same denominator can theoretically overshoot 100 by a
// point — clamp so the two widths never exceed the track.
const barPct = paycheck?.pct ?? 0;
const barDiscountedPct = Math.max(0, Math.min(paycheck?.discounted_pct ?? 0, 100 - barPct));
```

- [ ] **Step 2: Replace the live meter markup**

Replace lines 108-129 (the entire `{choreMode && (...)}` block):
```astro
    {choreMode && (
        <section class="mb-6 rounded-2xl border-2 border-brand-mint-deep/40 bg-white p-4 shadow-[var(--shadow-card)]">
            <div class="flex items-center justify-between mb-1">
                <span class="text-sm font-extrabold text-brand-ink">{es ? "💵 Mi pago por tareas" : "💵 My chore paycheck"}</span>
                <span class="text-xs text-brand-ink-soft">{es ? "esta semana" : "this week"}</span>
            </div>
            <div class="flex items-baseline gap-1">
                <span class="text-3xl font-extrabold text-brand-mint-deep">{pcFmt(paycheck.projected_cents)}</span>
                <span class="text-sm text-brand-ink-soft">/ {pcFmt(paycheck.cap_cents)}</span>
            </div>
            <div class="h-3 rounded-full bg-brand-cream-deep overflow-hidden mt-2">
                <div class="h-full bg-brand-mint-deep transition-all" style={`width:${paycheck.pct}%`}></div>
            </div>
            <p class="text-xs text-brand-ink-soft mt-2">
                {paycheck.already_released
                    ? (es ? "¡Pago liberado! 🎉" : "Paycheck released! 🎉")
                    : (es
                        ? `${paycheck.done_points}/${paycheck.assigned_points} pts hechos · termina todo para ganar ${pcFmt(paycheck.cap_cents)}`
                        : `${paycheck.done_points}/${paycheck.assigned_points} pts done · finish all to earn ${pcFmt(paycheck.cap_cents)}`)}
            </p>
        </section>
    )}
```
with:
```astro
    {choreMode && (
        <section class="mb-6 rounded-2xl border-2 border-brand-mint-deep/40 bg-white p-4 shadow-[var(--shadow-card)]">
            <div class="flex items-center justify-between mb-1">
                <span class="text-sm font-extrabold text-brand-ink">{es ? "💵 Mi pago por tareas" : "💵 My chore paycheck"}</span>
                <span class="text-xs text-brand-ink-soft">{es ? "esta semana" : "this week"}</span>
            </div>
            {paycheck.already_released ? (
                <p class="text-xs text-brand-ink-soft mt-2">
                    {es ? "¡Pago liberado! 🎉" : "Paycheck released! 🎉"}
                </p>
            ) : (
                <>
                    <div class="flex items-baseline gap-1">
                        <span class="text-xs text-brand-ink-soft">{es ? "Meta de esta semana:" : "This week's goal:"}</span>
                        <span class="text-lg font-extrabold text-brand-mint-deep">{pcFmt(paycheck.cap_cents)}</span>
                    </div>
                    <div class="h-3 rounded-full bg-brand-cream-deep overflow-hidden mt-2 flex">
                        <div class="h-full bg-brand-mint-deep transition-all" style={`width:${barPct}%`}></div>
                        <div class="h-full bg-red-400 transition-all" style={`width:${barDiscountedPct}%`}></div>
                    </div>
                    <p class="text-xs text-brand-ink-soft mt-2">
                        {es
                            ? "Tu pago depende de qué tan bien y cuánto completes tus tareas de esta semana."
                            : "Your pay depends on how well and how much of your tasks you complete this week."}
                    </p>
                </>
            )}
        </section>
    )}
```

- [ ] **Step 3: Type-check and build**

Run: `cd frontend && npm run check`
Expected: `0 errors` (pre-existing warnings/hints in other files are unrelated and unaffected).

- [ ] **Step 4: Manual verification against local dev**

Rebuild and recreate the frontend container so the change is actually served (per this repo's known gotcha — `up -d` alone can keep serving the old image):
```bash
cd /Users/jc/dev-2026/AgentIA/family-task-manager
podman compose build frontend
podman compose down backend frontend
podman compose up -d backend frontend
```
Log in as a TEEN on `chore_proportional` mode (or temporarily set one via `_config`-equivalent — e.g. through Settings → Family Bank in the parent view) and open `/bank`. Confirm:
- No dollar figure or points fraction appears in the chore-paycheck card while unreleased.
- The static "Meta de esta semana: $X" line shows the cap.
- The bar renders green (and red, if any task for that kid has been graded partial/missed this week) with no numbers overlaid.
- Once released, the card shows only "¡Pago liberado! 🎉" — unchanged from before.
- The parent's `/parent/payouts` and `/parent/settings/family-bank` pages are visually and functionally unchanged (still show full per-task $ detail).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/bank.astro
git commit -m "feat(bank): teen chore-paycheck meter shows a bar, not moving numbers

Replaces the live projected-\$/points-fraction display with a static
weekly-goal amount and a two-color bar (green = done, red = a parent-
graded loss). Removes the numbers that shifted whenever a parent added
or edited a task mid-week — the actual trigger for real complaints —
while parent-facing views keep full detail unchanged."
```

---

## Final Verification

- [ ] Full backend suite still green: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v` (or the project's standard coverage-gated run).
- [ ] `cd backend && ruff check app` clean.
- [ ] `cd frontend && npm run check` clean.
- [ ] Manual pass on `/bank` (teen) and `/parent/payouts` + `/parent/settings/family-bank` (parent) per Task 2 Step 4.
- [ ] Use `superpowers:finishing-a-development-branch` to wrap up (branch → PR → CI → merge → deploy, per this repo's established workflow).
