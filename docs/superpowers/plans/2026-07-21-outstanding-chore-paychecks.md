# Outstanding Chore-Paycheck Weeks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a parent see and release EVERY unreleased chore-paycheck week per kid (not just the current one), closing the gap where a missed week becomes permanently unreachable.

**Architecture:** A new `BankService.list_outstanding_weeks` walks back a bounded window of weeks and checks the ledger (`CashTransaction`) directly for what's actually been paid — the same authoritative source `chore_paycheck_history` already uses — rather than the single-field `last_chore_paycheck_week` comparison that only ever knows about "the most recent release." The release route gains an optional `week_of` so a specific past week can be targeted. Everything is additive: existing fields/behavior (`chore_paycheck_preview`, the current `PayoutSummaryKid` fields, the sweep, `flat` mode) are untouched — this only adds new fields and a new capability alongside them, so no existing test needs to change.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), Astro 5 + Tailwind + vanilla JS (frontend), pytest.

## Global Constraints

- Purely additive to the backend: no existing schema field, service method behavior, or route response shape changes meaning. New fields/endpoints only.
- `list_outstanding_weeks` determines "already paid" via `CashTransaction` existence (ledger truth), not `last_chore_paycheck_week` (which only tracks the single latest release and can't represent an out-of-order past release).
- `lookback_weeks=8` fixed cap, matching `chore_paycheck_history`'s existing `limit=12` convention.
- A past outstanding week is only surfaced if something was actually assigned that week (`assigned_units > 0`); the current week is always surfaced regardless (preserves today's "this week, in progress" visibility).
- No change to `flat` mode, the payday sweep, the kid-facing current-week meter (`bank.astro`, the untouched singular `GET /chore-paycheck/{user_id}` endpoint), or the reminder notification system.
- Spec: `docs/superpowers/specs/2026-07-21-outstanding-chore-paychecks-design.md`

---

### Task 1: Backend — outstanding-weeks computation, week-scoped release, aggregate totals

**Files:**
- Modify: `backend/app/services/bank_service.py` (add `_paycheck_projection` helper, refactor `chore_paycheck_preview` to use it, add `list_outstanding_weeks`, extend `payout_summary`)
- Modify: `backend/app/schemas/bank.py` (add `PayoutPaycheckWeek`, extend `PayoutSummaryKid`/`PayoutSummary`, add `week_of` to `ChorePaycheckReleaseBody`, add `ChorePaycheckOutstandingResponse`)
- Modify: `backend/app/api/routes/bank.py` (release route accepts `week_of`, new `/outstanding` route)
- Modify: `backend/tests/test_chore_paycheck.py` (new tests for `list_outstanding_weeks` and week-targeted release)
- Modify: `backend/tests/test_payout_summary.py` (new tests for the additive `outstanding_weeks`/`outstanding_*_total_cents` fields; existing tests untouched)

**Interfaces:**
- Consumes: existing `BankService._chore_units`, `_chore_week_tasks`, `_chore_paycheck_cents`, `_chore_paycheck_gated`, `_points_rate_cents`, `_family_point_value_cents`, `_family_local_today`, `_week_monday`, `ensure_account`, `CHORE_PAYCHECK_MODES` — all unchanged.
- Produces: `BankService.list_outstanding_weeks(db, target_user, family_id, lookback_weeks=8) -> list[dict]` (each dict: `week_of`, `amount_cents`, `done_points`, `assigned_points`, `pct`, `is_current_week`, `tasks`) — consumed by Task 2's frontend via `payout_summary`'s new `outstanding_weeks` field and the new `GET /chore-paycheck/{user_id}/outstanding` route.

- [ ] **Step 1: Extract the shared per-week projection helper**

In `backend/app/services/bank_service.py`, `chore_paycheck_preview` currently reads (lines 524-561):

```python
    @staticmethod
    async def chore_paycheck_preview(
        db: AsyncSession, target_user: User, family_id: UUID,
        week_of: Optional[date] = None,
    ) -> dict:
        """Projected chore paycheck for a kid's week — feeds the teen's live
        meter and the parent's weekly review. Side-effect free."""
        acct = await BankService.ensure_account(db, target_user)
        if week_of is None:
            week_of = await BankService._family_local_today(db, family_id)
        week_monday = BankService._week_monday(week_of)
        done_u, assigned_u = await BankService._chore_units(
            db, family_id, target_user.id, week_monday
        )
        cap = acct.allowance_cents
        mode = acct.allowance_mode
        if mode == "chore_proportional":
            projected = BankService._chore_paycheck_cents(cap, done_u, assigned_u)
        elif mode == "chore_gated":
            projected = BankService._chore_paycheck_gated(cap, done_u, assigned_u)
        elif mode == "points_rate":
            projected = BankService._points_rate_cents(
                done_u, await BankService._family_point_value_cents(db, family_id)
            )
        else:
            projected = 0
        return {
            "user_id": target_user.id,
            "week_of": week_monday,
            "mode": acct.allowance_mode,
            "cap_cents": cap,
            # Display in points (units carry ×100 grade scale).
            "done_points": round(done_u / 100) if done_u else 0,
            "assigned_points": assigned_u // 100,
            "pct": round(100 * done_u / assigned_u) if assigned_u else 0,
            "projected_cents": projected,
            "already_released": acct.last_chore_paycheck_week == week_monday,
        }
```

Replace it with (extracts the mode-branch math + points/pct shaping into a shared helper that both this method and the new `list_outstanding_weeks` call, so the two never drift):

```python
    @staticmethod
    async def _paycheck_projection(
        db: AsyncSession, acct: KidBankAccount, family_id: UUID, week_monday: date,
    ) -> dict:
        """Pure per-week paycheck math shared by chore_paycheck_preview (single,
        current-week-biased) and list_outstanding_weeks (multi-week scan).
        Includes assigned_units (pre-scale) so callers can decide whether a
        week is worth surfacing without re-deriving it."""
        done_u, assigned_u = await BankService._chore_units(
            db, family_id, acct.user_id, week_monday
        )
        cap = acct.allowance_cents
        mode = acct.allowance_mode
        if mode == "chore_proportional":
            amount = BankService._chore_paycheck_cents(cap, done_u, assigned_u)
        elif mode == "chore_gated":
            amount = BankService._chore_paycheck_gated(cap, done_u, assigned_u)
        elif mode == "points_rate":
            amount = BankService._points_rate_cents(
                done_u, await BankService._family_point_value_cents(db, family_id)
            )
        else:
            amount = 0
        return {
            "week_of": week_monday,
            "cap_cents": cap,
            "amount_cents": amount,
            "done_points": round(done_u / 100) if done_u else 0,
            "assigned_points": assigned_u // 100,
            "pct": round(100 * done_u / assigned_u) if assigned_u else 0,
            "assigned_units": assigned_u,
        }

    @staticmethod
    async def chore_paycheck_preview(
        db: AsyncSession, target_user: User, family_id: UUID,
        week_of: Optional[date] = None,
    ) -> dict:
        """Projected chore paycheck for a kid's week — feeds the teen's live
        meter and the parent's weekly review. Side-effect free."""
        acct = await BankService.ensure_account(db, target_user)
        if week_of is None:
            week_of = await BankService._family_local_today(db, family_id)
        week_monday = BankService._week_monday(week_of)
        p = await BankService._paycheck_projection(db, acct, family_id, week_monday)
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

- [ ] **Step 2: Add `list_outstanding_weeks`**

In the same file, immediately after `chore_paycheck_preview` (before the `chore_paycheck_history` method), add:

```python
    @staticmethod
    async def list_outstanding_weeks(
        db: AsyncSession, target_user: User, family_id: UUID,
        lookback_weeks: int = 8,
    ) -> list[dict]:
        """Every unreleased chore-paycheck week for a kid, oldest first. A
        week counts as released when a CashTransaction(ALLOWANCE, week_of=
        that_monday) exists — the ledger, same source chore_paycheck_history
        already trusts — NOT last_chore_paycheck_week, which only remembers
        the single most recent release and can't represent an out-of-order
        past release. Past weeks are included only when something was
        assigned that week (assigned_units > 0); the current week is always
        included regardless, preserving the existing 'this week, in
        progress' visibility."""
        acct = await BankService.ensure_account(db, target_user)
        if acct.allowance_mode not in CHORE_PAYCHECK_MODES:
            return []
        today = await BankService._family_local_today(db, family_id)
        current_monday = BankService._week_monday(today)

        released_weeks = set((await db.execute(
            select(CashTransaction.week_of).where(
                CashTransaction.user_id == target_user.id,
                CashTransaction.family_id == family_id,
                CashTransaction.type == CashTransactionType.ALLOWANCE,
                CashTransaction.week_of.isnot(None),
            )
        )).scalars().all())

        weeks: list[dict] = []
        for i in range(lookback_weeks - 1, -1, -1):
            week_monday = current_monday - timedelta(weeks=i)
            is_current = week_monday == current_monday
            if week_monday in released_weeks:
                continue
            projection = await BankService._paycheck_projection(
                db, acct, family_id, week_monday
            )
            if not is_current and projection["assigned_units"] <= 0:
                continue
            tasks = await BankService._chore_week_tasks(
                db, family_id, target_user.id, week_monday
            )
            weeks.append({
                "week_of": projection["week_of"],
                "amount_cents": projection["amount_cents"],
                "done_points": projection["done_points"],
                "assigned_points": projection["assigned_points"],
                "pct": projection["pct"],
                "is_current_week": is_current,
                "tasks": tasks,
            })
        return weeks
```

- [ ] **Step 3: Thread `outstanding_weeks` through `payout_summary`**

In the same file, `payout_summary` currently reads (the setup before the loop, then the loop body):

```python
        rows = []
        cash_total = 0
        paycheck_total = 0
        for kid in kids:
            acct = await BankService.ensure_account(db, kid)
            cash = int(kid.cash_cents or 0)
            paycheck = 0
            released = False
            done_points = assigned_points = pct = 0
            tasks: list = []
            if acct.allowance_mode in CHORE_PAYCHECK_MODES:
                preview = await BankService.chore_paycheck_preview(
                    db, kid, family_id
                )
                released = bool(preview["already_released"])
                paycheck = 0 if released else int(preview["projected_cents"])
                done_points = preview["done_points"]
                assigned_points = preview["assigned_points"]
                pct = preview["pct"]
                tasks = await BankService._chore_week_tasks(
                    db, family_id, kid.id, preview["week_of"]
                )
            cash_total += cash
            paycheck_total += paycheck
            rows.append({
                "user_id": kid.id,
                "name": kid.name,
                "cash_pending_cents": cash,
                "paycheck_cents": paycheck,
                "paycheck_released": released,
                "allowance_mode": acct.allowance_mode,
                "done_points": done_points,
                "assigned_points": assigned_points,
                "pct": pct,
                "tasks": tasks,
            })
        return {
            "kids": rows,
            "cash_total_cents": cash_total,
            "paycheck_total_cents": paycheck_total,
            "grand_total_cents": cash_total + paycheck_total,
        }
```

Replace it with (every existing field/line kept verbatim and in the same order — only additions):

```python
        rows = []
        cash_total = 0
        paycheck_total = 0
        outstanding_total = 0
        for kid in kids:
            acct = await BankService.ensure_account(db, kid)
            cash = int(kid.cash_cents or 0)
            paycheck = 0
            released = False
            done_points = assigned_points = pct = 0
            tasks: list = []
            outstanding: list = []
            if acct.allowance_mode in CHORE_PAYCHECK_MODES:
                preview = await BankService.chore_paycheck_preview(
                    db, kid, family_id
                )
                released = bool(preview["already_released"])
                paycheck = 0 if released else int(preview["projected_cents"])
                done_points = preview["done_points"]
                assigned_points = preview["assigned_points"]
                pct = preview["pct"]
                tasks = await BankService._chore_week_tasks(
                    db, family_id, kid.id, preview["week_of"]
                )
                outstanding = await BankService.list_outstanding_weeks(
                    db, kid, family_id
                )
            cash_total += cash
            paycheck_total += paycheck
            outstanding_total += sum(w["amount_cents"] for w in outstanding)
            rows.append({
                "user_id": kid.id,
                "name": kid.name,
                "cash_pending_cents": cash,
                "paycheck_cents": paycheck,
                "paycheck_released": released,
                "allowance_mode": acct.allowance_mode,
                "done_points": done_points,
                "assigned_points": assigned_points,
                "pct": pct,
                "tasks": tasks,
                "outstanding_weeks": outstanding,
            })
        return {
            "kids": rows,
            "cash_total_cents": cash_total,
            "paycheck_total_cents": paycheck_total,
            "grand_total_cents": cash_total + paycheck_total,
            "outstanding_paycheck_total_cents": outstanding_total,
            "outstanding_grand_total_cents": cash_total + outstanding_total,
        }
```

- [ ] **Step 4: Extend the schemas**

In `backend/app/schemas/bank.py`, add after `PayoutTaskDetail` (before `PayoutSummaryKid`):

```python
class PayoutPaycheckWeek(BaseModel):
    """One chore-paycheck week for a kid — either a fully-elapsed unreleased
    week, or the current week in progress. Same per-task shape as history."""

    week_of: date
    amount_cents: int
    done_points: int
    assigned_points: int
    pct: int
    is_current_week: bool
    tasks: list[PayoutTaskDetail] = []
```

Then extend `PayoutSummaryKid` — currently:

```python
class PayoutSummaryKid(BaseModel):
    user_id: UUID
    name: str
    cash_pending_cents: int
    paycheck_cents: int
    paycheck_released: bool
    allowance_mode: str
    # Week progress behind paycheck_cents (0 on flat mode).
    done_points: int = 0
    assigned_points: int = 0
    pct: int = 0
    # Per-task breakdown of the week (empty on flat mode).
    tasks: list[PayoutTaskDetail] = []
```

Add one field at the end:

```python
class PayoutSummaryKid(BaseModel):
    user_id: UUID
    name: str
    cash_pending_cents: int
    paycheck_cents: int
    paycheck_released: bool
    allowance_mode: str
    # Week progress behind paycheck_cents (0 on flat mode).
    done_points: int = 0
    assigned_points: int = 0
    pct: int = 0
    # Per-task breakdown of the week (empty on flat mode).
    tasks: list[PayoutTaskDetail] = []
    # Every unreleased week (past + current), oldest first — empty on flat mode.
    outstanding_weeks: list[PayoutPaycheckWeek] = []
```

Then extend `PayoutSummary` — currently:

```python
class PayoutSummary(BaseModel):
    """Everything a parent currently owes the kids: gig cash awaiting payout
    plus this week's chore paychecks awaiting release."""

    kids: list[PayoutSummaryKid]
    cash_total_cents: int
    paycheck_total_cents: int
    grand_total_cents: int
```

Replace with:

```python
class PayoutSummary(BaseModel):
    """Everything a parent currently owes the kids: gig cash awaiting payout
    plus chore paychecks awaiting release. paycheck_total_cents/grand_total_cents
    stay current-week-only (unchanged); outstanding_*_total_cents sum across
    every outstanding week including past ones — the honest "what do I owe
    right now" figure the payouts dashboard should show."""

    kids: list[PayoutSummaryKid]
    cash_total_cents: int
    paycheck_total_cents: int
    grand_total_cents: int
    outstanding_paycheck_total_cents: int
    outstanding_grand_total_cents: int
```

Then add `week_of` to `ChorePaycheckReleaseBody` — currently:

```python
class ChorePaycheckReleaseBody(BaseModel):
    """Optional parent adjustment (signed cents) added to the computed paycheck —
    a bonus (positive) or dock (negative). Final amount floored at 0."""
    adjustment_cents: int = Field(0, ge=-100000, le=100000)
```

Replace with:

```python
class ChorePaycheckReleaseBody(BaseModel):
    """Optional parent adjustment (signed cents) added to the computed paycheck —
    a bonus (positive) or dock (negative). Final amount floored at 0. week_of
    targets a specific week (any date in it; normalized to that week's Monday
    server-side) — omit to release the current week, unchanged default."""
    adjustment_cents: int = Field(0, ge=-100000, le=100000)
    week_of: Optional[date] = None
```

Finally add, after `PayoutHistoryResponse`:

```python
class ChorePaycheckOutstandingResponse(BaseModel):
    weeks: list[PayoutPaycheckWeek]
```

- [ ] **Step 5: Update the release route + add the outstanding route**

In `backend/app/api/routes/bank.py`, `release_chore_paycheck` currently reads (lines 217-239):

```python
async def release_chore_paycheck(
    user_id: UUID,
    body: Optional[ChorePaycheckReleaseBody] = None,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent releases a teen's chore paycheck for the current (family-local)
    week — credits allowance_cents × completion (± optional adjustment), split
    into jars. Premium-gated (Family-Bank automation); idempotent per (kid, week)."""
    fam = to_uuid_required(current_user.family_id)
    target = await verify_user_in_family(db, user_id, fam)
    if target.role not in (UserRole.CHILD, UserRole.TEEN):
        raise HTTPException(
            status_code=400, detail="Chore paycheck applies to CHILD/TEEN members only"
        )
    await require_feature("family_bank_automation", db, current_user)
    week_of = await BankService._family_local_today(db, fam)
    result = await BankService.release_chore_paycheck(
        db, target, fam, week_of, entitled=True,
        adjustment_cents=(body.adjustment_cents if body else 0),
        released_by=to_uuid_required(current_user.id),
    )
    return ChorePaycheckReleaseResult(**result)
```

Replace with:

```python
async def release_chore_paycheck(
    user_id: UUID,
    body: Optional[ChorePaycheckReleaseBody] = None,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent releases a teen's chore paycheck for a given (family-local)
    week — defaults to the current week when week_of is omitted, so any
    existing caller is unaffected. Credits allowance_cents × completion (±
    optional adjustment), split into jars. Premium-gated (Family-Bank
    automation); idempotent per (kid, week)."""
    fam = to_uuid_required(current_user.family_id)
    target = await verify_user_in_family(db, user_id, fam)
    if target.role not in (UserRole.CHILD, UserRole.TEEN):
        raise HTTPException(
            status_code=400, detail="Chore paycheck applies to CHILD/TEEN members only"
        )
    await require_feature("family_bank_automation", db, current_user)
    today = await BankService._family_local_today(db, fam)
    week_of = (body.week_of if body and body.week_of else None) or today
    week_monday = BankService._week_monday(week_of)
    if week_monday > BankService._week_monday(today):
        raise HTTPException(status_code=422, detail="week_of cannot be in the future")
    result = await BankService.release_chore_paycheck(
        db, target, fam, week_monday, entitled=True,
        adjustment_cents=(body.adjustment_cents if body else 0),
        released_by=to_uuid_required(current_user.id),
    )
    return ChorePaycheckReleaseResult(**result)
```

Then, immediately after the `chore_paycheck_history` route (after its function body, before `@router.post("/transfer", ...)`), add:

```python
@router.get(
    "/chore-paycheck/{user_id}/outstanding", response_model=ChorePaycheckOutstandingResponse
)
async def chore_paycheck_outstanding(
    user_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Every unreleased chore-paycheck week for a kid (oldest first),
    including the current in-progress week. Parent only, read-only."""
    fam = to_uuid_required(current_user.family_id)
    target = await verify_user_in_family(db, user_id, fam)
    weeks = await BankService.list_outstanding_weeks(db, target, fam)
    return ChorePaycheckOutstandingResponse(weeks=weeks)
```

Add `ChorePaycheckOutstandingResponse` to the existing `from app.schemas.bank import (...)` import block at the top of this file (alongside the other schema names already imported there).

- [ ] **Step 6: Backend tests — `list_outstanding_weeks` and week-targeted release**

In `backend/tests/test_chore_paycheck.py`, add (after `test_release_records_week_of`, before `test_release_rejects_flat_mode`):

```python
# ── outstanding weeks (the payout-backlog fix) ────────────────────────────

@pytest.mark.asyncio
async def test_outstanding_weeks_includes_unreleased_past_and_current(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)

    past_week = WEEK - timedelta(days=7)
    current_week = WEEK
    await _chore(db, fam, parent, kid, 100, AssignmentStatus.COMPLETED, week=past_week)
    await _chore(db, fam, parent, kid, 50, AssignmentStatus.COMPLETED, week=current_week)

    weeks = await BankService.list_outstanding_weeks(
        db, kid, fam.id, lookback_weeks=4
    )
    by_week = {w["week_of"]: w for w in weeks}
    assert past_week in by_week
    assert by_week[past_week]["is_current_week"] is False
    assert by_week[past_week]["amount_cents"] == 25000  # 100% of past_week's 100 pts
    assert current_week in by_week
    assert by_week[current_week]["is_current_week"] is True
    # Oldest first.
    assert [w["week_of"] for w in weeks] == sorted(by_week.keys())


@pytest.mark.asyncio
async def test_outstanding_weeks_excludes_already_released(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)

    past_week = WEEK - timedelta(days=7)
    await _chore(db, fam, parent, kid, 100, AssignmentStatus.COMPLETED, week=past_week)
    await BankService.release_chore_paycheck(db, kid, fam.id, past_week, entitled=True)

    weeks = await BankService.list_outstanding_weeks(
        db, kid, fam.id, lookback_weeks=4
    )
    assert past_week not in {w["week_of"] for w in weeks}


@pytest.mark.asyncio
async def test_outstanding_weeks_excludes_past_week_with_nothing_assigned(db):
    fam = await _family(db)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    # No chores at all — only the current week (always included) should appear.
    weeks = await BankService.list_outstanding_weeks(
        db, kid, fam.id, lookback_weeks=4
    )
    assert [w["week_of"] for w in weeks] == [WEEK]


@pytest.mark.asyncio
async def test_release_targets_an_explicit_past_week_independent_of_current(db):
    """Releasing an old week must pay THAT week's math and must not touch
    the current (still in-progress) week's own eligibility."""
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)

    past_week = WEEK - timedelta(days=14)
    mid_week = WEEK - timedelta(days=7)
    await _chore(db, fam, parent, kid, 100, AssignmentStatus.COMPLETED, week=past_week)  # 100%
    await _chore(db, fam, parent, kid, 40, AssignmentStatus.COMPLETED, week=mid_week)    # will stay outstanding
    await _chore(db, fam, parent, kid, 50, AssignmentStatus.COMPLETED, week=WEEK)        # current week

    r = await BankService.release_chore_paycheck(db, kid, fam.id, past_week, entitled=True)
    assert r["amount_cents"] == 25000
    assert r["week_of"] == past_week

    weeks = await BankService.list_outstanding_weeks(db, kid, fam.id, lookback_weeks=4)
    remaining = {w["week_of"] for w in weeks}
    assert past_week not in remaining          # just released
    assert mid_week in remaining               # still outstanding
    assert WEEK in remaining                   # current week, still shown
```

- [ ] **Step 7: Backend tests — additive `payout_summary` fields**

In `backend/tests/test_payout_summary.py`, add (after `test_payout_summary_includes_proportional_paycheck`):

```python
@pytest.mark.asyncio
async def test_payout_summary_outstanding_weeks_includes_backlog(
    client, db_session, test_family, test_parent_user, test_teen_user, parent_headers,
):
    """The new additive fields surface a backlog the old flat fields can't:
    a fully-elapsed unreleased past week plus the current week."""
    await _bank_config(
        db_session, test_teen_user,
        allowance_mode="chore_proportional", allowance_cents=20000,
    )
    current_week = await _current_week_monday(db_session, test_family.id)
    past_week = current_week - timedelta(days=7)
    await _approved_chore(
        db_session, test_family.id, test_parent_user.id, test_teen_user.id, 10, past_week
    )
    await _approved_chore(
        db_session, test_family.id, test_parent_user.id, test_teen_user.id, 5, current_week
    )

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    body = r.json()
    teen = _kid_row(body, test_teen_user.id)

    weeks_seen = {w["week_of"] for w in teen["outstanding_weeks"]}
    assert past_week.isoformat() in weeks_seen
    assert current_week.isoformat() in weeks_seen
    # Old current-week-only fields are completely unaffected by the backlog.
    assert teen["paycheck_cents"] == 20000  # 100% of current_week's 5 pts
    assert body["paycheck_total_cents"] == 20000
    # New totals include the past week's 20000 too.
    assert body["outstanding_paycheck_total_cents"] == 40000
    assert body["outstanding_grand_total_cents"] == 40000
```

- [ ] **Step 8: Run the tests**

If podman is up: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_chore_paycheck.py tests/test_payout_summary.py -v`

Expected: every test passes, including all pre-existing ones in both files (unchanged) plus the new ones added in Steps 6-7.

- [ ] **Step 9: Lint**

Run: `cd backend && ruff check app`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/bank_service.py backend/app/schemas/bank.py backend/app/api/routes/bank.py backend/tests/test_chore_paycheck.py backend/tests/test_payout_summary.py
git commit -m "feat(bank): surface + release every outstanding chore-paycheck week, not just this week"
```

---

### Task 2: Frontend — payouts.astro full queue, family-bank.astro simplified widget

**Files:**
- Modify: `frontend/src/pages/parent/payouts.astro`
- Modify: `frontend/src/pages/parent/settings/family-bank.astro`

**Interfaces:**
- Consumes: `GET /api/bank/payout-summary` (now carrying `outstanding_weeks` per kid + `outstanding_paycheck_total_cents`/`outstanding_grand_total_cents`), `POST /api/bank/chore-paycheck/{user_id}/release` (now accepts `week_of`), `GET /api/bank/chore-paycheck/{user_id}/outstanding` (new, used by family-bank.astro).
- Produces: nothing consumed elsewhere — this is the terminal UI layer.

- [ ] **Step 1: `payouts.astro` — use the outstanding totals for the header**

Lines 20-28 currently:

```astro
// Aggregate owed: gig cash pending + this week's chore paychecks to release.
const { data: summary } = await apiFetch<any>("/api/bank/payout-summary", { token });
const cashTotal = summary?.cash_total_cents ?? 0;
const paycheckTotal = summary?.paycheck_total_cents ?? 0;
const grandTotal = summary?.grand_total_cents ?? 0;
// Kids on a parent-released allowance mode → weekly paycheck rows.
const paycheckKids: any[] = (summary?.kids ?? []).filter(
    (k: any) => k.allowance_mode && k.allowance_mode !== "flat",
);
```

Replace with:

```astro
// Aggregate owed: gig cash pending + every unreleased chore-paycheck week
// (not just this week's — outstanding_* totals include the full backlog).
const { data: summary } = await apiFetch<any>("/api/bank/payout-summary", { token });
const cashTotal = summary?.cash_total_cents ?? 0;
const paycheckTotal = summary?.outstanding_paycheck_total_cents ?? 0;
const grandTotal = summary?.outstanding_grand_total_cents ?? 0;
// Kids with at least one outstanding week (current week is always present
// for any chore-based mode, so this matches "not flat mode" in practice —
// plus it naturally surfaces backlog weeks too).
const paycheckKids: any[] = (summary?.kids ?? []).filter(
    (k: any) => (k.outstanding_weeks ?? []).length > 0,
);
```

- [ ] **Step 2: `payouts.astro` — replace the single-row paycheck section with the outstanding-weeks queue**

Lines 197-282 currently render one row per kid (see the file for the full current block — the section header, description, and the `paycheckKids.map` producing a single `data-paycheck-row` per kid with one amount/release button/task-chip-list/history-toggle).

Replace that entire block (from `{paycheckKids.length > 0 && (` through its closing `)}`) with:

```astro
        {paycheckKids.length > 0 && (
            <>
                <h2 class="text-sm font-bold text-brand-ink pt-2">
                    💵 {lang === "es" ? "Cheques de tareas" : "Chore paychecks"}
                </h2>
                <p class="text-sm text-brand-ink-soft">
                    {lang === "es"
                        ? "Revisa cada semana y libera el pago; al liberarlo se abona al saldo del kid."
                        : "Review each week and release the pay; it credits the kid's balance."}
                </p>
                <div class="space-y-3">
                    {paycheckKids.map((k) => (
                        <div class="rounded-2xl border border-brand-ink/10 bg-brand-cream p-4" data-kid-paycheck-group data-kid-id={k.user_id}>
                            <h3 class="font-bold text-brand-ink mb-2">{k.name}</h3>
                            <div class="space-y-2">
                                {k.outstanding_weeks.map((w: any) => (
                                    <div
                                        class={`relative rounded-xl border-2 p-3 ${w.is_current_week ? "border-brand-mint-deep/40 bg-brand-mint/10" : "border-amber-400/60 bg-amber-50"}`}
                                        data-paycheck-row
                                        data-kid-id={k.user_id}
                                        data-week-of={w.week_of}
                                        data-is-current-week={w.is_current_week ? "1" : "0"}
                                        data-amount-cents={w.amount_cents}
                                    >
                                        <div class="flex items-center justify-between gap-3">
                                            <div>
                                                <p class="text-xs font-bold text-brand-ink flex items-center gap-1.5">
                                                    {!w.is_current_week && (
                                                        <span title={lang === "es" ? "Semana pasada sin liberar" : "Unreleased past week"}>⚠️</span>
                                                    )}
                                                    {dayLabel(w.week_of)}
                                                    {w.is_current_week && (
                                                        <span class="text-[10px] font-semibold text-brand-ink-soft">
                                                            ({lang === "es" ? "en curso" : "in progress"})
                                                        </span>
                                                    )}
                                                </p>
                                                <p class="text-xs text-brand-ink-soft">{w.done_points}/{w.assigned_points} pts · {w.pct}%</p>
                                            </div>
                                            <div class="text-right">
                                                <p class="text-2xl font-extrabold text-brand-mint-deep">{fmt(w.amount_cents)}</p>
                                                <div data-release-slot class="flex items-center gap-1.5 justify-end mt-1">
                                                    <label class="text-[11px] text-brand-ink-soft">{lang === "es" ? "Ajuste $" : "Adj $"}</label>
                                                    <input type="number" step="1" placeholder="0" data-adjust
                                                        class="w-14 rounded-lg border border-brand-ink/20 bg-white px-1.5 py-1 text-xs text-brand-ink focus:outline-none focus:ring-2 focus:ring-brand-mint-deep" />
                                                    <button type="button" data-release
                                                        class="px-3 py-1.5 bg-brand-mint-deep hover:opacity-90 text-white font-semibold text-xs rounded-lg transition-opacity">
                                                        {lang === "es" ? "Liberar" : "Release"}
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                        {(w.tasks ?? []).length > 0 && (
                                            <div class="flex flex-wrap gap-1.5 mt-3">
                                                {w.tasks.map((t: any) => (
                                                    <button
                                                        type="button"
                                                        class={`group px-2 py-1 rounded-lg border text-[11px] font-semibold flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-brand-mint-deep/50 ${chipCls[t.status] ?? chipCls.not_done}`}
                                                    >
                                                        <span aria-hidden="true">{chipIcon[t.status] ?? "·"}</span>
                                                        <span class="max-w-[9rem] truncate">{t.title}</span>
                                                        <span class="opacity-70">{t.earned_points}/{t.points}</span>
                                                        <span class="hidden group-hover:block group-focus:block pointer-events-none absolute left-2 right-2 bottom-full mb-1 z-[60] rounded-xl bg-brand-ink text-brand-cream text-left text-xs font-normal p-3 shadow-lg">
                                                            <span class="block font-bold mb-0.5">{t.title}</span>
                                                            <span class="block">{statusLabel(t)} · {t.earned_points}/{t.points} pts</span>
                                                            <span class="block opacity-80">{dayLabel(t.assigned_date)}</span>
                                                            {t.approval_notes && (
                                                                <span class="block mt-1 opacity-90">📝 {t.approval_notes}</span>
                                                            )}
                                                        </span>
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                        <p class="hidden text-xs mt-2" data-msg></p>
                                    </div>
                                ))}
                            </div>
                            <button
                                type="button"
                                data-history-toggle
                                data-kid-id={k.user_id}
                                class="mt-3 text-xs font-semibold text-brand-mint-deep underline underline-offset-2"
                            >
                                {lang === "es" ? "Ver historial" : "View history"}
                            </button>
                            <div class="hidden mt-2 space-y-2" data-history-panel data-kid-id={k.user_id}></div>
                        </div>
                    ))}
                </div>
            </>
        )}
```

- [ ] **Step 3: `payouts.astro` — replace the release + history JS for the new per-week rows**

The script currently has (find the `// ── Release this week's chore paycheck ──────────────────────────────` comment through its closing `});` — the block that queries `[data-paycheck-row]` and reads a single `data-amount-cents` per kid) and, separately, the `// ── Chore-paycheck history` block that queries `[data-history-toggle]` scoped via `btn.closest("[data-paycheck-row]")`.

Replace BOTH of those blocks (everything from `// ── Release this week's chore paycheck ──` through the end of the `document.querySelectorAll("[data-history-toggle]")...` block, i.e. down to just before the closing `})();` of the whole script) with:

```js
    // ── Release a specific outstanding week's chore paycheck ─────────────
    document.querySelectorAll("[data-paycheck-row]").forEach((row) => {
        const btn = row.querySelector("[data-release]");
        if (!btn) return;
        const weekOf = row.getAttribute("data-week-of");
        const isCurrentWeek = row.getAttribute("data-is-current-week") === "1";
        const projected = parseInt(row.getAttribute("data-amount-cents") || "0", 10);
        const kidId = row.getAttribute("data-kid-id");
        const adjustEl = row.querySelector("[data-adjust]");
        const msgEl = row.querySelector("[data-msg]");
        const slot = row.querySelector("[data-release-slot]");

        btn.addEventListener("click", async () => {
            const adjustCents = Math.round((parseFloat(adjustEl?.value || "0") || 0) * 100);
            btn.disabled = true;
            try {
                const res = await fetch(`/api/bank/chore-paycheck/${kidId}/release`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ week_of: weekOf, adjustment_cents: adjustCents }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    msgEl.textContent = data.detail || `Error ${res.status}`;
                    msgEl.classList.remove("hidden");
                    msgEl.classList.add("text-red-600");
                    btn.disabled = false;
                    return;
                }
                const amt = data.amount_cents || 0;
                if (isCurrentWeek) {
                    // Matches prior UX: the current week's row stays visible
                    // for the rest of the week, just flips to "Released".
                    slot.innerHTML = `<span class="text-xs font-bold text-brand-mint-deep">${
                        lang === "es" ? "Liberado ✓" : "Released ✓"
                    }</span>`;
                } else {
                    // A past week is now historical — drop the row.
                    row.remove();
                }
                adjustTotals(amt, -projected);
                const bal = document.querySelector(
                    `[data-kid-card][data-kid-id="${kidId}"] [data-balance]`
                );
                if (bal) {
                    const cur = Math.round(parseFloat((bal.textContent || "").replace(/[^0-9.]/g, "") || "0") * 100);
                    bal.textContent = fmt(cur + amt);
                }
            } catch (e) {
                msgEl.textContent = lang === "es" ? "Error de red" : "Network error";
                msgEl.classList.remove("hidden");
                msgEl.classList.add("text-red-600");
                btn.disabled = false;
            }
        });
    });

    // ── Chore-paycheck history (lazy-fetched on first expand, per kid) ───
    const histChipCls = {
        credited: "bg-brand-mint/20 border-brand-mint-deep/40 text-brand-mint-deep",
        pending_review: "bg-amber-100 border-amber-300 text-amber-800",
        missed: "bg-red-100 border-red-300 text-red-700",
        not_done: "bg-brand-ink/5 border-brand-ink/15 text-brand-ink-soft",
    };
    const histChipIcon = { credited: "✓", pending_review: "⏳", missed: "✗", not_done: "·" };

    function histStatusLabel(t) {
        if (t.status === "credited") {
            const base = lang === "es" ? "Completada ✓" : "Completed ✓";
            return t.grade === "partial"
                ? `${base} · ${lang === "es" ? "parcial" : "partial"} ${t.partial_credit_pct}%`
                : base;
        }
        if (t.status === "pending_review") return lang === "es" ? "Esperando revisión" : "Awaiting review";
        if (t.status === "missed") return lang === "es" ? "No cumplida" : "Missed";
        return lang === "es" ? "Sin hacer" : "Not done yet";
    }

    function histDayLabel(iso) {
        return new Date(`${iso}T00:00:00`).toLocaleDateString(lang === "es" ? "es-MX" : "en-US", {
            weekday: "short", day: "numeric", month: "short",
        });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));
    }

    function renderWeekTasks(tasks) {
        return (tasks || []).map((t) => `
            <button type="button" class="group px-2 py-1 rounded-lg border text-[11px] font-semibold flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-brand-mint-deep/50 ${histChipCls[t.status] || histChipCls.not_done}">
                <span aria-hidden="true">${histChipIcon[t.status] || "·"}</span>
                <span class="max-w-[9rem] truncate">${escapeHtml(t.title)}</span>
                <span class="opacity-70">${t.earned_points}/${t.points}</span>
                <span class="hidden group-hover:block group-focus:block pointer-events-none absolute left-2 right-2 bottom-full mb-1 z-[60] rounded-xl bg-brand-ink text-brand-cream text-left text-xs font-normal p-3 shadow-lg">
                    <span class="block font-bold mb-0.5">${escapeHtml(t.title)}</span>
                    <span class="block">${histStatusLabel(t)} · ${t.earned_points}/${t.points} pts</span>
                    <span class="block opacity-80">${histDayLabel(t.assigned_date)}</span>
                    ${t.approval_notes ? `<span class="block mt-1 opacity-90">📝 ${escapeHtml(t.approval_notes)}</span>` : ""}
                </span>
            </button>
        `).join("");
    }

    document.querySelectorAll("[data-history-toggle]").forEach((btn) => {
        const kidId = btn.getAttribute("data-kid-id");
        const panel = document.querySelector(`[data-history-panel][data-kid-id="${kidId}"]`);
        let loaded = false;

        btn.addEventListener("click", async () => {
            const opening = panel.classList.contains("hidden");
            if (!opening) {
                panel.classList.add("hidden");
                btn.textContent = lang === "es" ? "Ver historial" : "View history";
                return;
            }
            panel.classList.remove("hidden");
            btn.textContent = lang === "es" ? "Ocultar historial" : "Hide history";
            if (loaded) return;
            loaded = true;

            panel.innerHTML = `<p class="text-xs text-brand-ink-soft">${lang === "es" ? "Cargando…" : "Loading…"}</p>`;
            try {
                const res = await fetch(`/api/bank/chore-paycheck/${kidId}/history`);
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    panel.innerHTML = `<p class="text-xs text-red-600">${data.detail || `Error ${res.status}`}</p>`;
                    return;
                }
                const weeks = data.weeks || [];
                if (weeks.length === 0) {
                    panel.innerHTML = `<p class="text-xs text-brand-ink-soft">${
                        lang === "es" ? "Sin historial todavía." : "No history yet."
                    }</p>`;
                    return;
                }
                panel.innerHTML = weeks.map((w) => `
                    <div class="relative rounded-xl border border-brand-ink/10 bg-white p-3">
                        <div class="flex items-center justify-between">
                            <span class="text-xs font-bold text-brand-ink">${histDayLabel(w.week_of)}</span>
                            <span class="text-sm font-extrabold text-brand-mint-deep">${fmt(w.amount_cents)}</span>
                        </div>
                        <div class="flex flex-wrap gap-1.5 mt-2">${renderWeekTasks(w.tasks)}</div>
                    </div>
                `).join("") + (data.has_more ? `<p class="text-[11px] text-brand-ink-soft">${
                    lang === "es" ? "Mostrando las últimas 12 semanas." : "Showing the last 12 weeks."
                }</p>` : "");
            } catch (e) {
                panel.innerHTML = `<p class="text-xs text-red-600">${
                    lang === "es" ? "Error de red" : "Network error"
                }</p>`;
            }
        });
    });
```

(This is the same history logic as before — only the toggle's kid-scoping changed, since history is now attached once per kid-group instead of once per single row.)

- [ ] **Step 4: `family-bank.astro` — fetch outstanding weeks instead of the single current-week preview**

Lines 51-59 currently:

```astro
// This week's chore paycheck per kid on any parent-released mode.
const CHORE_MODES = ["chore_proportional", "chore_gated", "points_rate"];
const paycheckMap: Record<string, any> = {};
await Promise.all(
    kids.filter((k) => CHORE_MODES.includes(k.allowance_mode)).map(async (k) => {
        const { data } = await apiFetch<any>(`/api/bank/chore-paycheck/${k.user_id}`, { token });
        if (data) paycheckMap[k.user_id] = data;
    })
);
```

Replace with:

```astro
// Outstanding chore-paycheck weeks per kid on any parent-released mode —
// full release UI lives on /parent/payouts now; here we just show a count
// + link so this settings page isn't duplicating that surface.
const CHORE_MODES = ["chore_proportional", "chore_gated", "points_rate"];
const outstandingMap: Record<string, any[]> = {};
await Promise.all(
    kids.filter((k) => CHORE_MODES.includes(k.allowance_mode)).map(async (k) => {
        const { data } = await apiFetch<any>(`/api/bank/chore-paycheck/${k.user_id}/outstanding`, { token });
        if (data?.weeks) outstandingMap[k.user_id] = data.weeks;
    })
);
```

- [ ] **Step 5: `family-bank.astro` — replace the full paycheck card with a compact summary**

Lines 335-370 currently render the full "this week" card (title, amount, progress bar, points, adjustment input, Release/Released button — see the file for the exact current block, delimited by the `{/* Chore paycheck — this week's review + release (parent-released modes) */}` comment through its closing `)}`).

Replace that entire block with:

```astro
                            {/* Chore paycheck — outstanding-weeks summary; full release UI is on /parent/payouts */}
                            {CHORE_MODES.includes(k.allowance_mode) && (outstandingMap[k.user_id] ?? []).length > 0 && (
                                <div class="rounded-xl border-2 border-brand-mint-deep/40 bg-brand-mint/10 p-3" data-paycheck-card data-kid-user={k.user_id}>
                                    <div class="flex items-center justify-between gap-2">
                                        <span class="text-xs font-bold text-brand-ink">
                                            💵 {es
                                                ? `${outstandingMap[k.user_id].length} semana(s) pendiente(s)`
                                                : `${outstandingMap[k.user_id].length} week(s) pending`}
                                        </span>
                                        <span class="text-sm font-extrabold text-brand-mint-deep">
                                            {fmt(outstandingMap[k.user_id].reduce((sum: number, w: any) => sum + w.amount_cents, 0))}
                                        </span>
                                    </div>
                                    <a href="/parent/payouts" class="mt-2 inline-block text-xs font-semibold text-brand-mint-deep underline underline-offset-2">
                                        {es ? "Ir a Pagos →" : "Go to Payouts →"}
                                    </a>
                                </div>
                            )}
```

- [ ] **Step 6: `family-bank.astro` — remove the now-dead release JS**

Remove the entire `// ── Release chore paycheck ───────────────────────────────────────` block (the `document.querySelectorAll<HTMLButtonElement>("[data-release-paycheck]")...` handler) — there is no `data-release-paycheck` button left on this page after Step 5.

- [ ] **Step 7: Verify Astro/TS still type-checks**

Run: `cd frontend && npm run check`
Expected: 0 errors.

- [ ] **Step 8: Manual verification in the browser**

Ensure the stack is up and serving current code (`podman compose up -d --force-recreate backend frontend` if either was already running before this task's edits — a plain `up -d` can silently keep serving stale images).

Using `claude-in-chrome` (load via `ToolSearch` with `query: "select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__tabs_create_mcp"` if not already loaded):

1. Log in as `mom@demo.com` / `password123`.
2. Set up a backlog via curl (parent token from `/api/auth/login`, then as a TEEN/CHILD on `chore_proportional` mode — use an existing demo teen or configure one via `PUT /api/bank/settings/{user_id}` with `{"allowance_mode": "chore_proportional", "allowance_cents": 20000}`): create+complete+approve a task assigned 2 weeks ago (`assigned_date`/`week_of` two Mondays back) so it's an elapsed, unreleased week, and another for the current week.
3. Go to `/parent/payouts`. Confirm: the kid's card shows **two** rows — the past week marked with ⚠️ and a distinct (amber) border, and the current week unmarked (mint border, "en curso"/"in progress"). Confirm the header's "Cheques de tareas" total includes both amounts (not just the current week's).
4. Click **Liberar**/**Release** on the PAST week's row. Confirm: that row disappears, the header total drops by that amount, "Ver historial"/"View history" for that kid now shows it.
5. Click **Liberar**/**Release** on the CURRENT week's row. Confirm: that row stays in place but flips to "Liberado ✓"/"Released ✓" (unchanged from prior behavior).
6. Go to `/parent/settings/family-bank`. Confirm the old full "this week" card is gone, replaced by a compact "N semana(s) pendiente(s): $X — Ir a Pagos →" summary (or nothing, if you released everything in step 4-5 already — re-create a small backlog first if so, to actually see it).
7. Attempt a future `week_of` directly against the API (`POST /api/bank/chore-paycheck/{id}/release` with a `week_of` next week) and confirm 422.

If any check fails, fix before continuing — do not proceed to commit.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/parent/payouts.astro frontend/src/pages/parent/settings/family-bank.astro
git commit -m "feat(bank): payouts page shows every outstanding chore-paycheck week; settings page links to it"
```
