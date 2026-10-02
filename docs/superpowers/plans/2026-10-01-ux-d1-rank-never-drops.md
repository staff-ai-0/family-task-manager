# A Celebrated Rank Never Drops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A kid's shown rank is never lower than the highest rank they have already celebrated, while XP keeps netting parent corrections.

**Architecture:** One new pure function `shown_rank(xp, last_seen_rank)` in `progress_service.py`; the only two places that compute a rank (`ProgressService.progress_for` and the parent hub's `KidSummary`) call it. No stored field, no migration, no frontend code change — one frontend test pins the display when XP is below the rank's floor.

**Tech Stack:** FastAPI + SQLAlchemy async + pytest (backend); Astro 5 + vitest (frontend test only).

**Spec:** `docs/superpowers/specs/2026-10-01-ux-d1-rank-never-drops-design.md`

## Global Constraints

- Work in the worktree `/Users/jc/dev-2026/AgentIA/family-task-manager/.claude/worktrees/ux-d1-rank-floor` (branch `feat/ux-d1-rank-never-drops`). Never `cd` to the main checkout.
- Backend test command (run from the worktree's `backend/`):
  `export TZ=UTC REDIS_URL=redis://localhost:6379/0 UPLOADS_ROOT=/private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad/uploads TEST_DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test; timeout 900 /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/pytest -q --no-cov -p no:warnings <files> </dev/null`
  Never run the whole backend suite (CI runs it). Never run two pytest processes at once.
- Backend lint: `/opt/homebrew/bin/ruff check app` from `backend/`. Zero findings.
- Frontend commands run from the worktree's `frontend/` with `</dev/null` and a `timeout`; the worktree has no `node_modules` (Task 2 Step 1 runs `npm ci`).
- Shown rank `= max(rank_for_xp(xp), last_seen_rank or 1)`, clamped to 1–10. `rank`, `rank_floor_xp` and `next_rank_xp` follow the shown rank; `xp` stays the true, netted XP and may be below `rank_floor_xp`.
- `celebrate_rank` stays `rank if rank > (last_seen_rank or 1) else None`. `ack_rank` is not changed. XP computation is not changed. No schema change.
- Rank thresholds (unchanged): `(0, 100, 300, 600, 1000, 1600, 2500, 3800, 5500, 8000)`.
- Commit trailer: use the attribution line your own session instructs; if you have none, `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **A kid who celebrated the top rank (10) and then loses XP** — expects rank 10 to stay, with no "next rank" and no crash. Pinned by Task 1 `test_the_top_rank_is_held_too`.
2. **A kid who never celebrated anything (`last_seen_rank` NULL — every kid from before D1's celebration, and every new kid)** — expects exactly today's behaviour: rank from XP, celebration when it rises. Pinned by Task 1 `test_never_celebrated_is_rank_one` and `test_an_uncelebrated_rank_is_not_held`.
3. **The parent hub and the kid's own screen disagreeing** — expects the same rank name in both. Pinned by Task 1 `test_parent_hub_shows_the_held_rank`.
4. **A kid's device trying to push the held rank up through the ack** — expects the stored rank never to exceed what XP supports. Pinned by Task 1 `test_ack_cannot_raise_the_held_rank_above_what_xp_supports`.
5. **XP below the shown rank's floor reaching the frontend** — expects an empty bar and the true distance, never a negative bar. Pinned by Task 2.

---

### Task 1: `shown_rank` in the backend (kid progress + parent hub) and docs

**Files:**
- Modify: `backend/app/services/progress_service.py` (new `shown_rank`; `ProgressService.progress_for`)
- Modify: `backend/app/services/oversight_service.py` (import + `KidSummary.rank`)
- Modify: `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md`, `CLAUDE.md`
- Test: `backend/tests/test_progress_rules.py`, `backend/tests/test_progress_api.py`

**Interfaces:**
- Consumes: existing `rank_for_xp(xp: int) -> int`, `rank_floor(rank: int) -> int`, `next_rank_xp(rank: int) -> int | None`, `MAX_RANK = 10`, `User.last_seen_rank` (nullable int).
- Produces: `shown_rank(xp: int, last_seen_rank: int | None) -> int` in `app/services/progress_service.py`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_progress_rules.py`, add `shown_rank,` to the existing `from app.services.progress_service import (...)` list (after `rank_for_xp,`) and append:

```python
class TestShownRank:
    """A celebrated rank never drops; XP itself stays honest."""

    def test_the_celebrated_rank_wins_when_xp_dropped(self):
        assert shown_rank(550, 4) == 4       # XP says rank 3, the kid celebrated rank 4

    def test_the_xp_rank_wins_when_it_is_higher(self):
        assert shown_rank(1200, 4) == 5

    def test_never_celebrated_is_rank_one(self):
        assert shown_rank(0, None) == 1
        assert shown_rank(50, 0) == 1
        assert shown_rank(150, None) == 2    # still follows XP

    def test_out_of_range_values_are_clamped(self):
        assert shown_rank(0, 99) == 10
        assert shown_rank(0, -3) == 1
```

In `backend/tests/test_progress_api.py`, append (the file already defines `_login` and `_xp`, and imports `PointTransaction`, `PT`, `OversightService`):

```python
async def _correction(db, kid, points):
    """A parent correction: a negative row of an earning type (what reopening a chore writes)."""
    db.add(PointTransaction(type=PT.TASK_COMPLETED, points=-points, user_id=kid.id,
                            family_id=kid.family_id, balance_before=0, balance_after=0))
    await db.commit()


class TestCelebratedRankNeverDrops:
    async def test_a_correction_below_a_celebrated_rank_keeps_the_rank(self, client, db_session, test_child_user):
        kid = test_child_user
        await _xp(db_session, kid, 650)                           # rank 4 (600..999)
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 4}, headers=h)).status_code == 204
        await db_session.refresh(kid)
        await _correction(db_session, kid, 100)                   # XP 550 = rank 3 by XP
        body = (await client.get("/api/progress/me", headers=h)).json()
        assert body["xp"] == 550
        assert (body["rank"], body["rank_floor_xp"], body["next_rank_xp"]) == (4, 600, 1000)
        assert body["celebrate_rank"] is None
        await _xp(db_session, kid, 100)                           # earned back: no second celebration
        again = (await client.get("/api/progress/me", headers=h)).json()
        assert (again["rank"], again["xp"], again["celebrate_rank"]) == (4, 650, None)

    async def test_an_uncelebrated_rank_is_not_held(self, client, db_session, test_child_user):
        kid = test_child_user
        await _xp(db_session, kid, 650)                           # reached rank 4, never dismissed the celebration
        await _correction(db_session, kid, 100)
        body = (await client.get("/api/progress/me", headers=await _login(client, "child@test.com"))).json()
        assert (body["rank"], body["rank_floor_xp"], body["next_rank_xp"]) == (3, 300, 600)
        assert body["celebrate_rank"] == 3                        # the rank XP supports is the one to celebrate

    async def test_a_real_rank_up_above_the_held_rank_still_celebrates(self, client, db_session, test_child_user):
        kid = test_child_user
        kid.last_seen_rank = 4
        await db_session.commit()
        await _xp(db_session, kid, 550)                           # below the held rank
        h = await _login(client, "child@test.com")
        assert (await client.get("/api/progress/me", headers=h)).json()["celebrate_rank"] is None
        await _xp(db_session, kid, 500)                           # 1050 = rank 5
        body = (await client.get("/api/progress/me", headers=h)).json()
        assert (body["rank"], body["celebrate_rank"]) == (5, 5)

    async def test_the_top_rank_is_held_too(self, client, db_session, test_child_user):
        kid = test_child_user
        kid.last_seen_rank = 10
        await db_session.commit()
        body = (await client.get("/api/progress/me", headers=await _login(client, "child@test.com"))).json()
        assert (body["rank"], body["rank_floor_xp"], body["next_rank_xp"], body["xp"]) == (10, 8000, None, 0)
        assert body["celebrate_rank"] is None

    async def test_ack_cannot_raise_the_held_rank_above_what_xp_supports(self, client, db_session, test_child_user):
        kid = test_child_user
        await _xp(db_session, kid, 150)                           # rank 2
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 9}, headers=h)).status_code == 204
        await db_session.refresh(kid)
        assert kid.last_seen_rank == 2
        assert (await client.get("/api/progress/me", headers=h)).json()["rank"] == 2

    async def test_parent_hub_shows_the_held_rank(self, db_session, test_family, test_child_user):
        kid = test_child_user
        kid.last_seen_rank = 4
        await db_session.commit()
        await _xp(db_session, kid, 550)
        summary = await OversightService.get_summary(db_session, test_family.id)
        assert summary.members[0].rank == 4
```

- [ ] **Step 2: Run — RED**

Run (from `backend/`, with the Global Constraints env): `… pytest -q --no-cov -p no:warnings tests/test_progress_rules.py tests/test_progress_api.py </dev/null`
Expected:
- `tests/test_progress_rules.py` errors at import (`cannot import name 'shown_rank'`).
- In `tests/test_progress_api.py` (run that file alone to see them), three new tests FAIL: `test_a_correction_below_a_celebrated_rank_keeps_the_rank` (rank 3 instead of 4), `test_the_top_rank_is_held_too` (rank 1 instead of 10) and `test_parent_hub_shows_the_held_rank` (rank 3 instead of 4).
- The other three new API tests already PASS — `test_an_uncelebrated_rank_is_not_held`, `test_a_real_rank_up_above_the_held_rank_still_celebrates` and `test_ack_cannot_raise_the_held_rank_above_what_xp_supports` pin behaviour that must NOT change. Say so in your report; they get their proof in Step 4's mutation check.

- [ ] **Step 3: Implement**

`backend/app/services/progress_service.py` — add directly after the `rank_for_xp` function:

```python
def shown_rank(xp: int, last_seen_rank: int | None) -> int:
    """The rank a kid is SHOWN: never lower than the highest rank they have
    already celebrated (`users.last_seen_rank`), even when a parent correction
    has pulled XP back under that rank's threshold. XP itself stays honest —
    only the rank name is held, so recognition already given is not taken back."""
    celebrated = min(max(int(last_seen_rank or 1), 1), MAX_RANK)
    return max(rank_for_xp(xp), celebrated)
```

In `ProgressService.progress_for`, replace the line `rank = rank_for_xp(xp)` with:

```python
        # Shown rank: XP can sit below this rank's floor after a correction.
        rank = shown_rank(xp, user.last_seen_rank)
```

Leave the rest of the method as it is: `rank_floor_xp=int(rank_floor(rank))` and `next_rank_xp=next_rank_xp(rank)` now follow the shown rank, and `celebrate_rank=rank if rank > seen else None` is unchanged (with the shown rank it is non-null exactly when the XP rank exceeds the last celebrated one).

`backend/app/services/oversight_service.py`:
- in the import `from app.services.progress_service import ProgressService, compute_streak, rank_for_xp`, replace `rank_for_xp` with `shown_rank`;
- in `get_summary`, replace `rank=int(rank_for_xp(xp)),` with `rank=int(shown_rank(xp, kid.last_seen_rank)),`.

- [ ] **Step 4: Run — GREEN**

Run: `… pytest -q --no-cov -p no:warnings tests/test_progress_rules.py tests/test_progress_api.py tests/test_progress_service.py tests/test_badge_api.py tests/test_quest_api.py tests/test_oversight.py tests/test_oversight_today_fields.py tests/test_parent_nudge.py </dev/null`
Expected: all pass. Then `/opt/homebrew/bin/ruff check app` → `All checks passed!` (an unused `rank_for_xp` import in `oversight_service.py` would be reported — it must be gone).

Mutation-check: (a) make `shown_rank` return `rank_for_xp(xp)` → the celebrated-rank tests fail; (b) in `progress_for` put `rank_for_xp(xp)` back → the API tests fail while the pure tests pass; (c) in `oversight_service.py` use `rank_for_xp(xp)` (with its import) → only the hub test fails; (d) make `shown_rank` return `max(rank_for_xp(xp), 4)` regardless of `last_seen_rank` → `test_an_uncelebrated_rank_is_not_held` and `test_ack_cannot_raise_the_held_rank_above_what_xp_supports` fail; (e) in `progress_for` change `celebrate_rank` to always `None` → `test_a_real_rank_up_above_the_held_rank_still_celebrates` fails. Restore after each.

- [ ] **Step 5: Docs**

`docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md` — in the "### Ranks" section, directly after the paragraph that begins "`rank_for_xp(xp)` = highest rank whose threshold ≤ xp.", add:

```markdown
**Shown rank (added 2026-10-01).** The rank a kid sees is `shown_rank(xp, last_seen_rank) = max(rank_for_xp(xp), last_seen_rank or 1)`: a rank the kid has already celebrated never drops, even when a parent correction pulls XP back under its threshold. XP itself keeps netting corrections, so the bar can be empty and "XP to next" is the true distance. A rank reached but not yet celebrated is not held. See `docs/superpowers/specs/2026-10-01-ux-d1-rank-never-drops-design.md`.
```

`CLAUDE.md` — in the Progress row of the "Additional domains" table, directly after the text "+ gig pesos (`gig_earned` ÷ 100)." add this sentence (keep the rest of the row unchanged):

```markdown
 XP nets parent corrections, but the rank SHOWN never drops below the last celebrated one (`shown_rank` = max of the XP rank and `users.last_seen_rank`) — compute a rank through `shown_rank`, never `rank_for_xp` alone.
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/progress_service.py backend/app/services/oversight_service.py backend/tests/test_progress_rules.py backend/tests/test_progress_api.py docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md CLAUDE.md
git commit -m "feat(ux-d1): a celebrated rank never drops (shown_rank)"
```

---

### Task 2: Pin the frontend display when XP is below the rank's floor

**Files:**
- Test: `frontend/test/progress.test.ts`

**Interfaces:**
- Consumes: existing `progressView(resp, skin, lang)` in `frontend/src/lib/progress.ts` and the test file's existing `resp(over)` helper. After Task 1 the API can return `xp` lower than `rank_floor_xp`.
- Produces: nothing new — this task adds tests only. `frontend/src/lib/progress.ts` already clamps the bar at 0 and prints `next_rank_xp − xp`; the tests make that a guarantee.

- [ ] **Step 1: Install dependencies** (once per worktree), from `frontend/`:

Run: `timeout 600 npm ci </dev/null 2>&1 | tail -2`
Expected: `added … packages` with no error.

- [ ] **Step 2: Write the tests** — in `frontend/test/progress.test.ts`, add this block directly before `describe("shouldCelebrate (welcome tour gate)", …)`:

```ts
describe("progressView when XP is below the shown rank's floor (a celebrated rank is held)", () => {
    const held = { xp: 550, rank: 4, rank_floor_xp: 600, next_rank_xp: 1000 };
    it("keeps the rank, empties the bar and gives the true distance", () => {
        const v = progressView(resp(held), "child", "en")!;
        expect(v.rankLabel).toBe("Star · 4/10");
        expect(v.barPct).toBe(0);
        expect(v.toNextLabel).toBe("450 XP to Super Helper");
        expect(v.ladder[3].state).toBe("current");
        expect(v.ladder[2].state).toBe("done");
    });
    it("reads the same in Spanish and for teens", () => {
        expect(progressView(resp(held), "child", "es")!.toNextLabel).toBe("450 XP para Súper Ayudante");
        expect(progressView(resp(held), "teen", "en")!.rankLabel).toBe("Pro · 4/10");
    });
    it("holds the top rank with a full bar", () => {
        const v = progressView(resp({ xp: 0, rank: 10, rank_floor_xp: 8000, next_rank_xp: null }), "child", "en")!;
        expect(v.barPct).toBe(100);
        expect(v.toNextLabel).toBe("Top rank!");
    });
});
```

- [ ] **Step 3: Run — these tests pin EXISTING behaviour, so they pass immediately**

Run: `timeout 300 npx vitest run test/progress.test.ts </dev/null`
Expected: all pass, including the three new tests. A test that passes on first run proves nothing by itself, so prove each one can fail:

- in `frontend/src/lib/progress.ts`, temporarily change `Math.max(0, Math.min(100, Math.round(…)))` in `barPct` to `Math.min(100, Math.round(…))` → the first new test must fail (`barPct` goes negative); restore;
- temporarily change `Math.max(0, next - xp)` to `Math.max(0, next - floor)` in both branches of `toNextLabel` → the first two new tests must fail ("400 XP …"); restore;
- temporarily change `next == null ? 100 :` to `next == null ? 0 :` → the third new test must fail; restore.

Record all three in your report, and confirm with `git diff --stat` that `frontend/src/lib/progress.ts` is unchanged at the end.

- [ ] **Step 4: Full frontend verification** (from `frontend/`):

- `timeout 600 npx vitest run </dev/null 2>&1 | grep -E 'Test Files|Tests '` → all pass.
- `timeout 600 npm run check </dev/null 2>&1 | tail -4` → `0 errors`.

- [ ] **Step 5: Commit**

```bash
git add frontend/test/progress.test.ts
git commit -m "test(ux-d1): pin the progress view when XP is below the held rank's floor"
```

---

## After the last task (controller, not an implementer)

1. Backend, one run: `tests/test_progress_rules.py tests/test_progress_service.py tests/test_progress_api.py tests/test_badge_api.py tests/test_badge_service.py tests/test_quest_api.py tests/test_quest_service.py tests/test_oversight.py tests/test_oversight_today_fields.py tests/test_parent_nudge.py` → all pass; `/opt/homebrew/bin/ruff check app` clean.
2. Whole-branch review (most capable model), one fix wave if needed, scoped re-review.
3. Push → PR → watch CI → merge explicitly once green → sync main → `./scripts/deploy-onprem.sh -y` → verify running images.
4. Prod check, demo family `b8312b5a-c9c0-469f-992f-8dbd412db4a7` only: `sofia.demo` and `diego.demo` show the same ranks as before (Explorer 3/10, Contributor 2/10); `mariana.demo` hub rows show the same rank names. Never touch the real family `1998e48d-2ef0-48b6-a437-cbb730ae935c`.
