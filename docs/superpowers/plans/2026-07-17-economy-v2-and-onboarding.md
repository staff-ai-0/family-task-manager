# Economy v2 + Action-Driven Onboarding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile the points/cash economy into a single canonical model (points = weekly behavior currency that both buys rewards and unlocks a weekly allowance; gigs = extra cash with a payout cadence) and rebuild onboarding around doing the first task + gig on the real UI.

**Architecture:** Backend changes are additive — a new `chore_gated` allowance mode reusing the existing chore-paycheck plumbing, and a new advisory `payout_cadence` column on gig offerings. Frontend rewrites the economy copy (i18n) and layers an action-driven "mission" runner on top of the existing driver.js tour, advancing on real DOM events emitted by the task/gig modals, with graceful fallback to today's tooltip tour.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy (async) · Alembic · PostgreSQL 15 · pytest · Astro 5 · driver.js · Playwright.

## Global Constraints

- Multi-tenant: every query filters by `family_id`; never cross families.
- Migrations: Alembic only, single head; CI runs upgrade → downgrade -1 → upgrade.
- Backend lint: `ruff check app` zero-tolerance (`backend/ruff.toml`).
- Coverage gate ≥70% (`pytest.ini`).
- Aggregated numeric values cast to `int()` before Pydantic assignment (asyncpg `Decimal` → JSON string breaks strict mobile clients).
- Gig **term is per-family configurable** (`gig` default, or `chamba`) — see Task 3B. User-visible copy renders the family's term; DB tables, routes (`/gigs`, `/api/gigs`), and code identifiers stay `gig`. Copy must present a gig/chamba as extra **dinero**, distinct from a **premio** (points reward).
- `payout_cadence` is **advisory only** — reminders/grouping, never blocks a payout, no auto-pay scheduler.
- "250" weekly points total is **derived** (sum of assigned obligatory template points), never a stored config value.
- Backward compatible: gig create/read `payout_cadence` defaults to `immediate`; older mobile clients omitting it keep working.
- Run backend tests inside the container: `podman exec -e PYTHONPATH=/app family_app_backend pytest <path> -v`. Frontend: rebuild container (`podman compose build frontend && podman compose up -d --force-recreate frontend`) before e2e — the dev image bakes `dist/`, so source edits are invisible to Playwright until rebuilt.

---

## File Structure

**Backend**
- `backend/app/services/bank_service.py` — add `chore_gated` to `ALLOWANCE_MODES`, add `_chore_paycheck_gated`, branch preview/release on mode.
- `backend/app/schemas/bank.py` — widen `allowance_mode` Literal.
- `backend/app/models/gig.py` — add `payout_cadence` column + enum + check-constraint.
- `backend/app/api/routes/gigs.py` — add `payout_cadence` to Create/Update/Response schemas + create/update calls.
- `backend/app/services/gig_offering_service.py` — thread `payout_cadence` through `create`/`update`.
- `backend/migrations/versions/2026_07_18_gig_payout_cadence.py` — new migration.
- Tests: `backend/tests/test_bank_chore_gated.py`, `backend/tests/test_gig_payout_cadence.py`.

**Frontend**
- `frontend/src/lib/i18n.ts` — rewrite `intro_banner_*`, fix `tour_p_manage_body`, add mission copy keys, add `intro_banner_learn_more`.
- `frontend/src/lib/tourSteps.ts` — add `MissionStep`/`Mission` shapes + `buildMission`.
- `frontend/src/lib/missionRunner.ts` — NEW client runner (advances on DOM events).
- `frontend/src/components/TaskCreateModal.astro` — emit `ftm:mission` CustomEvents at each step.
- `frontend/src/pages/parent/tasks.astro` — emit FAB-open event; host mission 1.
- `frontend/src/pages/gigs.astro` (or the gig create modal) — emit gig events; host mission 2; add cadence `<select>`.
- `frontend/src/components/ui/InfoBanner.astro` (or wherever the (i) box lives) — readability + GIF slot.
- `frontend/public/onboarding/` — GIF asset dir (placeholders now).
- Tests: `e2e-tests/onboarding-missions.spec.js`, extend `e2e-tests/welcome-tour.spec.js`.

---

## Task 1: `chore_gated` allowance mode (backend)

**Files:**
- Modify: `backend/app/services/bank_service.py:57` (`ALLOWANCE_MODES`), add helper near `_chore_paycheck_cents:409`, branch `chore_paycheck_preview:437` and `release_chore_paycheck:463`.
- Modify: `backend/app/schemas/bank.py:43`
- Test: `backend/tests/test_bank_chore_gated.py`

**Interfaces:**
- Consumes: existing `BankService._chore_points(db, family_id, user_id, week_monday) -> (done, assigned)`, `_chore_paycheck_cents(cap, done, assigned) -> int`.
- Produces: `BankService._chore_paycheck_gated(cap_cents: int, done: int, assigned: int) -> int` (full cap iff `assigned > 0 and done == assigned`, else 0); `chore_gated` accepted anywhere `chore_proportional` is.

- [ ] **Step 1: Write failing unit test for the gated math + mode acceptance**

Create `backend/tests/test_bank_chore_gated.py`:

```python
import pytest
from app.services.bank_service import BankService, ALLOWANCE_MODES


def test_chore_gated_pays_full_cap_at_100pct():
    assert BankService._chore_paycheck_gated(25000, 8, 8) == 25000


def test_chore_gated_pays_zero_below_100pct():
    assert BankService._chore_paycheck_gated(25000, 7, 8) == 0


def test_chore_gated_pays_zero_when_nothing_assigned():
    assert BankService._chore_paycheck_gated(25000, 0, 0) == 0


def test_chore_gated_pays_zero_for_zero_cap():
    assert BankService._chore_paycheck_gated(0, 8, 8) == 0


def test_chore_gated_is_a_registered_mode():
    assert "chore_gated" in ALLOWANCE_MODES
```

- [ ] **Step 2: Run test, verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_bank_chore_gated.py -v`
Expected: FAIL — `AttributeError: _chore_paycheck_gated` and `chore_gated` not in `ALLOWANCE_MODES`.

- [ ] **Step 3: Add the mode + helper**

`bank_service.py:57` — widen the tuple:

```python
ALLOWANCE_MODES = ("flat", "chore_proportional", "chore_gated")
```

Add the helper immediately after `_chore_paycheck_cents` (after line 413):

```python
    @staticmethod
    def _chore_paycheck_gated(cap_cents: int, done: int, assigned: int) -> int:
        """All-or-nothing weekly chore paycheck: the full cap iff every assigned
        obligatory point was completed-and-approved this week, else 0."""
        if assigned <= 0 or cap_cents <= 0:
            return 0
        return cap_cents if done >= assigned else 0
```

- [ ] **Step 4: Run test, verify pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_bank_chore_gated.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Branch preview + release on mode, widen schema**

In `chore_paycheck_preview` (`bank_service.py:437-438`) replace the `proportional` computation:

```python
        mode = acct.allowance_mode
        if mode == "chore_proportional":
            projected = BankService._chore_paycheck_cents(cap, done, assigned)
        elif mode == "chore_gated":
            projected = BankService._chore_paycheck_gated(cap, done, assigned)
        else:
            projected = 0
```

In `release_chore_paycheck` (`bank_service.py:463-477`) replace the guard + base calc:

```python
        if acct.allowance_mode not in ("chore_proportional", "chore_gated"):
            raise HTTPException(
                status_code=422,
                detail="kid is not on a chore-based allowance",
            )
        week_monday = BankService._week_monday(week_of)
        if acct.last_chore_paycheck_week == week_monday:
            raise HTTPException(
                status_code=409,
                detail="chore paycheck already released for this week",
            )
        done, assigned = await BankService._chore_points(
            db, family_id, user.id, week_monday
        )
        if acct.allowance_mode == "chore_gated":
            base = BankService._chore_paycheck_gated(acct.allowance_cents, done, assigned)
        else:
            base = BankService._chore_paycheck_cents(acct.allowance_cents, done, assigned)
```

In `backend/app/schemas/bank.py:43` widen the Literal:

```python
    allowance_mode: Optional[Literal["flat", "chore_proportional", "chore_gated"]] = None
```

- [ ] **Step 6: Write integration test for a gated release**

Append to `backend/tests/test_bank_chore_gated.py` — mirror the setup style of `backend/tests/test_bank.py` (import its fixtures/helpers; inspect that file for the exact fixture names before writing). The test must: create a parent+kid family, set `allowance_mode="chore_gated"` and `allowance_cents=25000`, assign 2 obligatory templates for the current week, complete+approve only 1, assert `chore_paycheck_preview` returns `projected_cents == 0`; complete+approve the 2nd, assert `projected_cents == 25000`; call `release_chore_paycheck` and assert the kid's `cash_cents` rose by 25000 and a second release raises 409.

```python
# Pattern (adapt fixture names to tests/test_bank.py):
@pytest.mark.asyncio
async def test_gated_release_pays_only_at_full_completion(db_session, parent_user, child_user, family):
    from app.services.bank_service import BankService
    # ... set acct.allowance_mode="chore_gated", allowance_cents=25000
    # ... assign two non-bonus templates for BankService._week_monday(today)
    # ... complete+approve ONE
    preview = await BankService.chore_paycheck_preview(db_session, child_user, family.id)
    assert preview["projected_cents"] == 0
    # ... complete+approve the SECOND
    preview = await BankService.chore_paycheck_preview(db_session, child_user, family.id)
    assert preview["projected_cents"] == 25000
```

- [ ] **Step 7: Run full bank suite, verify green**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_bank_chore_gated.py tests/test_bank.py -v`
Expected: PASS (all, including pre-existing proportional tests unaffected).

- [ ] **Step 8: Lint + commit**

```bash
cd backend && ruff check app && cd ..
git add backend/app/services/bank_service.py backend/app/schemas/bank.py backend/tests/test_bank_chore_gated.py
git commit -m "feat(bank): chore_gated allowance mode — full cap iff 100% obligatory done"
```

---

## Task 2: Gig `payout_cadence` — model + migration (backend)

**Files:**
- Modify: `backend/app/models/gig.py` (enum near line 22, column near line 82, `__table_args__:118`)
- Create: `backend/migrations/versions/2026_07_18_gig_payout_cadence.py`
- Test: `backend/tests/test_gig_payout_cadence.py`

**Interfaces:**
- Produces: `GigOffering.payout_cadence` — `String(10)`, NOT NULL, `server_default="immediate"`, values in `{immediate, weekly, biweekly, monthly}`; enum `GigPayoutCadence(str, Enum)`.

- [ ] **Step 1: Write failing model test**

Create `backend/tests/test_gig_payout_cadence.py`:

```python
import pytest
from app.models.gig import GigOffering, GigPayoutCadence


def test_payout_cadence_enum_values():
    assert {c.value for c in GigPayoutCadence} == {
        "immediate", "weekly", "biweekly", "monthly",
    }


def test_gig_offering_has_payout_cadence_column():
    assert "payout_cadence" in GigOffering.__table__.columns
```

- [ ] **Step 2: Run test, verify fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_payout_cadence.py -v`
Expected: FAIL — `ImportError: cannot import name 'GigPayoutCadence'`.

- [ ] **Step 3: Add enum + column + constraint**

In `backend/app/models/gig.py`, add after the other enums (near line 48):

```python
class GigPayoutCadence(str, Enum):
    IMMEDIATE = "immediate"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
```

Add the column after `allow_multiple` (after line 82):

```python
    # Advisory payout rhythm: when the parent is reminded to hand over accrued
    # gig cash (weekly / quincena / mes). Never blocks an early payout and no
    # scheduler auto-pays — reminders + payout-screen grouping only.
    payout_cadence = Column(
        String(10),
        nullable=False,
        default=GigPayoutCadence.IMMEDIATE.value,
        server_default=GigPayoutCadence.IMMEDIATE.value,
    )
```

Add a check-constraint inside `__table_args__` (line 118 — inspect existing content and append):

```python
        CheckConstraint(
            "payout_cadence IN ('immediate','weekly','biweekly','monthly')",
            name="ck_gig_offerings_payout_cadence",
        ),
```

Ensure `CheckConstraint` and `String` are imported at the top of the file (they are — `String` used already; add `CheckConstraint` to the `sqlalchemy` import if absent).

- [ ] **Step 4: Run model test, verify pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_payout_cadence.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the Alembic migration**

Create `backend/migrations/versions/2026_07_18_gig_payout_cadence.py`:

```python
"""Gig payout cadence — advisory payout rhythm on gig offerings.

Revision ID: gig_payout_cadence
Revises: naive_to_timestamptz
"""
import sqlalchemy as sa
from alembic import op

revision = "gig_payout_cadence"
down_revision = "naive_to_timestamptz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gig_offerings",
        sa.Column(
            "payout_cadence",
            sa.String(length=10),
            nullable=False,
            server_default="immediate",
        ),
    )
    op.create_check_constraint(
        "ck_gig_offerings_payout_cadence",
        "gig_offerings",
        "payout_cadence IN ('immediate','weekly','biweekly','monthly')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_gig_offerings_payout_cadence", "gig_offerings", type_="check"
    )
    op.drop_column("gig_offerings", "payout_cadence")
```

- [ ] **Step 6: Run the migration round-trip**

```bash
podman exec family_app_backend alembic upgrade head
podman exec family_app_backend alembic downgrade -1
podman exec family_app_backend alembic upgrade head
```
Expected: all three succeed; head is `gig_payout_cadence`; single head (`alembic heads` shows one).

- [ ] **Step 7: Lint + commit**

```bash
cd backend && ruff check app && cd ..
git add backend/app/models/gig.py backend/migrations/versions/2026_07_18_gig_payout_cadence.py backend/tests/test_gig_payout_cadence.py
git commit -m "feat(gig): payout_cadence column + migration (advisory)"
```

---

## Task 3: Gig `payout_cadence` — schema + route wiring (backend)

**Files:**
- Modify: `backend/app/api/routes/gigs.py:21-59` (Create/Update/Response), `:150` (create_offering call)
- Modify: `backend/app/services/gig_offering_service.py:95-121` (`create`), `123+` (`update`)
- Test: extend `backend/tests/test_gig_payout_cadence.py`

**Interfaces:**
- Consumes: `GigPayoutCadence` from Task 2.
- Produces: `GigOfferingCreate.payout_cadence: str = "immediate"`; service `create(..., payout_cadence="immediate")`; response echoes it.

- [ ] **Step 1: Write failing API round-trip test**

Append to `backend/tests/test_gig_payout_cadence.py` — use the API test client + parent-auth fixtures from `backend/tests/test_gigs.py` (inspect that file for the exact client/auth fixture names first):

```python
@pytest.mark.asyncio
async def test_create_gig_with_weekly_cadence_roundtrips(parent_client):
    resp = await parent_client.post("/api/gigs/offerings", json={
        "title": "Lavar el coche", "points": 50, "payout_cadence": "weekly",
    })
    assert resp.status_code in (200, 201)
    assert resp.json()["payout_cadence"] == "weekly"


@pytest.mark.asyncio
async def test_create_gig_defaults_cadence_immediate(parent_client):
    resp = await parent_client.post("/api/gigs/offerings", json={
        "title": "Sacar basura", "points": 10,
    })
    assert resp.status_code in (200, 201)
    assert resp.json()["payout_cadence"] == "immediate"


@pytest.mark.asyncio
async def test_create_gig_rejects_bad_cadence(parent_client):
    resp = await parent_client.post("/api/gigs/offerings", json={
        "title": "x", "points": 10, "payout_cadence": "hourly",
    })
    assert resp.status_code == 422
```

- [ ] **Step 2: Run, verify fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_payout_cadence.py -k cadence_roundtrips -v`
Expected: FAIL — response has no `payout_cadence` (KeyError / defaults absent).

- [ ] **Step 3: Wire schemas**

In `backend/app/api/routes/gigs.py`, import the enum at top: `from app.models.gig import GigPayoutCadence`. Then:

`GigOfferingCreate` (after line 29) add:
```python
    payout_cadence: Literal["immediate", "weekly", "biweekly", "monthly"] = "immediate"
```
`GigOfferingUpdate` (after line 40) add:
```python
    payout_cadence: Optional[Literal["immediate", "weekly", "biweekly", "monthly"]] = None
```
`GigOfferingResponse` (after line 53) add:
```python
    payout_cadence: str = "immediate"
```

- [ ] **Step 4: Thread through service + create route**

In `gig_offering_service.py` `create` signature (line 105) add `payout_cadence: str = "immediate",` and pass `payout_cadence=payout_cadence,` into the `GigOffering(...)` constructor (line 116). In `update`, if it applies fields from a dict/kwargs, include `payout_cadence` in the allowed set (inspect the update body; apply the same pattern used for `allow_multiple`).

In `gigs.py` `create_offering` (line 155) add `payout_cadence=data.payout_cadence,` to the `GigOfferingService.create(...)` call.

- [ ] **Step 5: Run, verify pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_payout_cadence.py -v`
Expected: PASS (all).

- [ ] **Step 6: Run the full gig suite (no regressions)**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gigs.py -v`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
cd backend && ruff check app && cd ..
git add backend/app/api/routes/gigs.py backend/app/services/gig_offering_service.py backend/tests/test_gig_payout_cadence.py
git commit -m "feat(gig): accept + echo payout_cadence in offering API"
```

---

## Task 3B: Per-family gig term — `gig` | `chamba` (backend + frontend)

**Files:**
- Modify: `backend/app/models/family.py` (column near line 27), `backend/app/schemas/family.py:42` (`FamilyUpdate`), `:70` (`FamilyResponse`)
- Create: `backend/migrations/versions/2026_07_18_family_gig_term.py`
- Create: `frontend/src/lib/gigTerm.ts`
- Modify: gig-facing i18n strings + gig nav/page labels to render the resolved term
- Test: `backend/tests/test_family_gig_term.py`

**Interfaces:**
- Produces (backend): `Family.gig_term` `String(10)` NOT NULL `server_default="gig"`, check `('gig','chamba')`; `FamilyUpdate.gig_term: Optional[Literal["gig","chamba"]]`; `FamilyResponse.gig_term: str = "gig"`.
- Produces (frontend): `gigTerm(term: string, lang: string) -> { one: string; many: string; One: string; Many: string }`.
- Migration chains: `down_revision = "gig_payout_cadence"` (keeps a single head).

- [ ] **Step 1: Write failing backend test**

Create `backend/tests/test_family_gig_term.py` (use the API client + parent-auth fixtures from `backend/tests/test_families.py` — inspect for exact names):

```python
import pytest


def test_family_has_gig_term_column():
    from app.models.family import Family
    assert "gig_term" in Family.__table__.columns


@pytest.mark.asyncio
async def test_gig_term_defaults_to_gig(parent_client):
    resp = await parent_client.get("/api/families/me")
    assert resp.status_code == 200
    assert resp.json()["gig_term"] == "gig"


@pytest.mark.asyncio
async def test_parent_can_set_gig_term_to_chamba(parent_client):
    resp = await parent_client.patch("/api/families/me", json={"gig_term": "chamba"})
    assert resp.status_code == 200
    assert resp.json()["gig_term"] == "chamba"


@pytest.mark.asyncio
async def test_gig_term_rejects_bad_value(parent_client):
    resp = await parent_client.patch("/api/families/me", json={"gig_term": "trabajo"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run, verify fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_family_gig_term.py -v`
Expected: FAIL — no `gig_term` column.

- [ ] **Step 3: Add the column**

In `backend/app/models/family.py` after `rest_days` (line 27):

```python
    # User-visible term for the gig board, per family. DB/routes stay "gig".
    gig_term = Column(String(10), nullable=False, default="gig", server_default="gig")
```

Add to the model's `__table_args__` (create it if absent) a check-constraint:

```python
    __table_args__ = (
        CheckConstraint("gig_term IN ('gig','chamba')", name="ck_families_gig_term"),
    )
```

(Import `CheckConstraint` from `sqlalchemy` at the top.)

- [ ] **Step 4: Add the migration**

Create `backend/migrations/versions/2026_07_18_family_gig_term.py`:

```python
"""Per-family gig term (gig | chamba).

Revision ID: family_gig_term
Revises: gig_payout_cadence
"""
import sqlalchemy as sa
from alembic import op

revision = "family_gig_term"
down_revision = "gig_payout_cadence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column("gig_term", sa.String(length=10), nullable=False, server_default="gig"),
    )
    op.create_check_constraint(
        "ck_families_gig_term", "families", "gig_term IN ('gig','chamba')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_families_gig_term", "families", type_="check")
    op.drop_column("families", "gig_term")
```

- [ ] **Step 5: Wire the schemas**

`backend/app/schemas/family.py` — in `FamilyUpdate` (line 42) add:
```python
    gig_term: Optional[Literal["gig", "chamba"]] = None
```
In `FamilyResponse` (line 70) add:
```python
    gig_term: str = "gig"
```
(Ensure `Literal` is imported from `typing`.) Confirm `update_family` (`families.py:148`) applies incoming fields generically (e.g. `model_dump(exclude_unset=True)`); if it whitelists fields, add `gig_term`.

- [ ] **Step 6: Run backend test + migration round-trip, verify pass**

```bash
podman exec family_app_backend alembic upgrade head
podman exec family_app_backend alembic downgrade -1
podman exec family_app_backend alembic upgrade head
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_family_gig_term.py -v
```
Expected: migrations succeed, single head `family_gig_term`, tests PASS.

- [ ] **Step 7: Frontend term resolver**

Create `frontend/src/lib/gigTerm.ts`:

```typescript
/**
 * Resolve a family's gig term into the four cased/pluralized forms used in copy.
 * DB/routes stay "gig"; only user-visible strings vary. English keeps gig/gigs
 * even when the family picked "chamba" is a Spanish label — callers pass the
 * family's stored term and the active lang, and we honor the term in both.
 */
export function gigTerm(term: string, _lang: string): { one: string; many: string; One: string; Many: string } {
    const t = term === "chamba" ? "chamba" : "gig";
    const one = t;
    const many = t === "chamba" ? "chambas" : "gigs";
    const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
    return { one, many, One: cap(one), Many: cap(many) };
}
```

- [ ] **Step 8: Render the term in gig-facing labels**

In the gigs page + nav, replace literal "Gig"/"Gigs" labels with the resolved term. The family's `gig_term` is available in the Astro frontmatter (fetched via `/api/families/me`); pass it into `gigTerm()` and substitute:
- Nav label ("Gigs" → `${many.charAt(0).toUpperCase()+...}` i.e. `Many`)
- Gigs page `<h1>` and "+ Nueva Gig" → `+ Nueva ${One}`
- The gig subtitle and mission copy keys `m_gig_*` that say "gig(s)" — interpolate the term. For i18n strings, convert the affected keys to functions taking the term, OR post-process the rendered string with a `.replace(/\bgigs?\b/i, ...)` helper limited to the gig surface. Prefer explicit interpolation for the ~6 gig strings.

- [ ] **Step 9: Rebuild + astro check + commit**

```bash
cd frontend && npm run check && cd ..
podman compose build frontend && podman compose up -d --force-recreate frontend && sleep 3
git add backend/app/models/family.py backend/app/schemas/family.py backend/migrations/versions/2026_07_18_family_gig_term.py backend/tests/test_family_gig_term.py frontend/src/lib/gigTerm.ts frontend/src
git commit -m "feat(gig): per-family gig term (gig|chamba) — backend field + frontend term resolver"
```

---

## Task 4: Economy copy rewrite v2 (frontend)

**Files:**
- Modify: `frontend/src/lib/i18n.ts:450-451` (EN `intro_banner_*`), `:969-970` (ES), `tour_p_manage_body` (both langs), add `intro_banner_learn_more` key.
- Modify: `frontend/docs/USER_GUIDE_EN.md`, `frontend/docs/USER_GUIDE_ES.md` (economy section).
- Test: `e2e-tests/economy-copy.spec.js`

**Interfaces:**
- Produces: i18n keys `intro_banner_title`, `intro_banner_body`, `intro_banner_learn_more` (v2 wording, no "never turn into cash").

- [ ] **Step 1: Write failing e2e assertion on v2 copy**

Create `e2e-tests/economy-copy.spec.js`:

```javascript
const { test, expect } = require('@playwright/test');
const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

async function login(page, email, pw) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', pw);
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
}

test('kid dashboard economy banner uses v2 copy (no "never become cash")', async ({ page }) => {
  await login(page, 'emma@demo.com', 'password123');
  const body = await page.locator('body').innerText();
  expect(body).not.toContain('nunca se vuelven dinero');
  expect(body).not.toContain('never turn into cash');
  // v2 mentions the domingo/allowance unlock
  expect(body.toLowerCase()).toMatch(/domingo|allowance|desbloqu|unlock/);
});
```

- [ ] **Step 2: Run, verify fail**

Run: `cd e2e-tests && npx playwright test economy-copy.spec.js --reporter=list`
Expected: FAIL — current copy still contains "nunca se vuelven dinero".

- [ ] **Step 3: Rewrite the EN keys** (`i18n.ts:450-451`)

```javascript
        intro_banner_title: "How points & cash work",
        intro_banner_body: "Two currencies. Finish your required chores to earn points — spend them on rewards, and finishing them all unlocks your weekly allowance. Gigs are extra cash a parent pays you.",
        intro_banner_learn_more: "See how it works",
```

- [ ] **Step 4: Rewrite the ES keys** (`i18n.ts:969-970`)

```javascript
        intro_banner_title: "Cómo funcionan los puntos y el dinero",
        intro_banner_body: "Dos monedas. Termina tus tareas obligatorias para ganar puntos — cámbialos por premios, y al terminarlas todas desbloqueas tu domingo semanal. Las gigs son dinero extra que un padre te paga.",
        intro_banner_learn_more: "Ver cómo funciona",
```

- [ ] **Step 5: Fix `tour_p_manage_body` (both langs)**

Find `tour_p_manage_body` in `i18n.ts`. Replace EN with:
```javascript
        tour_p_manage_body: "Your home base. Tap the + on Tasks to create your first chore, publish gigs, review proof, and invite your family.",
```
Replace ES with:
```javascript
        tour_p_manage_body: "Tu base. Toca el + en Tareas para crear tu primera tarea, publica gigs, revisa la evidencia e invita a tu familia.",
```

- [ ] **Step 6: Wire the "learn more" link + update USER_GUIDE economy section**

Where `intro_banner_body` renders (grep `intro_banner_body` in `frontend/src`), append a link to `/ayuda` (ES) / `/help` (EN) using `intro_banner_learn_more`. Update the economy section of both USER_GUIDE files to describe: obligatory chores → points → (premios + weekly domingo when all done); gigs → extra cash with a payout rhythm.

- [ ] **Step 7: Rebuild frontend, run e2e, verify pass**

```bash
podman compose build frontend && podman compose up -d --force-recreate frontend && sleep 3
cd e2e-tests && npx playwright test economy-copy.spec.js --reporter=list
```
Expected: PASS.

- [ ] **Step 8: astro check + commit**

```bash
cd frontend && npm run check && cd ..
git add frontend/src/lib/i18n.ts frontend/docs/USER_GUIDE_EN.md frontend/docs/USER_GUIDE_ES.md e2e-tests/economy-copy.spec.js
git commit -m "feat(copy): economy v2 banner + tour manage copy (points unlock domingo; gigs=extra cash)"
```

---

## Task 5: Readability polish + GIF slots (frontend)

**Files:**
- Modify: the info-banner / (i)-box component (grep `intro_banner_title` to locate; likely a dashboard partial or `InfoBanner.astro`).
- Create: `frontend/public/onboarding/.gitkeep` (asset dir).
- Test: manual + astro check (visual; no e2e assertion beyond render).

**Interfaces:** none consumed/produced by other tasks.

- [ ] **Step 1: Bump info-banner body legibility**

In the info-banner component, raise the body text from its current small/soft treatment. Concretely: change the body `<p>` classes from `text-xs`/`text-brand-ink-soft` to `text-sm leading-relaxed text-brand-ink` (match the body scale used in card descriptions elsewhere). Verify contrast in both light and dark via `@media (prefers-color-scheme)` — if the banner hardcodes a light bg, ensure the text token has ≥4.5:1 against it.

- [ ] **Step 2: Shorten the (i) boxes to 1–2 lines + "ver más"**

For each multi-line (i) info box, truncate the copy to ≤2 lines and append the `intro_banner_learn_more` link to `/ayuda`|`/help`. (The v2 `intro_banner_body` from Task 4 is already ≤2 lines — apply the same discipline to any other verbose (i) box surfaced in onboarding.)

- [ ] **Step 3: Scaffold a GIF slot**

Create `frontend/public/onboarding/.gitkeep`. In the info-banner (or help page) add an optional lazy image slot that renders only when an asset path is provided:

```astro
{gifSrc && (
  <img src={gifSrc} alt={gifAlt} loading="lazy"
       class="mt-2 rounded-lg border border-brand-ink/10 max-w-full w-full h-auto" />
)}
```

Leave `gifSrc` unset/undefined for now (slots render nothing until asset files land under `/onboarding/`). Document the intended filenames in a code comment: `first-task.gif`, `first-gig.gif`.

- [ ] **Step 4: astro check + commit**

```bash
cd frontend && npm run check && cd ..
git add frontend/src frontend/public/onboarding/.gitkeep
git commit -m "feat(onboarding): info-banner readability + lazy GIF slots (assets follow-up)"
```

---

## Task 6: Mission scaffolding — shapes + DOM event emission (frontend)

**Files:**
- Modify: `frontend/src/lib/tourSteps.ts` (add `MissionStep`/`Mission` types + `buildMission`)
- Modify: `frontend/src/components/TaskCreateModal.astro` (emit `ftm:mission` events)
- Modify: `frontend/src/pages/parent/tasks.astro` (emit FAB-open event)
- Add mission copy keys to `frontend/src/lib/i18n.ts`
- Test: none yet (event emission verified in Task 7's e2e)

**Interfaces:**
- Produces: `interface MissionStep { element: string; title: string; description: string; side?: string; advanceOn: { event: string; }; }`; `interface Mission { id: string; steps: MissionStep[]; }`; `buildMission(id: "first-task"|"first-gig", lang: string): Mission`.
- Produces: `window.dispatchEvent(new CustomEvent("ftm:mission", { detail: { signal: string } }))` fired from the task modal at each milestone. Signals: `task-modal-open`, `task-template-selected`, `task-assignee-selected`, `task-created`.

- [ ] **Step 1: Add mission types + builder to `tourSteps.ts`**

Append to `frontend/src/lib/tourSteps.ts`:

```typescript
export interface MissionStep {
    element: string;
    title: string;
    description: string;
    side?: "top" | "bottom" | "left" | "right";
    /** The real DOM signal (CustomEvent detail.signal) that completes this step. */
    advanceOn: { signal: string };
}

export interface Mission {
    id: string;
    steps: MissionStep[];
}

export function buildMission(id: "first-task" | "first-gig", lang: string): Mission {
    if (id === "first-task") {
        return {
            id,
            steps: [
                { element: '[data-tour="task-fab"]', advanceOn: { signal: "task-modal-open" },
                  title: t(lang, "m_task_open_title"), description: t(lang, "m_task_open_body"), side: "left" },
                { element: '[data-tour="task-template-grid"]', advanceOn: { signal: "task-template-selected" },
                  title: t(lang, "m_task_tpl_title"), description: t(lang, "m_task_tpl_body"), side: "top" },
                { element: '[data-tour="task-assign"]', advanceOn: { signal: "task-assignee-selected" },
                  title: t(lang, "m_task_assign_title"), description: t(lang, "m_task_assign_body"), side: "top" },
                { element: '[data-tour="task-submit"]', advanceOn: { signal: "task-created" },
                  title: t(lang, "m_task_create_title"), description: t(lang, "m_task_create_body"), side: "top" },
            ],
        };
    }
    return {
        id,
        steps: [
            { element: '[data-tour="gig-fab"]', advanceOn: { signal: "gig-modal-open" },
              title: t(lang, "m_gig_open_title"), description: t(lang, "m_gig_open_body"), side: "left" },
            { element: '[data-tour="gig-cadence"]', advanceOn: { signal: "gig-cadence-set" },
              title: t(lang, "m_gig_cadence_title"), description: t(lang, "m_gig_cadence_body"), side: "top" },
            { element: '[data-tour="gig-submit"]', advanceOn: { signal: "gig-created" },
              title: t(lang, "m_gig_create_title"), description: t(lang, "m_gig_create_body"), side: "top" },
        ],
    };
}
```

- [ ] **Step 2: Add the mission copy keys to `i18n.ts`** (EN + ES blocks)

Add these keys to both language objects (EN values shown; write matching ES):

```javascript
        m_task_open_title: "Create your first task",
        m_task_open_body: "Tap the + to open the new-task form.",
        m_task_tpl_title: "Pick a chore",
        m_task_tpl_body: "Choose a template — e.g. Wash the dishes.",
        m_task_assign_title: "Assign it",
        m_task_assign_body: "Pick who does it. Auto shares points fairly.",
        m_task_create_title: "Set points & create",
        m_task_create_body: "Points count toward the weekly total that unlocks the domingo. Tap Create.",
        m_gig_open_title: "Post your first gig",
        m_gig_open_body: "Gigs are extra cash — tap + to add one.",
        m_gig_cadence_title: "When it pays out",
        m_gig_cadence_body: "Weekly, quincena, or monthly — when you hand over the cash.",
        m_gig_create_title: "Publish it",
        m_gig_create_body: "Tap Publish. A kid can now claim it for real cash.",
```

ES equivalents (add to the ES object): `m_task_open_title: "Crea tu primera tarea"`, `m_task_open_body: "Toca el + para abrir el formulario."`, `m_task_tpl_title: "Elige una tarea"`, `m_task_tpl_body: "Escoge una plantilla — ej. Lavar los platos."`, `m_task_assign_title: "Asígnala"`, `m_task_assign_body: "Elige quién la hace. Auto reparte los puntos."`, `m_task_create_title: "Puntos y crear"`, `m_task_create_body: "Los puntos suman al total semanal que desbloquea el domingo. Toca Crear tarea."`, `m_gig_open_title: "Publica tu primera gig"`, `m_gig_open_body: "Las gigs son dinero extra — toca + para crear una."`, `m_gig_cadence_title: "Cuándo se paga"`, `m_gig_cadence_body: "Semanal, quincenal o mensual — cuándo entregas el dinero."`, `m_gig_create_title: "Publícala"`, `m_gig_create_body: "Toca Publicar. Un hijo ya puede tomarla por dinero real."`

- [ ] **Step 3: Add `data-tour` anchors + emit events in the task modal**

In `frontend/src/pages/parent/tasks.astro`, add `data-tour="task-fab"` to the `+` FAB button. In its click handler (or the modal open), dispatch:
```javascript
window.dispatchEvent(new CustomEvent("ftm:mission", { detail: { signal: "task-modal-open" } }));
```
In `frontend/src/components/TaskCreateModal.astro`: add `data-tour="task-template-grid"` to the template grid, `data-tour="task-assign"` to the assignee control, `data-tour="task-submit"` to the "Crear tarea" button. Dispatch the matching signal at each real action: on a template being chosen (`task-template-selected`), on an assignee selected (`task-assignee-selected`), and after a successful create (`task-created`, dispatch right before/after the existing success path).

- [ ] **Step 4: astro check + commit**

```bash
cd frontend && npm run check && cd ..
git add frontend/src/lib/tourSteps.ts frontend/src/lib/i18n.ts frontend/src/pages/parent/tasks.astro frontend/src/components/TaskCreateModal.astro
git commit -m "feat(onboarding): mission shapes + real-DOM event emission for the task flow"
```

---

## Task 7: Mission runner + Mission 1 wired end-to-end (frontend)

**Files:**
- Create: `frontend/src/lib/missionRunner.ts`
- Modify: `frontend/src/pages/parent/index.astro` (launch mission from checklist) + the checklist item markup
- Test: `e2e-tests/onboarding-missions.spec.js`

**Interfaces:**
- Consumes: `buildMission` (Task 6), `ftm:mission` CustomEvents (Task 6), driver.js via existing `frontend/src/lib/tour.ts` helpers.
- Produces: `runMission(mission: Mission, lang: string): void` — highlights step N, advances when the matching `ftm:mission` signal fires, persists progress in `sessionStorage["ftm_mission_" + mission.id]`, falls back to a Next button after a 15s timeout per step, acks the tour on completion.

- [ ] **Step 1: Write the mission runner**

Create `frontend/src/lib/missionRunner.ts`:

```typescript
import { driver } from "driver.js";
import type { Mission } from "./tourSteps";

/**
 * Action-driven onboarding: highlight a real UI target and advance ONLY when the
 * user performs the real action (a `ftm:mission` CustomEvent whose detail.signal
 * matches the step's advanceOn.signal). If the expected signal doesn't fire
 * within a timeout, degrade to a Next button so a moved target is never a dead
 * end. Progress persists across page navigations via sessionStorage.
 */
const FALLBACK_MS = 15000;

export function runMission(mission: Mission, lang: string): void {
    const key = "ftm_mission_" + mission.id;
    let idx = Number(sessionStorage.getItem(key) || "0");
    if (idx >= mission.steps.length) return;

    const d = driver({ showButtons: ["close"], allowClose: true });
    let fallbackTimer: number | undefined;

    const showStep = () => {
        const step = mission.steps[idx];
        const el = document.querySelector(step.element);
        if (!el) {
            // Target absent on this page — end gracefully; checklist deep-link
            // remains the path forward.
            cleanup();
            return;
        }
        d.highlight({
            element: step.element,
            popover: { title: step.title, description: step.description, side: step.side },
        });
        clearTimeout(fallbackTimer);
        fallbackTimer = window.setTimeout(showFallbackNext, FALLBACK_MS);
    };

    const showFallbackNext = () => {
        const step = mission.steps[idx];
        d.highlight({
            element: step.element,
            popover: {
                title: step.title, description: step.description, side: step.side,
                showButtons: ["next", "close"],
                onNextClick: () => advance(),
            },
        });
    };

    const advance = () => {
        clearTimeout(fallbackTimer);
        idx += 1;
        sessionStorage.setItem(key, String(idx));
        if (idx >= mission.steps.length) {
            sessionStorage.removeItem(key);
            d.destroy();
            window.dispatchEvent(new CustomEvent("ftm:mission-complete", { detail: { id: mission.id } }));
            return;
        }
        showStep();
    };

    const onSignal = (e: Event) => {
        const detail = (e as CustomEvent).detail;
        if (detail?.signal === mission.steps[idx]?.advanceOn.signal) advance();
    };

    const cleanup = () => {
        clearTimeout(fallbackTimer);
        window.removeEventListener("ftm:mission", onSignal);
        d.destroy();
    };

    window.addEventListener("ftm:mission", onSignal);
    d.setConfig({ onDestroyed: cleanup });
    showStep();
}
```

- [ ] **Step 2: Launch Mission 1 from the checklist "Crea tu primera tarea" item**

In `frontend/src/pages/parent/index.astro`, add `data-mission="first-task"` to the "Crea tu primera tarea" checklist row (and a "Tomar el recorrido guiado" that starts it). Add a client script:

```html
<script>
  import { buildMission } from "@lib/tourSteps";
  import { runMission } from "@lib/missionRunner";
  document.addEventListener("astro:page-load", () => {
    const lang = document.documentElement.lang === "es" ? "es" : "en";
    // Resume an in-progress mission after navigating tasks→dashboard→gigs.
    for (const id of ["first-task", "first-gig"] as const) {
      if (sessionStorage.getItem("ftm_mission_" + id)) runMission(buildMission(id, lang), lang);
    }
    document.querySelectorAll("[data-mission]").forEach((el) =>
      el.addEventListener("click", () => {
        const id = el.getAttribute("data-mission") as "first-task" | "first-gig";
        sessionStorage.setItem("ftm_mission_" + id, "0");
        // Navigate to the page that hosts step 1's target, then the resume
        // block above picks it up on page-load.
        window.location.href = id === "first-task" ? "/parent/tasks" : "/gigs";
      }));
  });
</script>
```

Also add the same resume block to `frontend/src/pages/parent/tasks.astro` and the gigs page so a mission started elsewhere resumes when its target page loads.

- [ ] **Step 3: Write the e2e for Mission 1 advancing on real actions**

Create `e2e-tests/onboarding-missions.spec.js`:

```javascript
const { test, expect } = require('@playwright/test');
const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', 'mom@demo.com');
  await page.fill('input[name="password"]', 'password123');
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
}

test('mission 1 advances when the task modal actually opens', async ({ page }) => {
  await login(page);
  await page.evaluate(() => sessionStorage.setItem('ftm_mission_first-task', '0'));
  await page.goto(`${BASE_URL}/parent/tasks`);
  // Step 1 highlights the FAB.
  await expect(page.locator('.driver-popover')).toBeVisible({ timeout: 5000 });
  // Perform the REAL action — open the modal — and the mission should advance
  // to the template step (not wait for a Next button).
  await page.click('[data-tour="task-fab"]');
  await expect(page.locator('.driver-popover')).toContainText(/plantilla|template|chore|tarea/i, { timeout: 5000 });
});

test('mission target absent → no dead end (popover closes gracefully)', async ({ page }) => {
  await login(page);
  await page.evaluate(() => sessionStorage.setItem('ftm_mission_first-task', '3'));
  // Land on a page WITHOUT the submit target present standalone.
  await page.goto(`${BASE_URL}/dashboard`);
  // Runner finds no element for step 3 here and ends without throwing.
  await expect(page.locator('.driver-popover')).toHaveCount(0, { timeout: 5000 });
});
```

- [ ] **Step 4: Rebuild + run e2e, verify fail→fix→pass**

```bash
podman compose build frontend && podman compose up -d --force-recreate frontend && sleep 3
cd e2e-tests && npx playwright test onboarding-missions.spec.js --reporter=list
```
Expected first run may FAIL if `data-tour` anchors or signals are misnamed — reconcile selector/signal names with Task 6, rebuild, rerun until PASS.

- [ ] **Step 5: astro check + commit**

```bash
cd frontend && npm run check && cd ..
git add frontend/src/lib/missionRunner.ts frontend/src/pages/parent/index.astro frontend/src/pages/parent/tasks.astro e2e-tests/onboarding-missions.spec.js
git commit -m "feat(onboarding): action-driven mission runner + first-task mission"
```

---

## Task 8: Mission 2 (create gig) + cadence field in the gig form (frontend)

**Files:**
- Modify: the gig create form/modal (grep `Nueva Gig` / `+ Nueva Gig` in `frontend/src`)
- Modify: `frontend/src/pages/gigs.astro` (host + resume mission 2)
- Test: extend `e2e-tests/onboarding-missions.spec.js`

**Interfaces:**
- Consumes: `payout_cadence` API field (Task 3), `buildMission("first-gig")` (Task 6), `runMission` (Task 7).

- [ ] **Step 1: Add the cadence `<select>` to the gig form**

In the gig create form, add a `payout_cadence` select with `data-tour="gig-cadence"` and options `immediate|weekly|biweekly|monthly` (labels ES: Inmediato / Semanal / Quincenal / Mensual). Include its value in the POST body to `/api/gigs/offerings`. Dispatch `gig-cadence-set` on change and `gig-modal-open` / `gig-created` at the matching milestones (mirror Task 6's task-modal pattern). Add `data-tour="gig-fab"` to the "+ Nueva Gig" button and `data-tour="gig-submit"` to Publicar.

- [ ] **Step 2: Write the e2e for cadence persistence via the UI**

Append to `e2e-tests/onboarding-missions.spec.js`:

```javascript
test('gig form posts payout_cadence and it persists', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE_URL}/gigs`);
  await page.click('[data-tour="gig-fab"]');
  await page.fill('input[name="title"], #gig-title', 'Lavar el coche');
  await page.fill('input[name="points"], #gig-points', '50');
  await page.selectOption('[data-tour="gig-cadence"]', 'weekly');
  await page.click('[data-tour="gig-submit"]');
  // The new gig card renders; reload and confirm the cadence stuck via API.
  const resp = await page.request.get(`${BASE_URL}/api/gigs/offerings`);
  const offerings = await resp.json();
  expect(offerings.some((o) => o.payout_cadence === 'weekly')).toBeTruthy();
});
```

- [ ] **Step 3: Rebuild + run, verify pass**

```bash
podman compose build frontend && podman compose up -d --force-recreate frontend && sleep 3
cd e2e-tests && npx playwright test onboarding-missions.spec.js --reporter=list
```
Expected: PASS (all mission + cadence tests).

- [ ] **Step 4: astro check + commit**

```bash
cd frontend && npm run check && cd ..
git add frontend/src/pages/gigs.astro frontend/src e2e-tests/onboarding-missions.spec.js
git commit -m "feat(onboarding): first-gig mission + payout cadence in the gig form"
```

---

## Task 9: Full verification + branch wrap

**Files:** none (verification only)

- [ ] **Step 1: Backend full suite + lint**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q
cd backend && ruff check app && cd ..
```
Expected: all green, coverage ≥70%, zero ruff findings.

- [ ] **Step 2: Migration round-trip once more (clean)**

```bash
podman exec family_app_backend alembic downgrade -1 && podman exec family_app_backend alembic upgrade head && podman exec family_app_backend alembic heads
```
Expected: single head `family_gig_term` (chain: naive_to_timestamptz → gig_payout_cadence → family_gig_term).

- [ ] **Step 3: Frontend build + focused e2e**

```bash
cd frontend && npm run check && npm run build && cd ..
cd e2e-tests && npx playwright test jarvis.spec.js more-sheet.spec.js economy-copy.spec.js onboarding-missions.spec.js --reporter=list
```
Expected: all PASS.

- [ ] **Step 4: Manual smoke of the two missions** (drive the real app)

Log in as `mom@demo.com`, start "Crea tu primera tarea" from the checklist, confirm each coach-mark advances on the real action (open → template → assign → create), then the "ahora crea una gig" nudge and mission 2 including the cadence field. Confirm skipping (X) acks and the checklist deep-link still works.

- [ ] **Step 5: Update CLAUDE.md economy note + open PR**

Update the two-currency description in `CLAUDE.md` to model v2 (points unlock the domingo; gig payout_cadence). Then:

```bash
git add CLAUDE.md && git commit -m "docs: economy v2 in CLAUDE.md"
git push -u origin qa/wk29-jesus-feedback
gh pr create --title "WK29 QA: Jarvis/nav fixes + economy v2 + action-driven onboarding" --body "..."
```

---

## Self-Review

**Spec coverage:**
- §2 chore_gated → Task 1 ✓
- §2/§3.2 gig payout_cadence → Tasks 2–3 ✓
- §2/§3.6 per-family gig term (gig|chamba) → Task 3B ✓
- §3.3 copy rewrite (kills "nunca se vuelven dinero", fixes "Gestión es tu base", gig≠premio) → Task 4 ✓
- §3.4 action-driven missions (runner, real-DOM advance, cross-page resume, degrade-to-fallback) → Tasks 6–8 ✓
- §3.5 readability + GIF slots → Task 5 ✓
- §5 testing (TDD, migration round-trip, e2e) → every task + Task 9 ✓
- §6 out-of-scope respected (no auto-pay scheduler, rewards untouched, "250" derived, GIF assets deferred) ✓

**Placeholder scan:** Backend tasks carry full code. Frontend integration steps (Tasks 6–8) describe exact `data-tour` anchors, event signal names, and full runner code; the per-page wiring ("add data-tour to the FAB") is concrete because the anchor + signal contract is fully specified in Task 6's Interfaces. No "TBD"/"handle edge cases".

**Type consistency:** `advanceOn.signal` (string) used identically in `MissionStep` (Task 6), the dispatched CustomEvent `detail.signal` (Task 6 Step 3), and `onSignal` matching (Task 7). Signal names — `task-modal-open`, `task-template-selected`, `task-assignee-selected`, `task-created`, `gig-modal-open`, `gig-cadence-set`, `gig-created` — match between `buildMission` and the emit sites. `payout_cadence` value set `{immediate,weekly,biweekly,monthly}` identical across model (Task 2), schema Literal (Task 3), migration constraint (Task 2), and gig form select (Task 8). `runMission(mission, lang)` signature consistent between Task 7 definition and Task 7 Step 2 call sites.
