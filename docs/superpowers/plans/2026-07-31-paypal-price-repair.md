# PayPal Price Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore production subscription prices, wire the PayPal plan ids so checkout works, and make a future silent re-zeroing impossible to miss.

**Architecture:** One canonical price table in Python (`app/core/plan_pricing.py`) replaces three drifting copies. An idempotent migration re-asserts those prices in the DB. A single `audit_plan_rows()` helper detects misconfigured rows and feeds three consumers: a startup log line, an operator-console panel, and the deploy smoke check. Provisioning at PayPal stays an operator script run, reviewed dry-run-first.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · pytest · Astro 5 · rootless Podman

## Global Constraints

- Canonical prices, in minor units (centavos / cents): `plus USD 500 / 5000`, `pro USD 1500 / 15000`, `plus MXN 9900 / 99000`, `pro MXN 19900 / 199000`.
- `ruff check app` is zero-tolerance and CI-enforced. Config: `backend/ruff.toml`.
- Migrations are single-head. CI runs upgrade → downgrade -1 → upgrade; both directions must work.
- `backend/tests/conftest.py` builds the schema with `Base.metadata.create_all`, **not** alembic. Tests therefore start with an EMPTY `subscription_plans` table — no test may assume seeded plan rows exist. Create the rows you need in the test.
- Never `sudo podman` on `10.1.0.91`. Always `ssh jc@10.1.0.91 'podman ...'`.
- Run backend tests inside the container: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v`. When podman is down locally, `backend/.venv/bin/pytest --no-cov` against Homebrew PG on 5435 works.
- Prices are **display and provisioning data only**. Nothing in this plan may write `paypal_plan_id_*` or `is_active` from a migration — those belong to the operator provisioning run (Task 10).

---

## File Structure

**Create:**
- `backend/app/core/plan_pricing.py` — canonical price table + `audit_plan_rows()` misconfiguration detector. The single source of truth.
- `backend/migrations/versions/2026_07_31_restore_plan_prices.py` — idempotent absolute price restore, with a frozen copy of the table.
- `backend/tests/test_plan_pricing_invariants.py` — canonical-drift tests + `audit_plan_rows()` behavior tests.

**Modify:**
- `backend/scripts/setup_paypal_plans.py` — delete `PLAN_PRICES`, derive from `CANONICAL_PRICES`.
- `backend/app/services/admin/admin_read_service.py` — add `billing_config_health()`.
- `backend/app/api/routes/admin/overview.py` — expose `GET /api/admin/billing-config`.
- `backend/app/main.py` — startup audit log line.
- `frontend/src/pages/parent/settings/subscription.astro` — delete `fallbackCents`, render `—` when a price row is missing.
- `frontend/src/pages/admin/index.astro` — billing-config panel.
- `scripts/deploy-onprem.sh` — smoke check asserting paid plans are priced and checkout-ready.
- `CLAUDE.md` — document the single-source rule.

---

### Task 1: Canonical price table

**Files:**
- Create: `backend/app/core/plan_pricing.py`
- Test: `backend/tests/test_plan_pricing_invariants.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CANONICAL_PRICES: dict[tuple[str, str], tuple[int, int]]` keyed `(tier, currency)` → `(monthly_minor, annual_minor)`; `price_minor(tier, cycle, currency) -> int` where `cycle` is `"monthly"` or `"annual"`; `price_decimal_str(tier, cycle, currency) -> str` returning a PayPal-style `"5.00"`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_plan_pricing_invariants.py`:

```python
"""Invariants for subscription plan pricing.

Prod shipped with every paid plan priced at 0 for ~2 weeks (2026-07-16 →
2026-07-31) because the price lived in three hand-synced copies and nothing
compared them. These tests pin the single source of truth.

NOTE: conftest builds the schema with Base.metadata.create_all, so
subscription_plans starts EMPTY here. Nothing in this file may assume the
alembic seed ran — rows under test are created explicitly.
"""
import pytest

from app.core.plan_pricing import (
    CANONICAL_PRICES,
    price_decimal_str,
    price_minor,
)


def test_canonical_table_covers_every_paid_tier_and_currency():
    assert set(CANONICAL_PRICES) == {
        ("plus", "USD"),
        ("pro", "USD"),
        ("plus", "MXN"),
        ("pro", "MXN"),
    }


def test_canonical_prices_are_the_launch_values():
    assert CANONICAL_PRICES[("plus", "USD")] == (500, 5_000)
    assert CANONICAL_PRICES[("pro", "USD")] == (1_500, 15_000)
    assert CANONICAL_PRICES[("plus", "MXN")] == (9_900, 99_000)
    assert CANONICAL_PRICES[("pro", "MXN")] == (19_900, 199_000)


def test_annual_is_ten_months_of_monthly():
    """Annual is advertised as '2 months free'. If someone changes one side
    of a pair and not the other, the marketing claim silently becomes false."""
    for (tier, currency), (monthly, annual) in CANONICAL_PRICES.items():
        assert annual == monthly * 10, f"{tier} {currency} breaks 2-months-free"


def test_price_minor_selects_the_cycle():
    assert price_minor("pro", "monthly", "MXN") == 19_900
    assert price_minor("pro", "annual", "MXN") == 199_000


def test_price_minor_rejects_unknown_inputs():
    with pytest.raises(KeyError):
        price_minor("enterprise", "monthly", "USD")
    with pytest.raises(ValueError):
        price_minor("pro", "weekly", "USD")


def test_price_decimal_str_is_paypal_shaped():
    assert price_decimal_str("plus", "monthly", "USD") == "5.00"
    assert price_decimal_str("pro", "annual", "MXN") == "1990.00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.plan_pricing'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/core/plan_pricing.py`:

```python
"""Canonical subscription plan prices — the single source of truth.

Prices are stored and compared in the currency's MINOR unit (US cents,
MXN centavos), matching subscription_plans.price_*_cents.

History: these values used to live in three hand-synced copies (the
provisioning script, two alembic migrations, and a frontend fallback
constant). On 2026-07-16 prod's rows were overwritten with 0 out of band and
nothing noticed for two weeks — the pricing page advertised "$0/mes" and
checkout 501'd. Every consumer now derives from this table:

- backend/scripts/setup_paypal_plans.py  (what PayPal is told to charge)
- backend/migrations/versions/2026_07_31_restore_plan_prices.py
  (a FROZEN copy — migrations must not import app code, which moves under
  them; test_plan_pricing_invariants asserts the copy has not drifted)
- app/main.py startup audit, the operator console panel, and the deploy
  smoke check — all via audit_plan_rows() below.

The frontend deliberately has NO copy: a missing plan row renders "—" and
disables checkout rather than printing a price the backend never confirmed.

NOTE: audit_plan_rows() and its sqlalchemy imports are added in Task 3, not
here — an unused import would fail ruff.
"""
# (tier, currency) -> (monthly_minor_units, annual_minor_units).
# Annual is exactly 10x monthly — "2 months free" is a marketing promise the
# invariant test enforces.
CANONICAL_PRICES: dict[tuple[str, str], tuple[int, int]] = {
    ("plus", "USD"): (500, 5_000),
    ("pro", "USD"): (1_500, 15_000),
    ("plus", "MXN"): (9_900, 99_000),
    ("pro", "MXN"): (19_900, 199_000),
}

_CYCLE_INDEX = {"monthly": 0, "annual": 1}


def price_minor(tier: str, cycle: str, currency: str) -> int:
    """Canonical price in minor units. Raises on an unknown tier/currency
    (KeyError) or an unknown billing cycle (ValueError)."""
    if cycle not in _CYCLE_INDEX:
        raise ValueError(f"Unknown billing cycle: {cycle!r}")
    return CANONICAL_PRICES[(tier, currency)][_CYCLE_INDEX[cycle]]


def price_decimal_str(tier: str, cycle: str, currency: str) -> str:
    """Canonical price as the decimal string PayPal's Billing API expects."""
    return f"{price_minor(tier, cycle, currency) / 100:.2f}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint**

Run: `cd backend && ruff check app`
Expected: no findings. Do not import sqlalchemy or typing here — audit_plan_rows() and its imports land together in Task 3, and an unused import fails ruff.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/plan_pricing.py backend/tests/test_plan_pricing_invariants.py
git commit -m "feat(billing): canonical plan price table

Single source of truth for the four paid (tier, currency) prices. Three
hand-synced copies is how prod ended up advertising \$0/mes for two weeks."
```

---

### Task 2: Provisioning script derives from the canonical table

**Files:**
- Modify: `backend/scripts/setup_paypal_plans.py` (delete `PLAN_PRICES`, ~lines 108-135; update `build_plan_definitions` and `print_dry_run`)
- Test: `backend/tests/test_plan_pricing_invariants.py`

**Interfaces:**
- Consumes: `price_decimal_str` from Task 1.
- Produces: `build_plan_definitions(product_id, currencies=("USD","MXN")) -> list[dict]` — unchanged signature, prices now derived.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_plan_pricing_invariants.py`:

```python
def test_provisioning_script_prices_match_the_canonical_table():
    """setup_paypal_plans is what PayPal actually charges. If it drifts from
    the DB's display price, customers see one number and pay another."""
    from scripts.setup_paypal_plans import build_plan_definitions, plan_meta

    defs = build_plan_definitions("PROD-TEST")
    assert len(defs) == 8  # plus/pro x monthly/annual x USD/MXN

    seen = set()
    for plan_def in defs:
        tier, cycle, currency = plan_meta(plan_def)
        seen.add((tier, cycle, currency))
        regular = [
            c for c in plan_def["billing_cycles"] if c["tenure_type"] == "REGULAR"
        ][0]
        charged = regular["pricing_scheme"]["fixed_price"]
        assert charged["currency_code"] == currency
        assert charged["value"] == price_decimal_str(tier, cycle, currency)

    assert seen == {
        (tier, cycle, currency)
        for (tier, currency) in CANONICAL_PRICES
        for cycle in ("monthly", "annual")
    }


def test_provisioning_script_has_no_private_price_copy():
    """The whole point of Task 1 — the script must not carry its own table."""
    import scripts.setup_paypal_plans as mod

    assert not hasattr(mod, "PLAN_PRICES")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -k provisioning -v`
Expected: FAIL — `test_provisioning_script_has_no_private_price_copy` fails on the still-present `PLAN_PRICES`.

- [ ] **Step 3: Write minimal implementation**

In `backend/scripts/setup_paypal_plans.py`, delete the whole `PLAN_PRICES` block and its "THREE copies" comment, replacing it with:

```python
# ---------------------------------------------------------------------------
# Prices come from the canonical table — do NOT add a copy here.
# ---------------------------------------------------------------------------
from app.core.plan_pricing import CANONICAL_PRICES, price_decimal_str  # noqa: E402
```

In `build_plan_definitions`, replace `prices = PLAN_PRICES[currency]` / `prices[(tier, cycle)]` with `price_decimal_str(tier, cycle, currency)`:

```python
def build_plan_definitions(
    product_id: str, currencies: tuple[str, ...] = ("USD", "MXN")
) -> list[dict[str, Any]]:
    """Define the Plans (Plus/Pro × monthly/annual × currency) with trial."""
    cycles = {
        "monthly": {"interval_unit": "MONTH", "interval_count": 1},
        "annual": {"interval_unit": "YEAR", "interval_count": 1},
    }
    out = []
    for currency in currencies:
        for tier in ("plus", "pro"):
            for cycle in ("monthly", "annual"):
                out.append(
                    {
                        "product_id": product_id,
                        "name": _plan_name(tier, cycle, currency),
                        "description": (
                            f"Family Task Manager — {tier} ({cycle}, {currency})"
                        ),
                        "status": "ACTIVE",
                        "billing_cycles": [
                            {
                                "tenure_type": "TRIAL",
                                "sequence": 1,
                                "total_cycles": 1,
                                "frequency": {
                                    "interval_unit": "DAY",
                                    "interval_count": TRIAL_DAYS,
                                },
                                "pricing_scheme": {
                                    "fixed_price": {
                                        "value": "0",
                                        "currency_code": currency,
                                    }
                                },
                            },
                            {
                                "tenure_type": "REGULAR",
                                "sequence": 2,
                                "total_cycles": 0,
                                "frequency": cycles[cycle],
                                "pricing_scheme": {
                                    "fixed_price": {
                                        "value": price_decimal_str(
                                            tier, cycle, currency
                                        ),
                                        "currency_code": currency,
                                    }
                                },
                            },
                        ],
                        "payment_preferences": {
                            "auto_bill_outstanding": True,
                            "setup_fee": {"value": "0", "currency_code": currency},
                            "setup_fee_failure_action": "CONTINUE",
                            "payment_failure_threshold": 3,
                        },
                    }
                )
    return out
```

In `print_dry_run`, replace `price = PLAN_PRICES[currency][(tier, cycle)]` with:

```python
        price = price_decimal_str(tier, cycle, currency)
```

Update the module docstring's price lines to point at the canonical table instead of restating numbers:

```
MXN plans are the Mexico-first defaults. Prices come from
app/core/plan_pricing.py (CANONICAL_PRICES) — the single source of truth.
Do NOT add a price constant to this file.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Verify the dry run still works end to end**

Run: `podman exec -e PYTHONPATH=/app family_app_backend python -m scripts.setup_paypal_plans --dry-run`
Expected: 8 plans listed with `USD 5.00`, `USD 50.00`, `USD 15.00`, `USD 150.00`, `MXN 99.00`, `MXN 990.00`, `MXN 199.00`, `MXN 1990.00`. No credentials needed.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/setup_paypal_plans.py backend/tests/test_plan_pricing_invariants.py
git commit -m "refactor(billing): provisioning script reads canonical prices

Second of the three price copies removed. A test now fails if anyone
reintroduces PLAN_PRICES."
```

---

### Task 3: `audit_plan_rows()` — the misconfiguration detector

**Files:**
- Modify: `backend/app/core/plan_pricing.py`
- Test: `backend/tests/test_plan_pricing_invariants.py`

**Interfaces:**
- Consumes: `CANONICAL_PRICES` from Task 1.
- Produces: `async def audit_plan_rows(db: AsyncSession) -> list[dict[str, Any]]` — one dict per misconfigured ACTIVE paid row: `{"name", "currency", "problems": [str, ...]}`. Empty list means billing config is healthy. Consumed by Tasks 5, 6 and 8.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_plan_pricing_invariants.py`:

```python
from app.core.plan_pricing import audit_plan_rows
from app.models.subscription import SubscriptionPlan


def _plan(name, currency, monthly, annual, *, pp_m="P-M", pp_a="P-A", active=True):
    return SubscriptionPlan(
        name=name,
        display_name=name.capitalize(),
        display_name_es=name.capitalize(),
        currency=currency,
        price_monthly_cents=monthly,
        price_annual_cents=annual,
        paypal_plan_id_monthly=pp_m,
        paypal_plan_id_annual=pp_a,
        limits={},
        is_active=active,
        sort_order=10,
    )


@pytest.mark.asyncio
async def test_audit_is_clean_when_every_row_is_correct(db_session):
    db_session.add(_plan("plus", "USD", 500, 5_000))
    db_session.add(_plan("pro", "MXN", 19_900, 199_000))
    await db_session.commit()

    assert await audit_plan_rows(db_session) == []


@pytest.mark.asyncio
async def test_audit_flags_a_zero_price(db_session):
    """The exact production failure: an active paid row priced at 0."""
    db_session.add(_plan("plus", "USD", 0, 0))
    await db_session.commit()

    findings = await audit_plan_rows(db_session)
    assert len(findings) == 1
    assert findings[0]["name"] == "plus"
    assert findings[0]["currency"] == "USD"
    assert any("zero" in p for p in findings[0]["problems"])


@pytest.mark.asyncio
async def test_audit_flags_a_price_that_drifted_from_canonical(db_session):
    db_session.add(_plan("pro", "USD", 1_200, 12_000))
    await db_session.commit()

    findings = await audit_plan_rows(db_session)
    assert len(findings) == 1
    assert any("canonical" in p for p in findings[0]["problems"])


@pytest.mark.asyncio
async def test_audit_flags_a_missing_paypal_plan_id(db_session):
    """The second half of the prod outage: priced correctly, unwired, active
    — the pricing page shows a price nobody can actually check out."""
    db_session.add(_plan("plus", "MXN", 9_900, 99_000, pp_m=None))
    await db_session.commit()

    findings = await audit_plan_rows(db_session)
    assert len(findings) == 1
    assert any("paypal_plan_id_monthly" in p for p in findings[0]["problems"])


@pytest.mark.asyncio
async def test_audit_ignores_the_free_tier(db_session):
    """free is priced 0 and has no PayPal plan by design."""
    db_session.add(
        _plan("free", "USD", 0, 0, pp_m=None, pp_a=None)
    )
    await db_session.commit()

    assert await audit_plan_rows(db_session) == []


@pytest.mark.asyncio
async def test_audit_ignores_inactive_rows(db_session):
    """An inactive row is never listed or checked out — it is allowed to sit
    unwired, which is exactly how mxn_plan_currency_w6 seeds MXN."""
    db_session.add(_plan("pro", "MXN", 0, 0, pp_m=None, pp_a=None, active=False))
    await db_session.commit()

    assert await audit_plan_rows(db_session) == []


@pytest.mark.asyncio
async def test_audit_flags_an_unknown_active_paid_tier(db_session):
    """A paid tier with no canonical price cannot be validated at all — say
    so rather than silently passing it."""
    db_session.add(_plan("enterprise", "USD", 9_900, 99_000))
    await db_session.commit()

    findings = await audit_plan_rows(db_session)
    assert len(findings) == 1
    assert any("no canonical price" in p for p in findings[0]["problems"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -k audit -v`
Expected: FAIL — `ImportError: cannot import name 'audit_plan_rows'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/core/plan_pricing.py`:

```python
async def audit_plan_rows(db: AsyncSession) -> list[dict[str, Any]]:
    """Find ACTIVE paid plan rows that cannot correctly sell anything.

    Returns one entry per broken row, `[]` when healthy. Three consumers:
    the startup log, GET /api/admin/billing-config, and the deploy smoke
    check — CI cannot see production data, so this function IS the
    production-side regression guard.

    Scope decisions:
    - `free` is skipped: priced 0 with no PayPal plan by design.
    - inactive rows are skipped: they are never listed nor checkout-able, and
      inactive-and-unwired is the deliberate seeded state for a currency
      awaiting provisioning.
    """
    from app.models.subscription import SubscriptionPlan

    rows = (
        await db.execute(
            select(SubscriptionPlan).where(
                SubscriptionPlan.is_active == True,  # noqa: E712
                SubscriptionPlan.name != "free",
            )
        )
    ).scalars().all()

    findings: list[dict[str, Any]] = []
    for row in rows:
        problems: list[str] = []

        if row.price_monthly_cents == 0 or row.price_annual_cents == 0:
            problems.append(
                "zero price on an active paid plan "
                f"(monthly={row.price_monthly_cents}, "
                f"annual={row.price_annual_cents})"
            )

        expected = CANONICAL_PRICES.get((row.name, row.currency))
        if expected is None:
            problems.append(
                f"no canonical price for tier {row.name!r} in {row.currency}"
            )
        elif (row.price_monthly_cents, row.price_annual_cents) != expected:
            problems.append(
                "price differs from canonical "
                f"(db={row.price_monthly_cents}/{row.price_annual_cents}, "
                f"canonical={expected[0]}/{expected[1]})"
            )

        if not row.paypal_plan_id_monthly:
            problems.append("paypal_plan_id_monthly is not wired — checkout 501s")
        if not row.paypal_plan_id_annual:
            problems.append("paypal_plan_id_annual is not wired — checkout 501s")

        if problems:
            findings.append(
                {
                    "name": row.name,
                    "currency": row.currency,
                    "problems": problems,
                }
            )

    return sorted(findings, key=lambda f: (f["name"], f["currency"]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Lint**

Run: `cd backend && ruff check app`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/plan_pricing.py backend/tests/test_plan_pricing_invariants.py
git commit -m "feat(billing): audit_plan_rows misconfiguration detector

CI builds the schema with create_all and never sees prod data, so this
function is the guard that actually runs where the outage happened."
```

---

### Task 4: Repair migration

**Files:**
- Create: `backend/migrations/versions/2026_07_31_restore_plan_prices.py`
- Test: `backend/tests/test_plan_pricing_invariants.py`

**Interfaces:**
- Consumes: `CANONICAL_PRICES` from Task 1 (as a frozen literal copy, not an import).
- Produces: alembic revision `restore_plan_prices`.

- [ ] **Step 1: Find the current head**

Run: `podman exec family_app_backend alembic heads`
Expected: a single revision id. Use it as `down_revision` in Step 3. As of writing it is `user_completed_tours`; if `alembic heads` disagrees, the command wins — do not hardcode from this plan.

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_plan_pricing_invariants.py`:

```python
def test_migration_frozen_prices_have_not_drifted():
    """The migration carries its own literal copy on purpose — migrations
    must not import app code, which changes underneath them. That freedom
    costs a drift risk, and this is the test that pays for it."""
    import importlib

    mig = importlib.import_module(
        "migrations.versions.2026_07_31_restore_plan_prices"
    )
    assert mig.FROZEN_PRICES == CANONICAL_PRICES
```

If the dotted module name is not importable because the filename starts with a digit, use the loader form instead — it is equivalent and has no import-system constraints:

```python
def test_migration_frozen_prices_have_not_drifted():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "2026_07_31_restore_plan_prices.py"
    )
    spec = importlib.util.spec_from_file_location("_restore_plan_prices", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.FROZEN_PRICES == CANONICAL_PRICES
```

Use the second form. The first is shown only so the reader knows why it was rejected.

- [ ] **Step 3: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -k frozen -v`
Expected: FAIL — `FileNotFoundError` / `spec_from_file_location` returns None for the missing migration.

- [ ] **Step 4: Write the migration**

Create `backend/migrations/versions/2026_07_31_restore_plan_prices.py`:

```python
"""Restore subscription plan prices after an out-of-band zeroing.

On 2026-07-31 production held price_monthly_cents = price_annual_cents = 0
for all four paid rows (plus/pro x USD/MXN). This was NOT a missing
migration: prod's head was downstream of both usd_price_alignment and
mxn_plan_currency_w6, all four rows shared updated_at
2026-07-16 17:30:11.67115+00 (one transaction, consistent with that upgrade
run), and no migration in the chain ever writes a 0. The rows were
overwritten out of band afterwards; subscription_plans has no audit trail,
so the actor is not recoverable.

The UPDATE is ABSOLUTE and idempotent — re-running always converges on the
canonical values, whatever the row currently holds.

FROZEN_PRICES is a deliberate literal copy of app.core.plan_pricing's
CANONICAL_PRICES. Migrations must not import app code (it evolves under
already-applied revisions), so the copy is frozen here and
tests/test_plan_pricing_invariants.py asserts it has not drifted.

Deliberately does NOT touch is_active or paypal_plan_id_* — those are
provisioning state owned by scripts/setup_paypal_plans.py, and a migration
fighting the operator over them is how the MXN rows ended up active and
unwired.

Revision ID: restore_plan_prices
Revises: user_completed_tours
Create Date: 2026-07-31
"""
from alembic import op

revision = "restore_plan_prices"
down_revision = "user_completed_tours"
branch_labels = None
depends_on = None


# FROZEN copy of app.core.plan_pricing.CANONICAL_PRICES.
# (tier, currency) -> (monthly_minor_units, annual_minor_units)
FROZEN_PRICES = {
    ("plus", "USD"): (500, 5_000),
    ("pro", "USD"): (1_500, 15_000),
    ("plus", "MXN"): (9_900, 99_000),
    ("pro", "MXN"): (19_900, 199_000),
}


def upgrade() -> None:
    conn = op.get_bind()
    from sqlalchemy import text

    stmt = text(
        "UPDATE subscription_plans "
        "SET price_monthly_cents = :monthly, "
        "    price_annual_cents = :annual, "
        "    updated_at = now() "
        "WHERE name = :name AND currency = :currency"
    )
    for (name, currency), (monthly, annual) in FROZEN_PRICES.items():
        conn.execute(
            stmt,
            {
                "name": name,
                "currency": currency,
                "monthly": monthly,
                "annual": annual,
            },
        )


def downgrade() -> None:
    """No-op, deliberately.

    Prices are display data with exactly one correct value; there is no
    earlier state worth restoring, and reverting to 0 would recreate the
    outage this revision fixes. CI runs upgrade -> downgrade -1 -> upgrade,
    which is safe: the following upgrade re-asserts the same values.
    """
```

- [ ] **Step 5: Run the test and the migration**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -k frozen -v`
Expected: PASS

Run: `podman exec family_app_backend alembic upgrade head && podman exec family_app_backend alembic downgrade -1 && podman exec family_app_backend alembic upgrade head`
Expected: all three succeed; `alembic heads` shows a single head `restore_plan_prices`.

- [ ] **Step 6: Verify against the local dev DB**

Run:
```bash
podman exec family_app_db psql -U familyapp -d familyapp -c \
  "SELECT name,currency,price_monthly_cents,price_annual_cents FROM subscription_plans ORDER BY sort_order,currency;"
```
Expected: plus USD 500/5000, pro USD 1500/15000, plus MXN 9900/99000, pro MXN 19900/199000.

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/versions/2026_07_31_restore_plan_prices.py backend/tests/test_plan_pricing_invariants.py
git commit -m "fix(billing): restore paid plan prices

Absolute idempotent UPDATE from a frozen canonical table. Does not touch
is_active or the paypal ids — that is the operator's provisioning run."
```

---

### Task 5: Startup warning

**Files:**
- Modify: `backend/app/main.py` (inside `lifespan`, after the DB-URL log at ~line 88)
- Test: `backend/tests/test_plan_pricing_invariants.py`

**Interfaces:**
- Consumes: `audit_plan_rows` from Task 3.
- Produces: `async def _billing_audit_message(session) -> str | None` in `app/main.py`, plus a best-effort call to it inside `lifespan`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_plan_pricing_invariants.py`:

```python
@pytest.mark.asyncio
async def test_startup_audit_logs_an_error_for_broken_billing(db_session, caplog):
    """A silent misconfiguration is what let this run for two weeks. At
    minimum it must be greppable in podman logs."""
    import logging

    from app.main import _billing_audit_message

    db_session.add(_plan("plus", "USD", 0, 0))
    await db_session.commit()

    with caplog.at_level(logging.ERROR):
        message = await _billing_audit_message(db_session)

    assert message is not None
    assert "plus" in message and "USD" in message


@pytest.mark.asyncio
async def test_startup_audit_is_silent_when_healthy(db_session):
    from app.main import _billing_audit_message

    db_session.add(_plan("plus", "USD", 500, 5_000))
    await db_session.commit()

    assert await _billing_audit_message(db_session) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -k startup_audit -v`
Expected: FAIL — `ImportError: cannot import name '_billing_audit_message'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/main.py`, above `lifespan`:

```python
async def _billing_audit_message(session) -> str | None:
    """Human-readable summary of billing misconfiguration, or None if healthy.

    Split out from the lifespan hook so it is testable without booting the
    app. See app/core/plan_pricing.audit_plan_rows.
    """
    from app.core.plan_pricing import audit_plan_rows

    findings = await audit_plan_rows(session)
    if not findings:
        return None
    parts = [
        f"{f['name']}/{f['currency']}: {'; '.join(f['problems'])}"
        for f in findings
    ]
    return "billing misconfigured — " + " | ".join(parts)
```

Inside `lifespan`, right after the `Database URL:` log line:

```python
    # Billing configuration audit. CI cannot see production data, so this is
    # one of the three places a zeroed price or an unwired PayPal plan
    # becomes visible (the others: GET /api/admin/billing-config and the
    # deploy smoke check). Best-effort — never block startup on it.
    try:
        async with AsyncSessionLocal() as _billing_session:
            _billing_problem = await _billing_audit_message(_billing_session)
        if _billing_problem:
            logger.error(_billing_problem)
    except Exception:
        logger.exception("Billing configuration audit failed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_plan_pricing_invariants.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Verify it fires for real**

Run: `podman compose restart backend && podman logs family_app_backend 2>&1 | grep -i "billing misconfigured" || echo "healthy (expected after Task 4)"`
Expected: `healthy` locally, since Task 4 fixed the local prices. To prove the log path works, temporarily zero a row, restart, observe the line, then re-run `alembic upgrade head` — do NOT commit the zeroing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_plan_pricing_invariants.py
git commit -m "feat(billing): log a startup error when plan config is broken"
```

---

### Task 6: Operator console billing-config panel

**Files:**
- Modify: `backend/app/services/admin/admin_read_service.py` (add `billing_config_health`)
- Modify: `backend/app/api/routes/admin/overview.py` (add the route)
- Modify: `frontend/src/pages/admin/index.astro` (render the panel)
- Test: `backend/tests/test_admin_reads.py`

**Interfaces:**
- Consumes: `audit_plan_rows` from Task 3.
- Produces: `AdminReadService.billing_config_health(db) -> dict` with keys `{"healthy": bool, "findings": list[dict]}`; route `GET /api/admin/billing-config`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_admin_reads.py`:

```python
@pytest.mark.asyncio
async def test_billing_config_health_reports_broken_rows(
    client, superadmin_headers, db_session
):
    """The panel that would have caught the 2026-07-16 zeroing. CI's DB is
    empty, so the rows under test are created here."""
    from app.models.subscription import SubscriptionPlan

    db_session.add(
        SubscriptionPlan(
            name="pro",
            display_name="Pro",
            display_name_es="Pro",
            currency="MXN",
            price_monthly_cents=0,
            price_annual_cents=0,
            paypal_plan_id_monthly=None,
            paypal_plan_id_annual=None,
            limits={},
            is_active=True,
            sort_order=20,
        )
    )
    await db_session.commit()

    resp = await client.get("/api/admin/billing-config", headers=superadmin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["healthy"] is False
    assert body["findings"][0]["name"] == "pro"
    assert body["findings"][0]["currency"] == "MXN"


@pytest.mark.asyncio
async def test_billing_config_health_is_healthy_when_correct(
    client, superadmin_headers, db_session
):
    from app.models.subscription import SubscriptionPlan

    db_session.add(
        SubscriptionPlan(
            name="plus",
            display_name="Plus",
            display_name_es="Plus",
            currency="USD",
            price_monthly_cents=500,
            price_annual_cents=5_000,
            paypal_plan_id_monthly="P-PLUS-M",
            paypal_plan_id_annual="P-PLUS-A",
            limits={},
            is_active=True,
            sort_order=10,
        )
    )
    await db_session.commit()

    resp = await client.get("/api/admin/billing-config", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"healthy": True, "findings": []}


@pytest.mark.asyncio
async def test_billing_config_health_is_superadmin_only(client, auth_headers):
    resp = await client.get("/api/admin/billing-config", headers=auth_headers)
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -k billing_config -v`
Expected: FAIL — 404 on `/api/admin/billing-config` for the superadmin too (route does not exist).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/admin/admin_read_service.py`, add to `AdminReadService`:

```python
    @staticmethod
    async def billing_config_health(db: AsyncSession) -> dict:
        """Can the app actually sell a plan right now?

        Wraps app.core.plan_pricing.audit_plan_rows. This is the only one of
        its three consumers that runs against PRODUCTION data on demand —
        CI's schema is built with create_all and holds no plan rows, and the
        startup log is only seen if somebody greps for it.
        """
        from app.core.plan_pricing import audit_plan_rows

        findings = await audit_plan_rows(db)
        return {"healthy": not findings, "findings": findings}
```

In `backend/app/api/routes/admin/overview.py`, after the `/billing-review` route:

```python
@router.get("/billing-config")
async def billing_config(
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Plan rows that cannot correctly sell anything (zero price, drifted
    price, or an unwired PayPal plan id)."""
    return await AdminReadService.billing_config_health(db)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_admin_reads.py -k billing_config -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the frontend panel**

In `frontend/src/pages/admin/index.astro`, fetch alongside the existing overview call and render above the fold. Follow the file's existing `apiFetch` + card conventions:

```astro
const { data: billing } = await apiFetch<any>("/api/admin/billing-config", { token });
```

```astro
{billing && !billing.healthy && (
  <section class="rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950">
    <h2 class="font-semibold text-red-800 dark:text-red-200">
      Billing misconfigured — customers cannot subscribe
    </h2>
    <ul class="mt-2 space-y-1 text-sm text-red-700 dark:text-red-300">
      {billing.findings.map((f: any) => (
        <li>
          <strong>{f.name} / {f.currency}</strong>: {f.problems.join("; ")}
        </li>
      ))}
    </ul>
    <p class="mt-2 text-xs text-red-600 dark:text-red-400">
      Fix: <code>alembic upgrade head</code> restores prices;
      <code>python -m scripts.setup_paypal_plans</code> wires the PayPal ids.
    </p>
  </section>
)}
```

- [ ] **Step 6: Verify the frontend builds**

Run: `cd frontend && npm run check && npm run build`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/admin/admin_read_service.py backend/app/api/routes/admin/overview.py backend/tests/test_admin_reads.py frontend/src/pages/admin/index.astro
git commit -m "feat(admin): billing-config health panel

Red banner on the operator console when a paid plan row is priced 0,
drifted from canonical, or unwired at PayPal."
```

---

### Task 7: Frontend — stop inventing prices

**Files:**
- Modify: `frontend/src/pages/parent/settings/subscription.astro:90-119` (delete `fallbackCents`, rewrite `price()`)

**Interfaces:**
- Consumes: `PlanResponse.price_*_cents` from the API.
- Produces: `price(plan, cycle) -> string | null` — `null` when the row is missing.

- [ ] **Step 1: Delete the third price copy**

Replace lines 90-119 (the `fallbackCents` block, `formatPrice`, and `price`) with:

```astro
// No price constants live here. A missing plan row renders "—" and disables
// checkout rather than printing a price the backend never confirmed — which
// is exactly how this page advertised "$0/mes" for two weeks in July 2026
// (the rows existed with a real 0, so the old `?? fallbackCents[...]` never
// fired). Canonical prices: backend/app/core/plan_pricing.py.

// 'MX$99' / 'US$5' style — Intl.NumberFormat es-MX renders both MXN and USD
// as a bare '$', so prefix the country code to disambiguate the two pesos.
function formatPrice(cents: number, currency: string): string {
    const amount = cents / 100;
    let s = new Intl.NumberFormat(lang === "es" ? "es-MX" : "en-US", {
        style: "currency",
        currency,
        currencyDisplay: "narrowSymbol",
        minimumFractionDigits: 0,
        maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    }).format(amount);
    if (currency === "MXN" && !s.includes("MX")) s = `MX${s}`;
    if (currency === "USD" && !s.includes("US")) s = `US${s}`;
    return s;
}

// Returns null when the tier has no row in the selected currency, or when
// the row is priced 0 (a paid tier at 0 is a backend misconfiguration, not
// a free plan — see GET /api/admin/billing-config).
const price = (plan: any, cycle: "monthly" | "annual"): string | null => {
    const cents = plan?.[`price_${cycle}_cents`];
    if (typeof cents !== "number" || cents <= 0) return null;
    return formatPrice(cents, plan?.currency ?? selectedCurrency);
};
```

- [ ] **Step 2: Update every call site**

Find each `price(plusPlan, "monthly", "plus")` / `price(proPlan, ...)` call in the template and drop the now-unused third argument, rendering the null case:

```astro
{price(plusPlan, "monthly") ?? "—"}
```

Run: `rg -n 'price\(' frontend/src/pages/parent/settings/subscription.astro`
Expected: every call has exactly two arguments and is wrapped in `?? "—"`.

- [ ] **Step 3: Extend the upgrade guard**

`canCheckout` currently checks currency match + `checkout_ready_monthly`. Add the price condition so a zero-priced row can never be checked out:

```astro
const canCheckout = (plan: any) =>
    Boolean(
        plan &&
        rowCurrency(plan) === selectedCurrency &&
        plan.checkout_ready_monthly !== false &&
        // A paid tier priced 0 is misconfiguration; selling it would create
        // a PayPal subscription whose price does not match what we showed.
        (plan.price_monthly_cents ?? 0) > 0,
    );
```

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run check && npm run build`
Expected: no errors, no remaining reference to `fallbackCents`.

Run: `rg -n "fallbackCents" frontend/ || echo "gone"`
Expected: `gone`

- [ ] **Step 5: Manual check**

Open `http://localhost:3003/parent/settings/subscription` as a parent.
Expected: MX$99 / MX$199 (or US$5 / US$15 on the USD toggle) with enabled upgrade buttons, given Task 4 ran locally.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/parent/settings/subscription.astro
git commit -m "fix(billing): never render a price the backend did not confirm

Third and last price copy removed. A missing or zero-priced row now shows
'—' and disables upgrade instead of advertising \$0/mes."
```

---

### Task 8: Deploy smoke check

**Files:**
- Modify: `scripts/deploy-onprem.sh` (the post-`up` smoke section)

**Interfaces:**
- Consumes: `GET /api/subscriptions/plans` (public shape: `price_monthly_cents`, `checkout_ready_monthly`).
- Produces: a non-zero deploy exit when paid plans cannot sell.

- [ ] **Step 1: Read the existing smoke section**

Run: `rg -n "smoke|curl|health" scripts/deploy-onprem.sh | head -30`

Note the existing failure convention (the 2026-07-27 audit found the smoke check never actually failed the deploy — match whatever the *fixed* convention now is, and if the check still cannot fail, make this one fail loudly and say so in the commit message).

- [ ] **Step 2: Add the check**

After the existing public-endpoint smoke checks:

```bash
# Billing configuration smoke check. CI builds its schema with create_all and
# never sees plan rows, so this is the only automated gate that inspects real
# production pricing. A paid tier priced 0 or missing its PayPal plan id means
# nobody can subscribe — that shipped unnoticed for two weeks in July 2026.
echo "==> Smoke: billing configuration"
BILLING_JSON="$(curl -fsS "https://api-family.agent-ia.mx/api/subscriptions/plans")" || {
    echo "FAIL: could not fetch /api/subscriptions/plans" >&2
    exit 1
}
BROKEN="$(printf '%s' "$BILLING_JSON" | python3 -c '
import json, sys
plans = json.load(sys.stdin)
bad = [
    f"{p[\"name\"]}/{p.get(\"currency\", \"USD\")}"
    for p in plans
    if p["name"] != "free"
    and (
        p.get("price_monthly_cents", 0) <= 0
        or not p.get("checkout_ready_monthly", False)
    )
]
print(",".join(bad))
')"
if [ -n "$BROKEN" ]; then
    echo "FAIL: paid plans cannot be sold: $BROKEN" >&2
    echo "      alembic upgrade head restores prices;" >&2
    echo "      python -m scripts.setup_paypal_plans wires the PayPal ids." >&2
    exit 1
fi
echo "    billing OK"
```

- [ ] **Step 3: Verify the check can actually fail**

Run: `DEPLOY_DRY_RUN=1 ./scripts/deploy-onprem.sh -y`
Expected: the new block appears in the printed remote commands. (Note:
`--dry-run` is not a flag this script accepts — it exits 1 with "unknown
option: --dry-run"; dry-run mode is the `DEPLOY_DRY_RUN=1` env var.)

Then prove the failure path locally without deploying:
```bash
printf '[{"name":"pro","currency":"MXN","price_monthly_cents":0,"checkout_ready_monthly":false}]' \
  | python3 -c 'import json,sys; plans=json.load(sys.stdin); print(",".join(f"{p[\"name\"]}/{p[\"currency\"]}" for p in plans if p["name"]!="free" and (p.get("price_monthly_cents",0)<=0 or not p.get("checkout_ready_monthly",False))))'
```
Expected: `pro/MXN`

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy-onprem.sh
git commit -m "feat(deploy): fail the deploy when paid plans cannot be sold

The only automated gate that inspects real production pricing — CI's schema
is built with create_all and holds no plan rows."
```

---

### Task 9: Document the rule

**Files:**
- Modify: `CLAUDE.md` (Subscription & premium gating section)

- [ ] **Step 1: Add the paragraph**

Under "### Subscription & premium gating", after the metered/boolean feature lists:

```markdown
**Plan prices have exactly one source**: `backend/app/core/plan_pricing.py`
(`CANONICAL_PRICES`, minor units). `scripts/setup_paypal_plans.py` derives
from it; the `restore_plan_prices` migration carries a FROZEN copy that
`test_plan_pricing_invariants.py` asserts has not drifted; the frontend has
NO copy and renders `—` when a row is missing or priced 0. Never add a
fourth copy — three hand-synced ones is how prod advertised "$0/mes" from
2026-07-16 to 2026-07-31 while `/checkout` returned 501.

`plan_pricing.audit_plan_rows()` detects active paid rows that cannot sell
(zero price, drift from canonical, unwired `paypal_plan_id_*`). It backs
three consumers: a startup `logger.error`, `GET /api/admin/billing-config`
(red panel on the operator console), and the `deploy-onprem.sh` smoke check
— which is the only one that sees production data, since `conftest.py`
builds the test schema with `create_all` and holds no plan rows.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: single-source plan pricing rule"
```

---

### Task 10: Full suite, PR, and production provisioning

This task is the release gate. Do not mark it complete until production actually sells.

- [ ] **Step 1: Full backend suite**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v`
Expected: all green, coverage ≥70%. Paste the tail of the output into the PR body — no "should pass" claims.

- [ ] **Step 2: Lint + frontend**

Run: `cd backend && ruff check app`
Run: `cd frontend && npm run check && npm run build`
Expected: both clean.

- [ ] **Step 3: Migration round-trip**

Run: `podman exec family_app_backend alembic upgrade head && podman exec family_app_backend alembic downgrade -1 && podman exec family_app_backend alembic upgrade head`
Expected: clean, single head.

- [ ] **Step 4: Open the PR**

```bash
git push -u origin HEAD
gh pr create --title "fix(billing): restore plan prices and guard against re-zeroing" --body-file <(cat <<'BODY'
Production has advertised `$0/mes` and returned `501 PayPal plan not
configured` on every checkout since 2026-07-16.

**Root cause** — not a missing migration. Prod's head is downstream of both
`usd_price_alignment` and `mxn_plan_currency_w6`; all four paid rows share
`updated_at = 2026-07-16 17:30:11.67115+00`; no migration in the chain
writes a 0. The rows were overwritten out of band afterwards, and
`subscription_plans` has no audit trail.

**This PR**
- one canonical price table (`app/core/plan_pricing.py`), replacing three
  hand-synced copies
- idempotent `restore_plan_prices` migration
- `audit_plan_rows()` + three consumers: startup log,
  `GET /api/admin/billing-config` (operator panel), deploy smoke check
- frontend no longer invents a price when the row is missing or 0

**Still required after merge**: the operator provisioning run that wires the
eight PayPal plan ids. Checkout stays 501 until then.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01XPg3VXcYMArftxFibsqgyC
BODY
)
```

- [ ] **Step 5: Watch CI, merge, deploy**

```bash
gh pr checks --watch
gh pr merge --squash
git checkout main && git pull
./scripts/deploy-onprem.sh
```

The deploy WILL fail at the new billing smoke check — the PayPal ids are still NULL in prod. That is correct behavior, and Step 6 is what clears it. If it does not fail, the smoke check is broken; fix it before continuing.

- [ ] **Step 6: Provision at PayPal (live) — requires explicit user approval first**

Show the user the dry run and get an explicit go-ahead before any live PayPal write. Plans at PayPal cannot be deleted, only deactivated.

```bash
ssh jc@10.1.0.91 "podman exec family_onprem_backend python -m scripts.setup_paypal_plans --dry-run"
```

After approval:
```bash
ssh jc@10.1.0.91 "podman exec family_onprem_backend python -m scripts.setup_paypal_plans"
```

The script is idempotent — it matches the product and plans **by name across all pages** and creates only what is missing, so if the 2026-07-16 provisioning really happened, this reuses those plans rather than duplicating them.

**If MXN plan creation 400s** (the PayPal business account must be
Mexico-registered to price in MXN): stop, report it to the user, and take the
documented fallback — wire USD only and set the MXN rows `is_active = false`.
Never leave a row active and unwired; that is the state that disabled every
upgrade button.

- [ ] **Step 7: Apply the wiring SQL**

The script prints one `UPDATE ... SET paypal_plan_id_<cycle> = '<id>', is_active = true WHERE name = ... AND currency = ...` per plan. Apply them:

```bash
ssh jc@10.1.0.91 "podman exec -i family_onprem_db psql -U familyapp -d familyapp" <<'SQL'
-- paste the 8 printed UPDATE statements here
SQL
```

- [ ] **Step 8: Verify production**

```bash
ssh jc@10.1.0.91 "podman exec family_onprem_db psql -U familyapp -d familyapp -c \
  \"SELECT name,currency,price_monthly_cents,price_annual_cents,paypal_plan_id_monthly IS NOT NULL AS wired,is_active FROM subscription_plans ORDER BY sort_order,currency;\""
```
Expected: four paid rows with canonical prices, `wired = t`, `is_active = t`.

```bash
curl -s https://api-family.agent-ia.mx/api/subscriptions/plans | python3 -m json.tool | grep -E '"name"|price_monthly_cents|checkout_ready_monthly'
```
Expected: non-zero prices, `checkout_ready_monthly: true` on all four paid rows.

Re-run the deploy smoke check (or `./scripts/deploy-onprem.sh` again) — it must now pass.

Open `https://family.agent-ia.mx/parent/settings/subscription` as a parent.
Expected: MX$99 / MX$199, enabled upgrade buttons, no "coming soon" note.

- [ ] **Step 9: Hand the real payment test to the user**

Creating a PayPal subscription does not charge — the buyer must approve on
PayPal's hosted page. Ask the user to complete one real checkout end to end
and confirm the subscription activates. **Do not report billing as verified
until they have.** Report exactly what was verified by machine (config,
approval URL creation) and what still rests on their click.
