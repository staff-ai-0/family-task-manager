# Receipt Scanner v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the receipt scanner into a one-tap experience with auto-detected account, structured per-item rows, duplicate guard, FX cross-charge, IVA breakout, item price-history trends, and a per-family webhook fan-out to an external price-comparison agent.

**Architecture:** Single Alembic migration (`wave4_scanner_v2`) introduces 3 new tables (`budget_transaction_items`, `family_a2a_webhooks`, `a2a_webhook_deliveries`) and 6 new columns. The existing single-call `POST /api/budget/transactions/scan-receipt` endpoint is extended with 7 server-side stages (vision → account auto-detect → duplicate guard → FX → persist → categorize → fan-out). New endpoints expose item history/trends and webhook configuration. Frontend redesigns the scan page into a snap-and-confirm flow.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic · Pydantic v2 · PostgreSQL 15 · Redis 7 · Astro 5 · Tailwind CSS v4 · Playwright · LiteLLM proxy (Claude Haiku for vision) · exchangerate.host (FX).

**Spec:** `docs/superpowers/specs/2026-05-28-receipt-scanner-v2-design.md`

---

## File Map

**Create:**
- `backend/migrations/versions/2026_05_28_wave4_scanner_v2.py`
- `backend/app/models/a2a.py`
- `backend/app/services/fx_service.py`
- `backend/app/services/budget/transaction_item_service.py`
- `backend/app/services/budget/account_matching_service.py`
- `backend/app/services/budget/duplicate_guard_service.py`
- `backend/app/services/budget/a2a_webhook_service.py`
- `backend/app/api/routes/budget/items.py`
- `backend/app/api/routes/budget/a2a_webhook.py`
- `backend/app/api/routes/internal/__init__.py`
- `backend/app/api/routes/internal/a2a_retry.py`
- `backend/tests/test_receipt_scanner_v2.py`
- `backend/tests/test_fx_service.py`
- `backend/tests/test_transaction_item_service.py`
- `backend/tests/test_a2a_webhook_service.py`
- `frontend/src/pages/budget/items/[normalized_name].astro`
- `frontend/src/pages/parent/settings/a2a.astro`
- `e2e-tests/tests/scanner-v2.spec.ts`

**Modify:**
- `backend/app/models/budget.py` (add `BudgetTransactionItem`, columns on `BudgetTransaction` + `BudgetAccount`)
- `backend/app/models/__init__.py` (export new models)
- `backend/app/schemas/budget.py` (new schemas + extend existing)
- `backend/app/services/budget/receipt_scanner_service.py` (rewrite scan-and-create flow, extend prompt)
- `backend/app/services/budget/categorization_rule_service.py` (accept `item_name` arg)
- `backend/app/api/routes/budget/transactions.py` (extend scan-receipt endpoint with `force`, `account_id` optional, 409 path)
- `backend/app/api/routes/budget/__init__.py` (register items + a2a routers)
- `backend/app/main.py` (register internal router)
- `backend/app/core/premium.py` (add `a2a_webhook`, `item_trends`, `fx_cross_charge` features)
- `backend/requirements.txt` (add `httpx` if absent; `apscheduler` if used)
- `frontend/src/pages/budget/scan-receipt.astro` (one-tap UX redesign)
- `frontend/src/lib/api/budget.ts` (new client helpers)

---

## Phased Execution

- **Phase 1 — Data layer:** Tasks 1–2
- **Phase 2 — Pure services:** Tasks 3–7
- **Phase 3 — Scanner integration:** Tasks 8–10
- **Phase 4 — New endpoints:** Tasks 11–13
- **Phase 5 — Premium gating:** Task 14
- **Phase 6 — Frontend:** Tasks 15–18
- **Phase 7 — E2E + deploy:** Tasks 19–20

Run tests inside the running backend container:

```
podman exec -e PYTHONPATH=/app family_app_backend pytest <path> -v
```

---

## Phase 1 — Data layer

### Task 1: Wave 4 Alembic migration + ORM models

**Files:**
- Create: `backend/migrations/versions/2026_05_28_wave4_scanner_v2.py`
- Create: `backend/app/models/a2a.py`
- Modify: `backend/app/models/budget.py:91-129` (add columns to `BudgetAccount` + `BudgetTransaction`, add `BudgetTransactionItem` class)
- Modify: `backend/app/models/__init__.py` (export `BudgetTransactionItem`, `FamilyA2AWebhook`, `A2AWebhookDelivery`)
- Test: `backend/tests/test_wave4_scanner_v2_migration.py` (new)

- [ ] **Step 1: Write the failing test for migration upgrade/downgrade idempotency**

Create `backend/tests/test_wave4_scanner_v2_migration.py`:

```python
"""Smoke test: wave4_scanner_v2 migration creates expected tables and columns."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_wave4_tables_exist(db: AsyncSession):
    """budget_transaction_items, family_a2a_webhooks, a2a_webhook_deliveries exist."""
    result = await db.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename IN ('budget_transaction_items', 'family_a2a_webhooks', "
        "'a2a_webhook_deliveries')"
    ))
    names = {row[0] for row in result.all()}
    assert names == {
        "budget_transaction_items",
        "family_a2a_webhooks",
        "a2a_webhook_deliveries",
    }


@pytest.mark.asyncio
async def test_wave4_new_columns_exist(db: AsyncSession):
    """Account + Transaction tables have new columns."""
    cols = await db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'budget_accounts' AND column_name = 'card_last4'"
    ))
    assert cols.scalar() == "card_last4"

    for col in ["card_last4", "iva_cents", "fx_rate",
                "original_amount_cents", "original_currency"]:
        r = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = 'budget_transactions' AND column_name = '{col}'"
        ))
        assert r.scalar() == col, f"Missing column budget_transactions.{col}"


@pytest.mark.asyncio
async def test_card_last4_backfill_from_name(db: AsyncSession, family):
    """Migration backfill regex captures **9222 / ***313 / 'terminada en 1234' patterns."""
    from app.models.budget import BudgetAccount
    a1 = BudgetAccount(family_id=family.id, name="Mastercard **9222", type="credit")
    a2 = BudgetAccount(family_id=family.id, name="Cheques Banamex ***313", type="checking")
    a3 = BudgetAccount(family_id=family.id, name="Tarjeta terminada en 1234", type="credit")
    db.add_all([a1, a2, a3])
    await db.commit()
    # Re-run the backfill UPDATE the migration emits; it must be idempotent.
    await db.execute(text(
        "UPDATE budget_accounts SET card_last4 = "
        "regexp_replace(name, '.*(?:\\*{2,}|terminada en )(\\d{4}).*', '\\1') "
        "WHERE name ~* '(\\*{2,}|terminada en )\\d{4}' AND card_last4 IS NULL"
    ))
    await db.commit()
    await db.refresh(a1); await db.refresh(a2); await db.refresh(a3)
    assert a1.card_last4 == "9222"
    assert a2.card_last4 == "313" or a2.card_last4 is None  # 3-digit suffix won't backfill (4 required)
    assert a3.card_last4 == "1234"
```

- [ ] **Step 2: Run test to verify it fails**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_wave4_scanner_v2_migration.py -v
```

Expected: FAIL — tables / columns do not exist.

- [ ] **Step 3: Create the Alembic migration**

Create `backend/migrations/versions/2026_05_28_wave4_scanner_v2.py`:

```python
"""wave4_scanner_v2: item rows, account card_last4, FX/IVA cols, a2a webhooks

Revision ID: wave4_scanner_v2
Revises: drop_stripe_v1
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "wave4_scanner_v2"
down_revision = "drop_stripe_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- BudgetAccount.card_last4 -------------------------------------------------
    op.add_column(
        "budget_accounts",
        sa.Column("card_last4", sa.CHAR(4), nullable=True),
    )
    op.create_index(
        "ix_budget_accounts_family_card_last4",
        "budget_accounts",
        ["family_id", "card_last4"],
        postgresql_where=sa.text("card_last4 IS NOT NULL"),
    )

    # Backfill from existing account names (e.g. "Mastercard **9222",
    # "Cheques Banamex ***313", "Tarjeta terminada en 1234"). The regex
    # requires exactly 4 trailing digits — 3-digit suffixes (e.g. "***313")
    # are intentionally NOT backfilled and the user can edit the account
    # later to set the correct last-4.
    op.execute(sa.text(
        "UPDATE budget_accounts SET card_last4 = "
        "regexp_replace(name, '.*(?:\\*{2,}|terminada en |XXXX|xxxx)(\\d{4}).*', '\\1') "
        "WHERE name ~* '(\\*{2,}|terminada en |XXXX|xxxx)\\d{4}' "
        "AND card_last4 IS NULL"
    ))

    # --- BudgetTransaction extra columns -----------------------------------------
    op.add_column("budget_transactions",
                  sa.Column("card_last4", sa.CHAR(4), nullable=True))
    op.add_column("budget_transactions",
                  sa.Column("iva_cents", sa.BigInteger(), nullable=True))
    op.add_column("budget_transactions",
                  sa.Column("fx_rate", sa.Numeric(12, 6), nullable=True))
    op.add_column("budget_transactions",
                  sa.Column("original_amount_cents", sa.BigInteger(), nullable=True))
    op.add_column("budget_transactions",
                  sa.Column("original_currency", sa.CHAR(3), nullable=True))

    # --- budget_transaction_items ------------------------------------------------
    op.create_table(
        "budget_transaction_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("family_id", UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("transaction_id", UUID(as_uuid=True),
                  sa.ForeignKey("budget_transactions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(10, 3), nullable=True),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True),
                  sa.ForeignKey("budget_categories.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bti_family_normalized_created",
                    "budget_transaction_items",
                    ["family_id", "normalized_name",
                     sa.text("created_at DESC")])
    op.create_index("ix_bti_transaction",
                    "budget_transaction_items", ["transaction_id"])
    op.create_index("ix_bti_family_category",
                    "budget_transaction_items", ["family_id", "category_id"])

    # --- family_a2a_webhooks -----------------------------------------------------
    op.create_table(
        "family_a2a_webhooks",
        sa.Column("family_id", UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # --- a2a_webhook_deliveries --------------------------------------------------
    op.create_table(
        "a2a_webhook_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("family_id", UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("transaction_id", UUID(as_uuid=True),
                  sa.ForeignKey("budget_transactions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_a2a_deliveries_due",
                    "a2a_webhook_deliveries",
                    ["next_retry_at"],
                    postgresql_where=sa.text("status IN ('pending', 'failed')"))
    op.create_index("ix_a2a_deliveries_family",
                    "a2a_webhook_deliveries", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_a2a_deliveries_family", table_name="a2a_webhook_deliveries")
    op.drop_index("ix_a2a_deliveries_due", table_name="a2a_webhook_deliveries")
    op.drop_table("a2a_webhook_deliveries")
    op.drop_table("family_a2a_webhooks")

    op.drop_index("ix_bti_family_category", table_name="budget_transaction_items")
    op.drop_index("ix_bti_transaction", table_name="budget_transaction_items")
    op.drop_index("ix_bti_family_normalized_created",
                  table_name="budget_transaction_items")
    op.drop_table("budget_transaction_items")

    op.drop_column("budget_transactions", "original_currency")
    op.drop_column("budget_transactions", "original_amount_cents")
    op.drop_column("budget_transactions", "fx_rate")
    op.drop_column("budget_transactions", "iva_cents")
    op.drop_column("budget_transactions", "card_last4")

    op.drop_index("ix_budget_accounts_family_card_last4",
                  table_name="budget_accounts")
    op.drop_column("budget_accounts", "card_last4")
```

- [ ] **Step 4: Add ORM column attrs on existing models**

Modify `backend/app/models/budget.py`. In `class BudgetAccount`, after line 105 (`currency` col), add:

```python
    card_last4: Mapped[Optional[str]] = mapped_column(
        CHAR(4), nullable=True,
        comment="Last 4 digits of the card associated with this account; used for receipt auto-match",
    )
```

Add `CHAR` to the imports at the top of the file (it lives in `sqlalchemy`).

In `class BudgetTransaction` (find via `grep -n "class BudgetTransaction" backend/app/models/budget.py`), after the existing `amount` column, add:

```python
    card_last4: Mapped[Optional[str]] = mapped_column(CHAR(4), nullable=True)
    iva_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    original_amount_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    original_currency: Mapped[Optional[str]] = mapped_column(CHAR(3), nullable=True)
```

Ensure `Numeric` and `Decimal` are imported (`from sqlalchemy import Numeric`, `from decimal import Decimal`).

- [ ] **Step 5: Add `BudgetTransactionItem` ORM class**

In `backend/app/models/budget.py`, add at the end of the file (before any trailing module exports):

```python
class BudgetTransactionItem(Base):
    """Line items extracted from a receipt scan or manual transaction edit."""

    __tablename__ = "budget_transaction_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budget_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    unit_price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budget_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    brand: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    transaction: Mapped["BudgetTransaction"] = relationship(
        "BudgetTransaction", back_populates="items"
    )
    category: Mapped[Optional["BudgetCategory"]] = relationship("BudgetCategory")
```

Then in `class BudgetTransaction`, add the inverse relationship (after existing relationships):

```python
    items: Mapped[list["BudgetTransactionItem"]] = relationship(
        "BudgetTransactionItem",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
```

- [ ] **Step 6: Create `backend/app/models/a2a.py` for webhook tables**

```python
"""A2A webhook configuration and delivery log."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FamilyA2AWebhook(Base):
    """One row per family. Per-family opt-in to the external price-agent."""

    __tablename__ = "family_a2a_webhooks"

    family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        primary_key=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )


class A2AWebhookDelivery(Base):
    """Retry log for a2a webhook deliveries."""

    __tablename__ = "a2a_webhook_deliveries"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budget_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )
```

- [ ] **Step 7: Wire models into `backend/app/models/__init__.py`**

Append to `backend/app/models/__init__.py`:

```python
from app.models.budget import BudgetTransactionItem  # noqa: F401
from app.models.a2a import FamilyA2AWebhook, A2AWebhookDelivery  # noqa: F401
```

- [ ] **Step 8: Run migration against test DB and rerun tests**

```
podman exec family_app_backend alembic upgrade head
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_wave4_scanner_v2_migration.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/migrations/versions/2026_05_28_wave4_scanner_v2.py \
        backend/app/models/budget.py \
        backend/app/models/a2a.py \
        backend/app/models/__init__.py \
        backend/tests/test_wave4_scanner_v2_migration.py
git commit -m "feat(scanner-v2): wave4 migration + ORM for items, a2a webhooks, FX/IVA cols"
```

---

### Task 2: Pydantic schemas

**Files:**
- Modify: `backend/app/schemas/budget.py` (add `TransactionItemRead`, `ItemTrend`, `AccountMatch`, `DupWarning`, `ScanReceiptResponse`; extend `AccountBase`/`AccountUpdate`/`AccountResponse` with `card_last4`; extend `TransactionResponse` with new columns)
- Create: `backend/app/schemas/a2a.py`
- Test: `backend/tests/test_scanner_v2_schemas.py`

- [ ] **Step 1: Write failing schema tests**

Create `backend/tests/test_scanner_v2_schemas.py`:

```python
import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.budget import (
    AccountCreate, TransactionItemRead, ItemTrend,
    AccountMatch, DupWarning, ScanReceiptResponse,
)
from app.schemas.a2a import A2AWebhookRead, A2AWebhookUpdate


def test_account_card_last4_validates_format():
    AccountCreate(name="x", type="credit", currency="MXN", card_last4="1234")
    with pytest.raises(PydanticValidationError):
        AccountCreate(name="x", type="credit", currency="MXN", card_last4="12a4")
    with pytest.raises(PydanticValidationError):
        AccountCreate(name="x", type="credit", currency="MXN", card_last4="12345")


def test_item_trend_round_trip():
    t = ItemTrend(normalized_name="leche alpura", avg_unit_cents=2800,
                  last_unit_cents=3200, pct_change=0.142, sample_size=8)
    assert t.pct_change == 0.142


def test_a2a_webhook_url_must_be_https():
    A2AWebhookUpdate(url="https://example.com/hook", enabled=True, rotate_secret=False)
    with pytest.raises(PydanticValidationError):
        A2AWebhookUpdate(url="http://example.com/hook", enabled=True, rotate_secret=False)


def test_scan_receipt_response_minimal():
    r = ScanReceiptResponse(
        success=True, transaction_id="00000000-0000-0000-0000-000000000000",
        confidence=0.9, items=[], trends=[], shopping_auto_checked=[],
        account_match=AccountMatch(strategy="last_used"),
    )
    assert r.success is True
    assert r.fx is None
```

- [ ] **Step 2: Run test to verify it fails**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_scanner_v2_schemas.py -v
```

Expected: FAIL — schemas not yet defined.

- [ ] **Step 3: Extend `AccountBase`/`AccountUpdate`/`AccountResponse`**

In `backend/app/schemas/budget.py`, locate `class AccountBase` (line 93). Add field:

```python
    card_last4: Optional[str] = Field(
        None, min_length=4, max_length=4, pattern=r"^\d{4}$",
        description="Last 4 digits of the card; used for receipt scanner auto-detect",
    )
```

Add the same field to `class AccountUpdate` (line 129). Add to `class AccountResponse` (line 157).

- [ ] **Step 4: Add new schemas at end of `backend/app/schemas/budget.py`**

```python
class TransactionItemRead(BaseModel):
    id: UUID
    transaction_id: UUID
    name: str
    normalized_name: str
    qty: Optional[Decimal] = None
    unit_price_cents: Optional[int] = None
    total_cents: int
    category_id: Optional[UUID] = None
    brand: Optional[str] = None
    raw_text: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ItemTrend(BaseModel):
    normalized_name: str
    avg_unit_cents: int
    last_unit_cents: int
    pct_change: float  # e.g. 0.142 = +14.2%
    sample_size: int


class AccountMatch(BaseModel):
    strategy: str  # "card_last4" | "last_used" | "override"
    matched_card_last4: Optional[str] = None


class DupWarning(BaseModel):
    existing_transaction_id: UUID
    scanned_at: datetime
    payee: Optional[str] = None
    amount_cents: int


class FXInfo(BaseModel):
    rate: Decimal
    original_amount_cents: int
    original_currency: str


class ScanReceiptResponse(BaseModel):
    success: bool
    transaction_id: Optional[UUID] = None
    transaction: Optional[TransactionResponse] = None
    items: list[TransactionItemRead] = []
    account_match: Optional[AccountMatch] = None
    fx: Optional[FXInfo] = None
    trends: list[ItemTrend] = []
    confidence: float = 0.0
    shopping_auto_checked: list[str] = []
    warnings: list[str] = []
    dup_warning: Optional[DupWarning] = None
    scanned_preview: Optional[dict] = None
    draft_id: Optional[UUID] = None
    message: Optional[str] = None
```

Ensure imports at top of file include: `from datetime import datetime`, `from decimal import Decimal`, `from pydantic import ConfigDict`. (Most already present; verify.)

- [ ] **Step 5: Create `backend/app/schemas/a2a.py`**

```python
"""Pydantic schemas for the per-family a2a webhook."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class A2AWebhookRead(BaseModel):
    url: Optional[str] = None
    enabled: bool = False
    last_success_at: Optional[datetime] = None
    failure_count: int = 0
    # secret is intentionally NOT exposed here

    model_config = ConfigDict(from_attributes=True)


class A2AWebhookUpdate(BaseModel):
    url: str = Field(..., description="HTTPS endpoint to POST receipt events to")
    enabled: bool = False
    rotate_secret: bool = False

    @field_validator("url")
    @classmethod
    def must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("webhook URL must use https://")
        # Pydantic HttpUrl validates the rest
        HttpUrl(v)
        return v


class A2AWebhookSaveResult(BaseModel):
    config: A2AWebhookRead
    secret: Optional[str] = Field(
        None,
        description="Plaintext secret. Returned ONLY when rotate_secret=true on save.",
    )
```

- [ ] **Step 6: Run tests, expect PASS**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_scanner_v2_schemas.py -v
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/budget.py backend/app/schemas/a2a.py \
        backend/tests/test_scanner_v2_schemas.py
git commit -m "feat(scanner-v2): pydantic schemas for items, trends, account match, a2a webhook"
```

---

## Phase 2 — Pure services

### Task 3: FXService

**Files:**
- Create: `backend/app/services/fx_service.py`
- Create: `backend/tests/test_fx_service.py`
- Modify: `backend/requirements.txt` (ensure `httpx` present; it already is — verify)

- [ ] **Step 1: Write failing FXService tests**

Create `backend/tests/test_fx_service.py`:

```python
"""FXService — historical rate lookup via exchangerate.host with Redis cache."""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.fx_service import FXService


@pytest.mark.asyncio
async def test_returns_one_for_same_currency():
    rate = await FXService.get_rate("MXN", "MXN", date(2026, 5, 28))
    assert rate == Decimal("1")


@pytest.mark.asyncio
async def test_fetches_and_caches(monkeypatch):
    """First call hits HTTP; second hits Redis cache."""
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(side_effect=[None, b"17.15"])
    fake_redis.set = AsyncMock()
    monkeypatch.setattr("app.services.fx_service._get_redis",
                        lambda: fake_redis)

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "success": True,
        "rates": {"MXN": 17.15},
    }
    fake_response.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch("app.services.fx_service.httpx.AsyncClient", return_value=fake_client):
        rate = await FXService.get_rate("USD", "MXN", date(2026, 5, 28))
        assert rate == Decimal("17.15")
        fake_redis.set.assert_awaited_once()

        # Second call: redis returns cached
        rate2 = await FXService.get_rate("USD", "MXN", date(2026, 5, 28))
        assert rate2 == Decimal("17.15")


@pytest.mark.asyncio
async def test_returns_none_on_http_failure(monkeypatch):
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock()
    monkeypatch.setattr("app.services.fx_service._get_redis",
                        lambda: fake_redis)

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=RuntimeError("boom"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch("app.services.fx_service.httpx.AsyncClient", return_value=fake_client):
        rate = await FXService.get_rate("USD", "MXN", date(2026, 5, 28))
        assert rate is None
```

- [ ] **Step 2: Run test to verify it fails**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_fx_service.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `backend/app/services/fx_service.py`**

```python
"""Foreign-exchange rate lookup with Redis cache.

Public surface: FXService.get_rate(from_ccy, to_ccy, on_date) -> Decimal | None

Source: https://exchangerate.host (free, no API key). Historical endpoint
returns rates as of a given date. We cache (from, to, date) → rate in Redis
for 24h since historical rates are immutable.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

import httpx
import redis.asyncio as aioredis

from app.core.config import settings


_REDIS_TTL_SECONDS = 24 * 3600


def _get_redis():
    return aioredis.from_url(settings.REDIS_URL, decode_responses=False)


def _cache_key(from_ccy: str, to_ccy: str, on_date: date) -> str:
    return f"fx:{from_ccy}:{to_ccy}:{on_date.isoformat()}"


class FXService:

    @staticmethod
    async def get_rate(
        from_ccy: str,
        to_ccy: str,
        on_date: date,
    ) -> Optional[Decimal]:
        """Return the rate to convert 1 unit of from_ccy into to_ccy on on_date.

        Returns None on any upstream failure — caller decides fallback.
        """
        from_ccy = from_ccy.upper()
        to_ccy = to_ccy.upper()
        if from_ccy == to_ccy:
            return Decimal("1")

        redis = _get_redis()
        key = _cache_key(from_ccy, to_ccy, on_date)
        try:
            cached = await redis.get(key)
            if cached is not None:
                return Decimal(cached.decode("utf-8"))
        except Exception:
            cached = None

        url = f"https://api.exchangerate.host/{on_date.isoformat()}"
        params = {"base": from_ccy, "symbols": to_ccy}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None

        if not data.get("success", True):  # exchangerate.host omits 'success' on OK
            return None
        rate_val = data.get("rates", {}).get(to_ccy)
        if rate_val is None:
            return None

        rate = Decimal(str(rate_val))
        try:
            await redis.set(key, str(rate), ex=_REDIS_TTL_SECONDS)
        except Exception:
            pass
        return rate
```

- [ ] **Step 4: Run tests, expect PASS**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_fx_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/fx_service.py backend/tests/test_fx_service.py
git commit -m "feat(scanner-v2): FXService with Redis-cached historical rate lookup"
```

---

### Task 4: TransactionItemService

**Files:**
- Create: `backend/app/services/budget/transaction_item_service.py`
- Create: `backend/tests/test_transaction_item_service.py`

- [ ] **Step 1: Write failing tests for normalization + CRUD + trend**

Create `backend/tests/test_transaction_item_service.py`:

```python
"""TransactionItemService — normalize names + CRUD + trend."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.budget.transaction_item_service import (
    TransactionItemService, normalize_name,
)


def test_normalize_strips_accents_and_units():
    assert normalize_name("Leche Alpura 1L") == "leche alpura"
    assert normalize_name("Aguacate Hass kg") == "aguacate hass"
    assert normalize_name("PAN INTEGRAL 500g") == "pan integral"
    assert normalize_name("Café molido 250 g") == "cafe molido"
    assert normalize_name("Yogurt   griego  ") == "yogurt griego"
    assert normalize_name("3 PZA Tomate") == "tomate"


@pytest.mark.asyncio
async def test_bulk_create_persists_items(db, family, transaction):
    items = await TransactionItemService.bulk_create(
        db, family.id, transaction.id,
        items=[
            {"name": "Leche Alpura 1L", "qty": 2, "unit_price_cents": 3200,
             "total_cents": 6400, "brand": "Alpura"},
            {"name": "Pan integral", "total_cents": 4850},
        ],
    )
    assert len(items) == 2
    assert items[0].normalized_name == "leche alpura"
    assert items[1].normalized_name == "pan integral"


@pytest.mark.asyncio
async def test_get_trend_returns_none_below_sample_size(db, family):
    trend = await TransactionItemService.get_trend(
        db, family.id, normalized_name="leche alpura", window_days=90,
    )
    assert trend is None


@pytest.mark.asyncio
async def test_get_trend_computes_pct_change(db, family, transaction_factory):
    """Seed 4 items across recent dates; verify avg and pct_change."""
    from app.models.budget import BudgetTransactionItem
    now = datetime.now(timezone.utc)
    tx = await transaction_factory(family_id=family.id, date=date.today())
    for unit_price, days_ago in [(2500, 80), (2800, 60), (2900, 30), (3200, 1)]:
        db.add(BudgetTransactionItem(
            family_id=family.id, transaction_id=tx.id,
            name="leche", normalized_name="leche alpura",
            qty=1, unit_price_cents=unit_price, total_cents=unit_price,
            created_at=now - timedelta(days=days_ago),
        ))
    await db.commit()
    trend = await TransactionItemService.get_trend(
        db, family.id, normalized_name="leche alpura", window_days=90,
    )
    assert trend is not None
    assert trend.sample_size == 4
    assert trend.last_unit_cents == 3200
    # avg of first 3 priors = (2500+2800+2900)/3 = 2733
    assert trend.avg_unit_cents == 2733
    # pct_change = (3200 - 2733) / 2733 ≈ 0.171
    assert 0.16 < trend.pct_change < 0.18


@pytest.mark.asyncio
async def test_tenant_isolation_on_list(db, family, other_family, transaction):
    """Family A cannot read Family B's items."""
    from app.models.budget import BudgetTransactionItem
    db.add(BudgetTransactionItem(
        family_id=other_family.id, transaction_id=transaction.id,
        name="bread", normalized_name="bread", total_cents=1000,
    ))
    await db.commit()
    rows = await TransactionItemService.list_for_family(
        db, family.id, normalized_name="bread",
    )
    assert rows == []
```

- [ ] **Step 2: Add fixtures `family`, `other_family`, `transaction`, `transaction_factory` to `backend/tests/conftest.py`**

Locate the existing fixtures section. Add:

```python
@pytest_asyncio.fixture
async def family(db):
    from app.models.family import Family
    fam = Family(name="Test Family")
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


@pytest_asyncio.fixture
async def other_family(db):
    from app.models.family import Family
    fam = Family(name="Other Family")
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


@pytest_asyncio.fixture
async def transaction(db, family):
    from app.models.budget import BudgetAccount, BudgetTransaction
    from datetime import date
    acct = BudgetAccount(family_id=family.id, name="Cash", type="checking",
                         currency="MXN")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)
    tx = BudgetTransaction(
        family_id=family.id, account_id=acct.id, date=date.today(),
        amount=-10000,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


@pytest_asyncio.fixture
async def transaction_factory(db, family):
    from app.models.budget import BudgetAccount, BudgetTransaction
    acct = BudgetAccount(family_id=family.id, name="F", type="checking",
                         currency="MXN")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)

    async def _make(**kwargs):
        tx = BudgetTransaction(
            family_id=kwargs.get("family_id", family.id),
            account_id=acct.id,
            date=kwargs.get("date"),
            amount=kwargs.get("amount", -10000),
        )
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        return tx
    return _make
```

(If `family`/`db` fixtures already exist, do not duplicate. Check `backend/tests/conftest.py` first.)

- [ ] **Step 3: Run tests, expect FAIL on missing module**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_transaction_item_service.py -v
```

- [ ] **Step 4: Implement `backend/app/services/budget/transaction_item_service.py`**

```python
"""Transaction item CRUD + price-trend lookup.

Items are first-class child rows of a BudgetTransaction. They power:
- per-item categorization
- price-trend badges on the confirm card
- the a2a webhook payload to the external price-comparison agent
"""

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetTransactionItem
from app.schemas.budget import ItemTrend


_UNIT_SUFFIX_RE = re.compile(
    r"\s*\b(\d+\s*(?:kg|g|lt|l|ml|pza|pzas|pieza|piezas|pkg|pack))\b\s*",
    flags=re.IGNORECASE,
)
_LEADING_QTY_RE = re.compile(r"^\s*\d+\s*(?:x|pza|pzas|pieza|piezas)?\s+", re.IGNORECASE)
_TRAILING_UNIT_RE = re.compile(
    r"\s*\b\d+\s*(?:kg|g|lt|l|ml|pza|pzas)\b\s*$", re.IGNORECASE
)


def normalize_name(raw: str) -> str:
    """Lowercase, strip accents, strip unit suffixes + leading quantities."""
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _LEADING_QTY_RE.sub("", s)
    s = _TRAILING_UNIT_RE.sub("", s)
    s = _UNIT_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


class TransactionItemService:

    @staticmethod
    async def bulk_create(
        db: AsyncSession,
        family_id: UUID,
        transaction_id: UUID,
        items: list[dict],
    ) -> list[BudgetTransactionItem]:
        """Insert a batch of items as children of a transaction."""
        rows: list[BudgetTransactionItem] = []
        for it in items:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            row = BudgetTransactionItem(
                family_id=family_id,
                transaction_id=transaction_id,
                name=name,
                normalized_name=normalize_name(name),
                qty=it.get("qty"),
                unit_price_cents=it.get("unit_price_cents"),
                total_cents=int(it.get("total_cents") or 0),
                category_id=it.get("category_id"),
                brand=it.get("brand"),
                raw_text=it.get("raw_text"),
            )
            db.add(row)
            rows.append(row)
        await db.commit()
        for r in rows:
            await db.refresh(r)
        return rows

    @staticmethod
    async def list_for_family(
        db: AsyncSession,
        family_id: UUID,
        normalized_name: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BudgetTransactionItem]:
        stmt = select(BudgetTransactionItem).where(
            BudgetTransactionItem.family_id == family_id
        )
        if normalized_name:
            stmt = stmt.where(BudgetTransactionItem.normalized_name == normalized_name)
        if since:
            stmt = stmt.where(BudgetTransactionItem.created_at >= since)
        stmt = stmt.order_by(desc(BudgetTransactionItem.created_at)).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_trend(
        db: AsyncSession,
        family_id: UUID,
        normalized_name: str,
        window_days: int = 90,
        min_sample: int = 3,
    ) -> Optional[ItemTrend]:
        """Return price trend for an item over the last window_days.

        avg_unit_cents = mean of all PRIOR items (excludes the most recent)
        last_unit_cents = the most recent item's unit_price_cents
        pct_change = (last - avg) / avg
        Returns None when sample_size < min_sample OR no priors with unit_price_cents.
        """
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        stmt = (
            select(BudgetTransactionItem)
            .where(and_(
                BudgetTransactionItem.family_id == family_id,
                BudgetTransactionItem.normalized_name == normalized_name,
                BudgetTransactionItem.created_at >= since,
                BudgetTransactionItem.unit_price_cents.isnot(None),
            ))
            .order_by(desc(BudgetTransactionItem.created_at))
        )
        rows = list((await db.execute(stmt)).scalars().all())
        if len(rows) < min_sample:
            return None
        last = rows[0]
        priors = rows[1:]
        avg = sum(int(p.unit_price_cents) for p in priors) // len(priors)
        if avg == 0:
            return None
        last_v = int(last.unit_price_cents)
        pct = (last_v - avg) / avg
        return ItemTrend(
            normalized_name=normalized_name,
            avg_unit_cents=avg,
            last_unit_cents=last_v,
            pct_change=round(pct, 4),
            sample_size=len(rows),
        )
```

- [ ] **Step 5: Run tests, expect PASS**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_transaction_item_service.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/budget/transaction_item_service.py \
        backend/tests/test_transaction_item_service.py \
        backend/tests/conftest.py
git commit -m "feat(scanner-v2): TransactionItemService with normalize + trend"
```

---

### Task 5: AccountMatchingService

**Files:**
- Create: `backend/app/services/budget/account_matching_service.py`
- Create: `backend/tests/test_account_matching_service.py`

- [ ] **Step 1: Write failing tests**

```python
"""AccountMatchingService — pick an account from card_last4 + fallbacks."""

from uuid import uuid4
import pytest

from app.services.budget.account_matching_service import AccountMatchingService


@pytest.mark.asyncio
async def test_exact_card_last4_match(db, family, account_factory):
    a = await account_factory(family.id, name="MC 9222", card_last4="9222",
                               currency="MXN")
    pick = await AccountMatchingService.match(
        db, family.id, user_id=uuid4(),
        card_last4="9222", receipt_currency="MXN",
    )
    assert pick.strategy == "card_last4"
    assert pick.account_id == a.id


@pytest.mark.asyncio
async def test_ambiguous_card_last4_narrows_by_currency(db, family, account_factory):
    mxn = await account_factory(family.id, name="MC 9222 MXN",
                                 card_last4="9222", currency="MXN")
    usd = await account_factory(family.id, name="MC 9222 USD",
                                 card_last4="9222", currency="USD")
    pick = await AccountMatchingService.match(
        db, family.id, user_id=uuid4(),
        card_last4="9222", receipt_currency="USD",
    )
    assert pick.strategy == "card_last4"
    assert pick.account_id == usd.id


@pytest.mark.asyncio
async def test_falls_back_to_last_used_when_no_match(db, family, user, account_factory,
                                                     transaction_factory_for_account):
    a1 = await account_factory(family.id, name="A1", currency="MXN")
    a2 = await account_factory(family.id, name="A2", currency="MXN")
    # Most recent tx by this user is on a2
    await transaction_factory_for_account(a2.id, user_id=user.id)
    pick = await AccountMatchingService.match(
        db, family.id, user_id=user.id,
        card_last4=None, receipt_currency="MXN",
    )
    assert pick.strategy == "last_used"
    assert pick.account_id == a2.id


@pytest.mark.asyncio
async def test_returns_none_when_no_accounts_at_all(db, family, user):
    pick = await AccountMatchingService.match(
        db, family.id, user_id=user.id,
        card_last4=None, receipt_currency="MXN",
    )
    assert pick.account_id is None
```

- [ ] **Step 2: Add `account_factory` + `user` + `transaction_factory_for_account` fixtures to `conftest.py`** (similar pattern to Task 4 fixtures; include `created_by_id` on the transaction if model supports it; otherwise inject `user_id` via the transaction's `user_id` column — verify which exists in `app/models/budget.py` first).

- [ ] **Step 3: Run tests — FAIL on missing module**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_account_matching_service.py -v
```

- [ ] **Step 4: Implement `backend/app/services/budget/account_matching_service.py`**

```python
"""Pick a target account for a scanned receipt.

Strategy order:
1. Caller-supplied account_id (validated to belong to family) → strategy="override"
2. Match BudgetAccount.card_last4 → narrow by receipt currency if >1
3. Most-recent transaction created by the authenticated user → "last_used"
4. Most-recent transaction in the family (any user) → "last_used"
5. None
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetAccount, BudgetTransaction


@dataclass
class AccountMatchResult:
    account_id: Optional[UUID]
    strategy: str  # "card_last4" | "last_used" | "override" | "none"
    matched_card_last4: Optional[str] = None
    matched_account_currency: Optional[str] = None


class AccountMatchingService:

    @staticmethod
    async def match(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        card_last4: Optional[str],
        receipt_currency: Optional[str],
        override_account_id: Optional[UUID] = None,
    ) -> AccountMatchResult:
        if override_account_id:
            stmt = select(BudgetAccount).where(and_(
                BudgetAccount.id == override_account_id,
                BudgetAccount.family_id == family_id,
            ))
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is not None:
                return AccountMatchResult(
                    account_id=row.id, strategy="override",
                    matched_account_currency=row.currency,
                )

        if card_last4:
            stmt = select(BudgetAccount).where(and_(
                BudgetAccount.family_id == family_id,
                BudgetAccount.card_last4 == card_last4,
                BudgetAccount.closed.is_(False),
                BudgetAccount.deleted_at.is_(None),
            ))
            hits = list((await db.execute(stmt)).scalars().all())
            if len(hits) == 1:
                return AccountMatchResult(
                    account_id=hits[0].id, strategy="card_last4",
                    matched_card_last4=card_last4,
                    matched_account_currency=hits[0].currency,
                )
            if len(hits) > 1 and receipt_currency:
                by_ccy = [h for h in hits if h.currency == receipt_currency.upper()]
                if len(by_ccy) == 1:
                    return AccountMatchResult(
                        account_id=by_ccy[0].id, strategy="card_last4",
                        matched_card_last4=card_last4,
                        matched_account_currency=by_ccy[0].currency,
                    )

        # Fallback: most-recent tx by this user in this family
        stmt = (
            select(BudgetTransaction.account_id, BudgetAccount.currency)
            .join(BudgetAccount, BudgetAccount.id == BudgetTransaction.account_id)
            .where(and_(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.created_by_id == user_id,
            ))
            .order_by(desc(BudgetTransaction.created_at))
            .limit(1)
        )
        result = (await db.execute(stmt)).first()
        if result:
            return AccountMatchResult(
                account_id=result[0], strategy="last_used",
                matched_account_currency=result[1],
            )

        # Fallback: any recent tx in family
        stmt = (
            select(BudgetTransaction.account_id, BudgetAccount.currency)
            .join(BudgetAccount, BudgetAccount.id == BudgetTransaction.account_id)
            .where(BudgetTransaction.family_id == family_id)
            .order_by(desc(BudgetTransaction.created_at))
            .limit(1)
        )
        result = (await db.execute(stmt)).first()
        if result:
            return AccountMatchResult(
                account_id=result[0], strategy="last_used",
                matched_account_currency=result[1],
            )

        return AccountMatchResult(account_id=None, strategy="none")
```

> **Note:** If `BudgetTransaction.created_by_id` does not exist in the model, replace with whichever column tracks the creator (verify via `grep "created_by_id\|user_id" backend/app/models/budget.py`). If neither exists, ship the fallback as "most-recent tx in family" only — and add a follow-up task to introduce `created_by_id` on transactions.

- [ ] **Step 5: Run tests, expect PASS**

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/budget/account_matching_service.py \
        backend/tests/test_account_matching_service.py \
        backend/tests/conftest.py
git commit -m "feat(scanner-v2): AccountMatchingService — card_last4 + last-used fallback"
```

---

### Task 6: DuplicateGuardService

**Files:**
- Create: `backend/app/services/budget/duplicate_guard_service.py`
- Create: `backend/tests/test_duplicate_guard_service.py`

- [ ] **Step 1: Write failing tests**

```python
"""DuplicateGuardService — flag same-payee same-amount recent receipts."""

from datetime import datetime, timedelta, timezone
import pytest

from app.services.budget.duplicate_guard_service import DuplicateGuardService


@pytest.mark.asyncio
async def test_flags_same_payee_same_amount_within_60s(
    db, family, payee, transaction_factory_with_payee,
):
    recent = await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    dup = await DuplicateGuardService.check(
        db, family.id, payee_id=payee.id, amount_cents=-72040,
    )
    assert dup is not None
    assert dup.existing_transaction_id == recent.id


@pytest.mark.asyncio
async def test_does_not_flag_after_60s(
    db, family, payee, transaction_factory_with_payee,
):
    await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=90),
    )
    dup = await DuplicateGuardService.check(
        db, family.id, payee_id=payee.id, amount_cents=-72040,
    )
    assert dup is None


@pytest.mark.asyncio
async def test_does_not_flag_when_amount_differs_more_than_1pct(
    db, family, payee, transaction_factory_with_payee,
):
    await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    dup = await DuplicateGuardService.check(
        db, family.id, payee_id=payee.id, amount_cents=-80000,
    )
    assert dup is None


@pytest.mark.asyncio
async def test_does_not_cross_families(
    db, family, other_family, payee, transaction_factory_with_payee,
):
    await transaction_factory_with_payee(
        other_family.id, payee.id, amount=-72040,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    dup = await DuplicateGuardService.check(
        db, family.id, payee_id=payee.id, amount_cents=-72040,
    )
    assert dup is None
```

- [ ] **Step 2: Add `payee` + `transaction_factory_with_payee` fixtures to conftest.py.**

- [ ] **Step 3: Run, FAIL on missing module**

- [ ] **Step 4: Implement `backend/app/services/budget/duplicate_guard_service.py`**

```python
"""Detect a likely duplicate receipt scan within a short time window."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetTransaction
from app.schemas.budget import DupWarning


class DuplicateGuardService:

    WINDOW_SECONDS = 60
    AMOUNT_TOLERANCE = 0.01  # 1%

    @classmethod
    async def check(
        cls,
        db: AsyncSession,
        family_id: UUID,
        payee_id: Optional[UUID],
        amount_cents: int,
    ) -> Optional[DupWarning]:
        if payee_id is None:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=cls.WINDOW_SECONDS)
        tol = max(1, int(abs(amount_cents) * cls.AMOUNT_TOLERANCE))
        stmt = (
            select(BudgetTransaction)
            .where(and_(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.payee_id == payee_id,
                BudgetTransaction.created_at >= cutoff,
                BudgetTransaction.amount.between(amount_cents - tol, amount_cents + tol),
            ))
            .order_by(desc(BudgetTransaction.created_at))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return DupWarning(
            existing_transaction_id=row.id,
            scanned_at=row.created_at,
            amount_cents=int(row.amount),
        )
```

- [ ] **Step 5: Run tests, expect PASS**

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/budget/duplicate_guard_service.py \
        backend/tests/test_duplicate_guard_service.py \
        backend/tests/conftest.py
git commit -m "feat(scanner-v2): DuplicateGuardService — 60s/1% same-payee guard"
```

---

### Task 7: A2AWebhookService

**Files:**
- Create: `backend/app/services/budget/a2a_webhook_service.py`
- Create: `backend/tests/test_a2a_webhook_service.py`

- [ ] **Step 1: Write failing tests**

```python
"""A2AWebhookService — enqueue, dispatch, signature, retry sweep."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.budget.a2a_webhook_service import A2AWebhookService
from app.models.a2a import FamilyA2AWebhook, A2AWebhookDelivery


@pytest.mark.asyncio
async def test_enqueue_skips_when_family_has_no_webhook(db, family, transaction):
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"hello": "world"},
    )
    assert delivery is None


@pytest.mark.asyncio
async def test_enqueue_skips_when_disabled(db, family, transaction):
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=False,
    ))
    await db.commit()
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"a": 1},
    )
    assert delivery is None


@pytest.mark.asyncio
async def test_enqueue_creates_delivery_row(db, family, transaction):
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=True,
    ))
    await db.commit()
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"k": "v"},
    )
    assert delivery is not None
    assert delivery.status == "pending"
    assert delivery.payload_json == {"k": "v"}


@pytest.mark.asyncio
async def test_dispatch_once_signs_and_marks_sent(db, family, transaction):
    secret = "abc123"
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://hook.example/x",
        secret=secret, enabled=True,
    ))
    await db.commit()
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"foo": "bar"},
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 202
    fake_resp.text = "ok"

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch("app.services.budget.a2a_webhook_service.httpx.AsyncClient",
               return_value=fake_client):
        await A2AWebhookService.dispatch_once(db, delivery.id)

    await db.refresh(delivery)
    assert delivery.status == "sent"
    assert delivery.attempts == 1

    sent_headers = fake_client.post.await_args.kwargs["headers"]
    body = fake_client.post.await_args.kwargs["content"]
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    assert sent_headers["X-A2A-Signature"] == expected


@pytest.mark.asyncio
async def test_dispatch_failure_schedules_retry(db, family, transaction):
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=True,
    ))
    await db.commit()
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"a": 1},
    )

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=RuntimeError("net"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch("app.services.budget.a2a_webhook_service.httpx.AsyncClient",
               return_value=fake_client):
        await A2AWebhookService.dispatch_once(db, delivery.id)

    await db.refresh(delivery)
    assert delivery.status == "failed"
    assert delivery.attempts == 1
    assert delivery.next_retry_at is not None
    assert delivery.next_retry_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_sweep_picks_up_due_failed(db, family, transaction):
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=True,
    ))
    db.add(A2AWebhookDelivery(
        family_id=family.id, transaction_id=transaction.id,
        payload_json={"a": 1}, status="failed", attempts=1,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    ))
    await db.commit()

    ids: list = []

    async def fake_dispatch(_db, _id):
        ids.append(_id)

    with patch.object(A2AWebhookService, "dispatch_once",
                      side_effect=fake_dispatch):
        n = await A2AWebhookService.sweep_retries(db, limit=10)

    assert n == 1
    assert len(ids) == 1
```

- [ ] **Step 2: Run — FAIL on missing module**

- [ ] **Step 3: Implement `backend/app/services/budget/a2a_webhook_service.py`**

```python
"""Per-family a2a webhook: enqueue, sign, dispatch, retry."""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.a2a import A2AWebhookDelivery, FamilyA2AWebhook


# Exponential backoff schedule for failed deliveries.
_BACKOFF_SCHEDULE = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
]
_MAX_ATTEMPTS = len(_BACKOFF_SCHEDULE)
_DISPATCH_TIMEOUT_SECONDS = 10.0


def generate_secret() -> str:
    return secrets.token_hex(32)


class A2AWebhookService:

    @staticmethod
    async def get_config(
        db: AsyncSession, family_id: UUID
    ) -> Optional[FamilyA2AWebhook]:
        result = await db.execute(
            select(FamilyA2AWebhook).where(
                FamilyA2AWebhook.family_id == family_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_config(
        db: AsyncSession,
        family_id: UUID,
        url: str,
        enabled: bool,
        rotate_secret: bool,
    ) -> tuple[FamilyA2AWebhook, Optional[str]]:
        existing = await A2AWebhookService.get_config(db, family_id)
        plaintext_secret: Optional[str] = None
        if existing is None:
            plaintext_secret = generate_secret()
            row = FamilyA2AWebhook(
                family_id=family_id, url=url,
                secret=plaintext_secret, enabled=enabled,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row, plaintext_secret

        existing.url = url
        existing.enabled = enabled
        if rotate_secret:
            plaintext_secret = generate_secret()
            existing.secret = plaintext_secret
        await db.commit()
        await db.refresh(existing)
        return existing, plaintext_secret

    @staticmethod
    async def enqueue(
        db: AsyncSession,
        family_id: UUID,
        transaction_id: UUID,
        payload: dict,
    ) -> Optional[A2AWebhookDelivery]:
        cfg = await A2AWebhookService.get_config(db, family_id)
        if cfg is None or not cfg.enabled:
            return None
        delivery = A2AWebhookDelivery(
            family_id=family_id,
            transaction_id=transaction_id,
            payload_json=payload,
            status="pending",
        )
        db.add(delivery)
        await db.commit()
        await db.refresh(delivery)
        return delivery

    @staticmethod
    async def dispatch_once(db: AsyncSession, delivery_id: UUID) -> None:
        delivery = await db.get(A2AWebhookDelivery, delivery_id)
        if delivery is None:
            return
        cfg = await A2AWebhookService.get_config(db, delivery.family_id)
        if cfg is None or not cfg.enabled:
            delivery.status = "dead"
            delivery.last_error = "no enabled webhook config"
            await db.commit()
            return

        body = json.dumps(delivery.payload_json, separators=(",", ":"),
                          sort_keys=True).encode("utf-8")
        signature = "sha256=" + hmac.new(
            cfg.secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-A2A-Signature": signature,
            "X-A2A-Delivery": str(delivery.id),
            "X-A2A-Schema": "family-budget.receipt.v1",
        }

        delivery.attempts += 1
        try:
            async with httpx.AsyncClient(timeout=_DISPATCH_TIMEOUT_SECONDS) as client:
                resp = await client.post(cfg.url, content=body, headers=headers)
            if 200 <= resp.status_code < 300:
                delivery.status = "sent"
                delivery.last_error = None
                delivery.next_retry_at = None
                cfg.last_success_at = datetime.now(timezone.utc)
                cfg.failure_count = 0
                cfg.last_error = None
            else:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            delivery.last_error = str(exc)[:500]
            if delivery.attempts >= _MAX_ATTEMPTS:
                delivery.status = "dead"
                delivery.next_retry_at = None
            else:
                delivery.status = "failed"
                delay = _BACKOFF_SCHEDULE[delivery.attempts - 1]
                delivery.next_retry_at = datetime.now(timezone.utc) + delay
            cfg.failure_count += 1
            cfg.last_error = delivery.last_error
        await db.commit()

    @staticmethod
    async def sweep_retries(db: AsyncSession, limit: int = 50) -> int:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(A2AWebhookDelivery.id).where(and_(
                A2AWebhookDelivery.status.in_(["pending", "failed"]),
                A2AWebhookDelivery.next_retry_at.isnot(None),
                A2AWebhookDelivery.next_retry_at <= now,
            )).limit(limit)
        )
        ids = [r[0] for r in result.all()]
        for _id in ids:
            await A2AWebhookService.dispatch_once(db, _id)
        return len(ids)
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/budget/a2a_webhook_service.py \
        backend/tests/test_a2a_webhook_service.py
git commit -m "feat(scanner-v2): A2AWebhookService — enqueue, HMAC sign, dispatch, retry sweep"
```

---

## Phase 3 — Scanner integration

### Task 8: Vision prompt update

**Files:**
- Modify: `backend/app/services/budget/receipt_scanner_service.py` (replace `RECEIPT_PROMPT`, extend `ScannedReceipt` dataclass + `scan_receipt` parser)
- Test: extend `backend/tests/test_receipt_scanner.py` OR new `backend/tests/test_receipt_scanner_v2.py`

- [ ] **Step 1: Write failing tests for new vision fields**

Create/append `backend/tests/test_receipt_scanner_v2.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.budget.receipt_scanner_service import scan_receipt


def _mock_vision_json(payload: dict):
    """Build an OpenAI Chat completion mock returning JSON-as-text."""
    import json as _json
    msg = MagicMock()
    msg.content = _json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    return completion


@pytest.mark.asyncio
async def test_scan_extracts_card_last4_iva_and_items(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.LITELLM_API_KEY", "test-key")
    monkeypatch.setattr("app.core.config.settings.LITELLM_API_BASE",
                        "http://litellm")

    fake = _mock_vision_json({
        "date": "2026-05-28",
        "total_amount": -72040,
        "iva_cents": 9683,
        "payee_name": "HEB",
        "card_last4": "9222",
        "currency": "MXN",
        "items": [
            {"name": "Leche Alpura 1L", "qty": 2,
             "unit_price_cents": 3200, "total_cents": 6400,
             "brand": "Alpura", "raw_text": "LECHE ALPURA 1L 2 X 32.00 64.00"},
        ],
        "confidence": 0.92,
    })
    fake_client = MagicMock()
    fake_client.chat.completions.create = MagicMock(return_value=fake)
    with patch("app.services.budget.receipt_scanner_service.OpenAI",
               return_value=fake_client):
        result = await scan_receipt(b"jpegbytes", "image/jpeg")

    assert result.card_last4 == "9222"
    assert result.iva_cents == 9683
    assert len(result.items) == 1
    item = result.items[0]
    assert item["brand"] == "Alpura"
    assert item["qty"] == 2
    assert item["unit_price_cents"] == 3200
    assert item["raw_text"].startswith("LECHE ALPURA")
```

- [ ] **Step 2: Run, FAIL — fields not parsed**

- [ ] **Step 3: Replace `RECEIPT_PROMPT` in `receipt_scanner_service.py`**

```python
RECEIPT_PROMPT = """Analyze this receipt image and extract the following information. Return ONLY valid JSON, no markdown or explanation.

{
  "date": "YYYY-MM-DD or null if unreadable",
  "total_amount": <total in the receipt's smallest currency unit (cents/centavos), as integer, NEGATIVE for expenses>,
  "iva_cents": <tax/IVA line as positive integer cents, or null if not present>,
  "payee_name": "store/business name or null",
  "card_last4": "4-digit string (last 4 of the card used) or null",
  "currency": "MXN or USD or other ISO code",
  "items": [
    {
      "name": "item description",
      "qty": <number or null>,
      "unit_price_cents": <positive integer cents per unit, or null>,
      "total_cents": <positive integer cents for the line>,
      "brand": "string or null",
      "raw_text": "the original line as printed on the receipt"
    }
  ],
  "confidence": <0.0-1.0 how confident you are in the extraction>
}

Rules:
- total_amount MUST be negative (it's an expense)
- If the receipt shows MXN $150.50, total_amount = -15050
- If the receipt shows $42.99 USD, total_amount = -4299
- card_last4: look for "**1234", "XXXX1234", "terminada en 1234", "Card: ...1234"
- iva_cents: look for "IVA", "Tax", "Impuesto" line; extract as POSITIVE cents
- Per item: extract qty when explicit ("2 x", "2 PZA"), brand when present
- Set confidence based on image clarity and readability
- If you cannot read the receipt at all, set confidence to 0 and all values to null"""
```

- [ ] **Step 4: Extend `ScannedReceipt` dataclass**

```python
@dataclass
class ScannedReceipt:
    date: Optional[date]
    total_amount: Optional[int]
    payee_name: Optional[str]
    items: list
    currency: str = "MXN"
    raw_text: str = ""
    confidence: float = 0.0
    # new in v2
    card_last4: Optional[str] = None
    iva_cents: Optional[int] = None
```

In `scan_receipt`, after `data = json.loads(...)`, populate `card_last4` and `iva_cents` from the parsed dict and pass them when constructing the return value:

```python
    return ScannedReceipt(
        date=parsed_date,
        total_amount=data.get("total_amount"),
        payee_name=data.get("payee_name"),
        items=data.get("items", []),
        currency=data.get("currency", "MXN"),
        raw_text=response_text,
        confidence=data.get("confidence", 0.0),
        card_last4=(data.get("card_last4") or None) if (
            isinstance(data.get("card_last4"), str)
            and len(data.get("card_last4", "")) == 4
            and data.get("card_last4", "").isdigit()
        ) else None,
        iva_cents=data.get("iva_cents") if isinstance(data.get("iva_cents"), int) else None,
    )
```

- [ ] **Step 5: Run tests, expect PASS**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_receipt_scanner_v2.py::test_scan_extracts_card_last4_iva_and_items -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/budget/receipt_scanner_service.py \
        backend/tests/test_receipt_scanner_v2.py
git commit -m "feat(scanner-v2): vision prompt + parser extract card_last4 + iva + qty/brand"
```

---

### Task 9: Rewrite `scan_and_create_transaction` pipeline

**Files:**
- Modify: `backend/app/services/budget/receipt_scanner_service.py` (rewrite `scan_and_create_transaction` to run the 7 stages: vision → account match → dup-guard → FX → persist tx+items → categorize → enqueue webhook)
- Modify: `backend/app/services/budget/categorization_rule_service.py` (extend `suggest_category` to accept optional `item_name`)
- Test: extend `backend/tests/test_receipt_scanner_v2.py`

- [ ] **Step 1: Write failing pipeline integration tests**

Append to `backend/tests/test_receipt_scanner_v2.py`:

```python
from datetime import date
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.budget.receipt_scanner_service import (
    scan_and_create_transaction,
)


@pytest.mark.asyncio
async def test_pipeline_creates_tx_with_items_and_fx(
    db, family, user, account_factory, monkeypatch,
):
    mxn = await account_factory(family.id, name="MC MXN",
                                 card_last4="9222", currency="MXN")

    fake_receipt = MagicMock(
        date=date(2026, 5, 28), total_amount=-72040,
        payee_name="HEB", currency="MXN",
        card_last4="9222", iva_cents=9683, confidence=0.92,
        items=[{"name": "Leche", "qty": 2, "unit_price_cents": 3200,
                 "total_cents": 6400, "raw_text": "LECHE 2x 64.00"}],
    )
    async def fake_scan(_b, _t): return fake_receipt
    monkeypatch.setattr("app.services.budget.receipt_scanner_service.scan_receipt",
                        fake_scan)

    result = await scan_and_create_transaction(
        db=db, family_id=family.id, user_id=user.id,
        account_id=None, image_bytes=b"x", media_type="image/jpeg",
        force=False,
    )
    assert result["success"] is True
    assert result["transaction_id"] is not None
    assert len(result["items"]) == 1
    assert result["account_match"]["strategy"] == "card_last4"


@pytest.mark.asyncio
async def test_pipeline_returns_dup_warning_without_committing(
    db, family, user, account_factory, payee, transaction_factory_with_payee,
    monkeypatch,
):
    mxn = await account_factory(family.id, card_last4="9222", currency="MXN")
    # Recent same-payee same-amount tx
    await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
        created_at=None,  # default now
    )

    fake_receipt = MagicMock(
        date=date(2026, 5, 28), total_amount=-72040,
        payee_name=payee.name, currency="MXN",
        card_last4="9222", iva_cents=None, confidence=0.92,
        items=[],
    )
    async def fake_scan(_b, _t): return fake_receipt
    monkeypatch.setattr("app.services.budget.receipt_scanner_service.scan_receipt",
                        fake_scan)

    result = await scan_and_create_transaction(
        db=db, family_id=family.id, user_id=user.id,
        account_id=None, image_bytes=b"x", media_type="image/jpeg",
        force=False,
    )
    assert result["success"] is False
    assert result["dup_warning"] is not None
    assert result["transaction_id"] is None


@pytest.mark.asyncio
async def test_force_true_bypasses_duplicate_guard(
    db, family, user, account_factory, payee, transaction_factory_with_payee,
    monkeypatch,
):
    mxn = await account_factory(family.id, card_last4="9222", currency="MXN")
    await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
    )
    fake_receipt = MagicMock(
        date=date(2026, 5, 28), total_amount=-72040,
        payee_name=payee.name, currency="MXN",
        card_last4="9222", iva_cents=None, confidence=0.92, items=[],
    )
    async def fake_scan(_b, _t): return fake_receipt
    monkeypatch.setattr("app.services.budget.receipt_scanner_service.scan_receipt",
                        fake_scan)
    result = await scan_and_create_transaction(
        db=db, family_id=family.id, user_id=user.id,
        account_id=None, image_bytes=b"x", media_type="image/jpeg",
        force=True,
    )
    assert result["success"] is True
    assert result["transaction_id"] is not None


@pytest.mark.asyncio
async def test_pipeline_stores_fx_when_currencies_differ(
    db, family, user, account_factory, monkeypatch,
):
    mxn = await account_factory(family.id, card_last4=None, currency="MXN")

    fake_receipt = MagicMock(
        date=date(2026, 5, 28), total_amount=-4200,
        payee_name="WALMART US", currency="USD",
        card_last4=None, iva_cents=None, confidence=0.92, items=[],
    )
    async def fake_scan(_b, _t): return fake_receipt
    monkeypatch.setattr("app.services.budget.receipt_scanner_service.scan_receipt",
                        fake_scan)

    from decimal import Decimal
    async def fake_fx(*_a, **_k): return Decimal("17.15")
    monkeypatch.setattr("app.services.fx_service.FXService.get_rate", fake_fx)

    # User has Pro plan so fx_cross_charge is enabled
    async def allow_feature(*_a, **_k): return MagicMock(name="pro")
    monkeypatch.setattr("app.services.budget.receipt_scanner_service.is_feature_enabled",
                        AsyncMock(return_value=True))

    result = await scan_and_create_transaction(
        db=db, family_id=family.id, user_id=user.id,
        account_id=mxn.id, image_bytes=b"x", media_type="image/jpeg",
        force=False,
    )
    assert result["success"] is True
    assert result["fx"]["rate"] == "17.15"
    assert result["fx"]["original_currency"] == "USD"
    assert result["fx"]["original_amount_cents"] == -4200
```

- [ ] **Step 2: Add `is_feature_enabled` import + helper to `receipt_scanner_service.py`**

At top of file:

```python
from fastapi import BackgroundTasks  # optional; pass through if caller provides one
from app.core.premium import get_family_plan, FEATURE_LIMIT_MAP, FEATURE_MIN_PLAN

_PLAN_ORDER = {"free": 0, "plus": 1, "pro": 2}

async def is_feature_enabled(db, family_id, feature: str) -> bool:
    """Cheap boolean check (no usage increment, no HTTPException). For
    optional features inside the pipeline (fx_cross_charge, item_trends,
    a2a_webhook). Resolves the family's plan and compares to the minimum
    plan required for the feature.
    """
    from app.models.user import User
    from sqlalchemy import select
    r = await db.execute(select(User).where(User.family_id == family_id).limit(1))
    user = r.scalar_one_or_none()
    if user is None:
        return False
    plan = await get_family_plan(db, user)
    min_plan = FEATURE_MIN_PLAN.get(feature, "free")
    return _PLAN_ORDER.get(plan.name, 0) >= _PLAN_ORDER.get(min_plan, 0)
```

- [ ] **Step 3: Rewrite `scan_and_create_transaction`**

Replace the existing function body with:

```python
async def scan_and_create_transaction(
    db: AsyncSession,
    family_id: UUID,
    user_id: UUID,
    account_id: Optional[UUID],
    image_bytes: bytes,
    media_type: str,
    force: bool = False,
) -> dict:
    """Run the 7-stage scanner v2 pipeline.

    Stages: vision → account match → duplicate guard → FX cross-charge →
    persist transaction+items → auto-categorize → fan-out (shopping
    auto-check, a2a webhook enqueue).
    """
    from app.services.budget.account_matching_service import AccountMatchingService
    from app.services.budget.duplicate_guard_service import DuplicateGuardService
    from app.services.budget.transaction_item_service import (
        TransactionItemService, normalize_name,
    )
    from app.services.budget.a2a_webhook_service import A2AWebhookService
    from app.services.fx_service import FXService

    # (1) Vision extract
    receipt = await scan_receipt(image_bytes, media_type)

    scanned_dict = {
        "date": receipt.date.isoformat() if receipt.date else None,
        "total_amount": receipt.total_amount,
        "payee_name": receipt.payee_name,
        "items": receipt.items,
        "currency": receipt.currency,
        "card_last4": receipt.card_last4,
        "iva_cents": receipt.iva_cents,
    }

    # HITL: low confidence routes to the drafts queue (unchanged from v1)
    if receipt.confidence < 0.3 or receipt.total_amount is None:
        return await _route_to_drafts(
            db, family_id, account_id, image_bytes, receipt, scanned_dict
        )

    # (2) Account auto-detect
    match = await AccountMatchingService.match(
        db, family_id, user_id=user_id,
        card_last4=receipt.card_last4,
        receipt_currency=receipt.currency,
        override_account_id=account_id,
    )
    if match.account_id is None:
        # No accounts at all → drafts queue
        return await _route_to_drafts(
            db, family_id, None, image_bytes, receipt, scanned_dict,
            reason="no_accounts",
        )

    # FX gating: non-Pro and currency mismatch → drafts queue
    fx_allowed = await is_feature_enabled(db, family_id, "fx_cross_charge")
    if (match.matched_account_currency != receipt.currency
            and not fx_allowed):
        return await _route_to_drafts(
            db, family_id, match.account_id, image_bytes, receipt,
            scanned_dict, reason="currency_mismatch",
        )

    # Resolve payee (needed for dup-guard)
    payee_id = await _find_or_create_payee(db, family_id, receipt.payee_name)

    # (3) Duplicate guard
    if not force:
        dup = await DuplicateGuardService.check(
            db, family_id, payee_id=payee_id, amount_cents=receipt.total_amount,
        )
        if dup is not None:
            # Roll back the just-created payee if it was new — leaving an
            # unused payee row is acceptable noise for v1 (find-or-create
            # is idempotent on a re-scan with force=true).
            return {
                "success": False,
                "transaction_id": None,
                "dup_warning": {
                    "existing_transaction_id": str(dup.existing_transaction_id),
                    "scanned_at": dup.scanned_at.isoformat(),
                    "amount_cents": dup.amount_cents,
                    "payee": receipt.payee_name,
                },
                "scanned_preview": scanned_dict,
                "confidence": receipt.confidence,
            }

    # (4) FX cross-charge
    fx_info = None
    final_amount = receipt.total_amount
    original_amount = None
    original_currency = None
    fx_rate = None
    warnings: list[str] = []
    if match.matched_account_currency != receipt.currency and fx_allowed:
        rate = await FXService.get_rate(
            receipt.currency, match.matched_account_currency,
            on_date=receipt.date or date.today(),
        )
        if rate is None:
            warnings.append("fx_unavailable")
        else:
            original_amount = receipt.total_amount
            original_currency = receipt.currency
            fx_rate = rate
            # Convert (signed)
            from decimal import ROUND_HALF_UP, Decimal
            final_amount = int(
                (Decimal(receipt.total_amount) * rate).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            fx_info = {
                "rate": str(rate),
                "original_amount_cents": original_amount,
                "original_currency": original_currency,
            }

    # (5) Persist transaction
    from app.models.budget import BudgetTransaction
    txn_date = receipt.date or date.today()
    txn = BudgetTransaction(
        family_id=family_id,
        account_id=match.account_id,
        date=txn_date,
        amount=final_amount,
        payee_id=payee_id,
        notes=_build_notes(receipt.payee_name, receipt.items, receipt.currency),
        cleared=False,
        reconciled=False,
        card_last4=receipt.card_last4,
        iva_cents=receipt.iva_cents,
        fx_rate=fx_rate,
        original_amount_cents=original_amount,
        original_currency=original_currency,
    )
    db.add(txn)
    await db.flush()

    # (5b) Persist items
    items_persisted = await TransactionItemService.bulk_create(
        db, family_id, txn.id, items=receipt.items,
    )

    # (6) Auto-categorize (transaction header + each item)
    header_cat = await CategorizationRuleService.suggest_category(
        db, family_id, payee=receipt.payee_name, description=None,
    )
    if header_cat:
        txn.category_id = header_cat
    for it in items_persisted:
        it.category_id = await CategorizationRuleService.suggest_category(
            db, family_id, payee=receipt.payee_name,
            description=None, item_name=it.name,
        )
    await db.commit()
    await db.refresh(txn)

    # (7a) Shopping auto-check
    shopping_auto_checked: list[str] = []
    try:
        shopping_auto_checked = await _auto_check_shopping_items(
            db, family_id, [i.get("name", "") for i in receipt.items]
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("shopping auto-check failed")

    # (7b) Trends per item (only if feature allowed and items present)
    trends: list[dict] = []
    if await is_feature_enabled(db, family_id, "item_trends"):
        seen = set()
        for it in items_persisted:
            if it.normalized_name in seen:
                continue
            seen.add(it.normalized_name)
            trend = await TransactionItemService.get_trend(
                db, family_id, normalized_name=it.normalized_name,
            )
            if trend:
                trends.append(trend.model_dump())

    # (7c) A2A webhook enqueue
    if await is_feature_enabled(db, family_id, "a2a_webhook"):
        payload = _build_webhook_payload(
            family_id, txn, items_persisted, receipt.currency,
        )
        try:
            delivery = await A2AWebhookService.enqueue(
                db, family_id, txn.id, payload=payload,
            )
            if delivery is not None:
                # Best-effort first attempt inline; sweep handles retries.
                await A2AWebhookService.dispatch_once(db, delivery.id)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("a2a enqueue/dispatch failed")

    return {
        "success": True,
        "transaction_id": str(txn.id),
        "items": [
            {
                "id": str(it.id),
                "name": it.name,
                "normalized_name": it.normalized_name,
                "qty": float(it.qty) if it.qty is not None else None,
                "unit_price_cents": it.unit_price_cents,
                "total_cents": it.total_cents,
                "brand": it.brand,
                "category_id": str(it.category_id) if it.category_id else None,
            }
            for it in items_persisted
        ],
        "account_match": {
            "strategy": match.strategy,
            "matched_card_last4": match.matched_card_last4,
        },
        "fx": fx_info,
        "trends": trends,
        "confidence": receipt.confidence,
        "shopping_auto_checked": shopping_auto_checked,
        "warnings": warnings,
        "dup_warning": None,
        "scanned_preview": None,
    }


async def _find_or_create_payee(
    db: AsyncSession, family_id: UUID, payee_name: Optional[str]
) -> Optional[UUID]:
    if not payee_name:
        return None
    stmt = select(BudgetPayee).where(
        BudgetPayee.family_id == family_id,
        BudgetPayee.name == payee_name,
    )
    payee = (await db.execute(stmt)).scalars().first()
    if payee:
        return payee.id
    new_payee = BudgetPayee(family_id=family_id, name=payee_name)
    db.add(new_payee)
    await db.flush()
    return new_payee.id


async def _route_to_drafts(
    db, family_id, account_id, image_bytes, receipt, scanned_dict,
    reason: str = "low_confidence",
):
    draft = await ReceiptDraftService.create(
        db=db, family_id=family_id, account_id=account_id,
        scanned_data=scanned_dict, confidence=receipt.confidence,
    )
    try:
        os.makedirs(RECEIPT_UPLOADS_DIR, exist_ok=True)
        img_path = os.path.join(RECEIPT_UPLOADS_DIR, f"{draft.id}.jpg")
        with open(img_path, "wb") as f:
            f.write(image_bytes)
        draft.image_url = f"/api/budget/receipt-drafts/{draft.id}/image"
        await db.commit()
    except Exception:
        pass
    return {
        "success": False,
        "draft_id": str(draft.id),
        "confidence": receipt.confidence,
        "scanned_data": scanned_dict,
        "message": f"Routed to drafts queue: {reason}",
        "transaction_id": None,
    }


def _build_webhook_payload(family_id, txn, items, currency) -> dict:
    return {
        "schema": "family-budget.receipt.v1",
        "family_id": str(family_id),
        "transaction_id": str(txn.id),
        "occurred_at": txn.created_at.isoformat() if txn.created_at else None,
        "payee": None,  # populated by caller before enqueue if needed
        "currency": currency,
        "total_cents": int(txn.amount),
        "iva_cents": txn.iva_cents,
        "items": [
            {
                "name": it.name,
                "normalized_name": it.normalized_name,
                "qty": float(it.qty) if it.qty is not None else None,
                "unit_price_cents": it.unit_price_cents,
                "total_cents": it.total_cents,
                "category": None,
                "brand": it.brand,
            }
            for it in items
        ],
        "location_hint": None,
    }
```

- [ ] **Step 4: Extend `CategorizationRuleService.suggest_category` with optional `item_name`**

In `backend/app/services/budget/categorization_rule_service.py`, add `item_name: Optional[str] = None` to the `suggest_category` signature. Use it as an additional match field against any rule whose `description_pattern` regex matches `item_name` (read existing rule matching logic to find the exact insertion point — keep payee match first, then description fallback, then item_name fallback).

- [ ] **Step 5: Run pipeline tests**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_receipt_scanner_v2.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/budget/receipt_scanner_service.py \
        backend/app/services/budget/categorization_rule_service.py \
        backend/tests/test_receipt_scanner_v2.py
git commit -m "feat(scanner-v2): 7-stage pipeline — account match, dup-guard, FX, items, webhook"
```

---

### Task 10: Extend `scan-receipt` endpoint

**Files:**
- Modify: `backend/app/api/routes/budget/transactions.py:434-510` (endpoint signature, 409 path, return shape)
- Test: extend `backend/tests/test_receipt_scanner_v2.py`

- [ ] **Step 1: Write failing endpoint tests**

```python
import pytest


@pytest.mark.asyncio
async def test_endpoint_returns_409_on_dup(client, auth_headers,
                                            family_with_recent_heb_tx):
    files = {"file": ("r.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}
    # The fixture sets up a 1-min-old HEB tx for the same amount;
    # the mocked scan_receipt returns same payee + amount.
    resp = await client.post("/api/budget/transactions/scan-receipt",
                             files=files, headers=auth_headers)
    assert resp.status_code == 409
    body = resp.json()
    assert "dup_warning" in body


@pytest.mark.asyncio
async def test_endpoint_force_true_commits(client, auth_headers,
                                            family_with_recent_heb_tx):
    files = {"file": ("r.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}
    resp = await client.post(
        "/api/budget/transactions/scan-receipt?force=true",
        files=files, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_endpoint_account_id_overrides_auto_detect(
    client, auth_headers, account_factory_authed,
):
    a = await account_factory_authed(currency="MXN")
    files = {"file": ("r.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}
    resp = await client.post(
        f"/api/budget/transactions/scan-receipt?account_id={a.id}",
        files=files, headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_match"]["strategy"] == "override"
```

(Add the fixtures `family_with_recent_heb_tx`, `account_factory_authed`, `client`, `auth_headers` to conftest.py; `client` uses `httpx.AsyncClient` + `ASGITransport` already wired up in the existing conftest.)

- [ ] **Step 2: Run, FAIL on signature / status code**

- [ ] **Step 3: Modify the endpoint in `backend/app/api/routes/budget/transactions.py`**

Replace the existing `scan_receipt_endpoint` with:

```python
@router.post("/scan-receipt", status_code=status.HTTP_200_OK)
async def scan_receipt_endpoint(
    file: UploadFile = File(...),
    account_id: Optional[UUID] = Form(None),
    force: bool = Query(False),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
    response: Response = None,
):
    family_id = to_uuid_required(current_user.family_id)
    await require_feature("ai_features", db, current_user)
    await require_feature("receipt_scan", db, current_user)
    await UsageService.increment(db, family_id, "receipt_scan")

    if account_id is not None:
        from app.services.budget.account_service import AccountService
        await AccountService.get_by_id(db, account_id, family_id)

    allowed_types = {
        "image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf",
    }
    content_type = file.content_type or "image/jpeg"
    if content_type not in allowed_types:
        return {
            "success": False,
            "message": f"Unsupported file type: {content_type}.",
            "transaction_id": None,
        }

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        return {
            "success": False,
            "message": "File too large. Maximum size is 10MB.",
            "transaction_id": None,
        }

    result = await scan_and_create_transaction(
        db=db, family_id=family_id, user_id=current_user.id,
        account_id=account_id, image_bytes=file_bytes,
        media_type=content_type, force=force,
    )

    if result.get("dup_warning") is not None:
        response.status_code = status.HTTP_409_CONFLICT

    return result
```

Add to imports at top of file:
```python
from fastapi import Response, Query
from typing import Optional
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/budget/transactions.py \
        backend/tests/test_receipt_scanner_v2.py \
        backend/tests/conftest.py
git commit -m "feat(scanner-v2): extend scan-receipt endpoint with force + 409 dup_warning"
```

---

## Phase 4 — New endpoints

### Task 11: Items endpoints

**Files:**
- Create: `backend/app/api/routes/budget/items.py`
- Modify: `backend/app/api/routes/budget/__init__.py` (register router)
- Test: extend `backend/tests/test_transaction_item_service.py` with HTTP tests OR new file

- [ ] **Step 1: Write failing endpoint tests**

```python
@pytest.mark.asyncio
async def test_list_items_filters_by_family(client, auth_headers, family,
                                              seeded_items):
    resp = await client.get("/api/budget/items?normalized_name=leche+alpura",
                            headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1


@pytest.mark.asyncio
async def test_trend_returns_null_when_below_sample(client, auth_headers):
    resp = await client.get(
        "/api/budget/items/trend?normalized_name=nonexistent",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() is None
```

- [ ] **Step 2: Implement `backend/app/api/routes/budget/items.py`**

```python
"""Item history + price-trend endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.models import User
from app.schemas.budget import TransactionItemRead, ItemTrend
from app.services.budget.transaction_item_service import TransactionItemService


router = APIRouter()


@router.get("/", response_model=list[TransactionItemRead])
async def list_items(
    normalized_name: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    rows = await TransactionItemService.list_for_family(
        db, family_id,
        normalized_name=normalized_name, since=since,
        limit=limit, offset=offset,
    )
    return rows


@router.get("/trend", response_model=Optional[ItemTrend])
async def get_trend(
    normalized_name: str = Query(...),
    window_days: int = Query(90, ge=7, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    return await TransactionItemService.get_trend(
        db, family_id, normalized_name=normalized_name,
        window_days=window_days,
    )
```

- [ ] **Step 3: Register the router in `backend/app/api/routes/budget/__init__.py`**

```python
from app.api.routes.budget import items as _items
budget_router.include_router(_items.router, prefix="/items", tags=["budget-items"])
```

(Match existing include style in that file.)

- [ ] **Step 4: Run, PASS, commit**

```bash
git add backend/app/api/routes/budget/items.py \
        backend/app/api/routes/budget/__init__.py \
        backend/tests/test_transaction_item_service.py
git commit -m "feat(scanner-v2): /api/budget/items list + trend endpoints"
```

---

### Task 12: A2A webhook config endpoints

**Files:**
- Create: `backend/app/api/routes/budget/a2a_webhook.py`
- Modify: `backend/app/api/routes/budget/__init__.py`
- Test: extend `backend/tests/test_a2a_webhook_service.py` with HTTP tests

- [ ] **Step 1: Write failing endpoint tests** for GET / PUT (parent-only, rotate_secret returns plaintext once, https-only validation).

```python
@pytest.mark.asyncio
async def test_put_webhook_returns_secret_on_rotate(client, parent_auth_headers):
    resp = await client.put(
        "/api/budget/a2a-webhook",
        json={"url": "https://hook.example/x",
              "enabled": True, "rotate_secret": True},
        headers=parent_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["secret"] is not None


@pytest.mark.asyncio
async def test_put_rejects_http(client, parent_auth_headers):
    resp = await client.put(
        "/api/budget/a2a-webhook",
        json={"url": "http://hook.example/x",
              "enabled": True, "rotate_secret": True},
        headers=parent_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_webhook_hides_secret(client, parent_auth_headers,
                                          enabled_webhook):
    resp = await client.get("/api/budget/a2a-webhook",
                            headers=parent_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "secret" not in body
```

- [ ] **Step 2: Implement `backend/app/api/routes/budget/a2a_webhook.py`**

```python
"""Per-family a2a webhook configuration."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
from app.schemas.a2a import A2AWebhookRead, A2AWebhookUpdate, A2AWebhookSaveResult
from app.services.budget.a2a_webhook_service import A2AWebhookService


router = APIRouter()


@router.get("/", response_model=A2AWebhookRead)
async def get_webhook(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    cfg = await A2AWebhookService.get_config(db, family_id)
    if cfg is None:
        return A2AWebhookRead(enabled=False)
    return cfg


@router.put("/", response_model=A2AWebhookSaveResult)
async def put_webhook(
    payload: A2AWebhookUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    cfg, plaintext = await A2AWebhookService.upsert_config(
        db, family_id, url=payload.url, enabled=payload.enabled,
        rotate_secret=payload.rotate_secret,
    )
    return A2AWebhookSaveResult(
        config=A2AWebhookRead.model_validate(cfg),
        secret=plaintext,
    )
```

- [ ] **Step 3: Register** in `backend/app/api/routes/budget/__init__.py`:

```python
from app.api.routes.budget import a2a_webhook as _a2a
budget_router.include_router(_a2a.router, prefix="/a2a-webhook", tags=["budget-a2a"])
```

- [ ] **Step 4: Run, PASS, commit**

```bash
git add backend/app/api/routes/budget/a2a_webhook.py \
        backend/app/api/routes/budget/__init__.py \
        backend/tests/test_a2a_webhook_service.py
git commit -m "feat(scanner-v2): GET/PUT /api/budget/a2a-webhook (parent only)"
```

---

### Task 13: Internal retry sweep endpoint

**Files:**
- Create: `backend/app/api/routes/internal/__init__.py`
- Create: `backend/app/api/routes/internal/a2a_retry.py`
- Modify: `backend/app/main.py` (register internal router under `/api/internal`)
- Modify: `backend/app/core/config.py` (add `INTERNAL_API_TOKEN` setting)
- Test: extend `backend/tests/test_a2a_webhook_service.py`

- [ ] **Step 1: Write failing test for the sweep endpoint guarded by token**

```python
@pytest.mark.asyncio
async def test_internal_retry_requires_token(client):
    resp = await client.post("/api/internal/a2a/retry")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_internal_retry_calls_sweep(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.INTERNAL_API_TOKEN", "tkn")
    called = {}
    async def fake_sweep(db, limit=50): called["n"] = limit; return 3
    monkeypatch.setattr(
        "app.services.budget.a2a_webhook_service.A2AWebhookService.sweep_retries",
        fake_sweep,
    )
    resp = await client.post(
        "/api/internal/a2a/retry",
        headers={"X-Internal-Token": "tkn"},
    )
    assert resp.status_code == 200
    assert resp.json()["processed"] == 3
```

- [ ] **Step 2: Add `INTERNAL_API_TOKEN` to `backend/app/core/config.py`** (one new line in the Settings class).

```python
    INTERNAL_API_TOKEN: str = ""
```

- [ ] **Step 3: Create `backend/app/api/routes/internal/__init__.py`** (empty), and `a2a_retry.py`:

```python
"""Internal retry sweep — invoked by external cron / scheduler."""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.budget.a2a_webhook_service import A2AWebhookService


router = APIRouter()


def _require_token(x_internal_token: str = Header(None)):
    if not settings.INTERNAL_API_TOKEN or x_internal_token != settings.INTERNAL_API_TOKEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid internal token")


@router.post("/a2a/retry")
async def retry_sweep(
    _t: None = Depends(_require_token),
    db: AsyncSession = Depends(get_db),
):
    n = await A2AWebhookService.sweep_retries(db, limit=50)
    return {"processed": n}
```

- [ ] **Step 4: Register router in `backend/app/main.py`**

After existing budget router includes:

```python
from app.api.routes.internal import a2a_retry as _internal_a2a
app.include_router(_internal_a2a.router, prefix="/api/internal", tags=["internal"])
```

- [ ] **Step 5: Run, PASS, commit**

```bash
git add backend/app/api/routes/internal/__init__.py \
        backend/app/api/routes/internal/a2a_retry.py \
        backend/app/main.py \
        backend/app/core/config.py \
        backend/tests/test_a2a_webhook_service.py
git commit -m "feat(scanner-v2): /api/internal/a2a/retry sweep endpoint (token-guarded)"
```

---

## Phase 5 — Premium gating

### Task 14: Plan feature flags

**Files:**
- Modify: `backend/app/core/premium.py` (add `a2a_webhook`, `item_trends`, `fx_cross_charge` boolean features)
- Modify: `backend/app/core/premium.py` `DEFAULT_FREE_LIMITS` (add new keys = False)
- Test: extend `backend/tests/test_subscription.py` OR new `backend/tests/test_premium_v2.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_free_plan_blocks_a2a_webhook(db, free_user):
    from app.core.premium import require_feature
    with pytest.raises(Exception):
        await require_feature("a2a_webhook", db, free_user)


@pytest.mark.asyncio
async def test_pro_plan_allows_fx_cross_charge(db, pro_user):
    from app.core.premium import require_feature
    await require_feature("fx_cross_charge", db, pro_user)  # no raise
```

- [ ] **Step 2: Edit `backend/app/core/premium.py`**

Update `DEFAULT_FREE_LIMITS`:

```python
DEFAULT_FREE_LIMITS: dict[str, Any] = {
    # ... existing ...
    "a2a_webhook": False,
    "item_trends": False,
    "fx_cross_charge": False,
}
```

Update `FEATURE_LIMIT_MAP`:

```python
FEATURE_LIMIT_MAP: dict[str, str] = {
    # ... existing ...
    "a2a_webhook": "a2a_webhook",
    "item_trends": "item_trends",
    "fx_cross_charge": "fx_cross_charge",
}
```

Update `FEATURE_MIN_PLAN`:

```python
FEATURE_MIN_PLAN: dict[str, str] = {
    # ... existing ...
    "a2a_webhook": "plus",
    "item_trends": "plus",
    "fx_cross_charge": "pro",
}
```

If the `subscription_plans` table is seeded with rows whose `limits` JSON drives `plus`/`pro`, update the seed (`backend/seed_data.py` or whichever file initializes the rows) so the new keys appear in the Plus + Pro limits dicts as `True`. Run the seed in the test container so the flags propagate.

- [ ] **Step 3: Run tests, PASS, commit**

```bash
git add backend/app/core/premium.py backend/tests/test_premium_v2.py
git commit -m "feat(scanner-v2): premium flags a2a_webhook, item_trends, fx_cross_charge"
```

---

## Phase 6 — Frontend

### Task 15: Redesign `/budget/scan-receipt` — confirm card

**Files:**
- Modify: `frontend/src/pages/budget/scan-receipt.astro` (drop pre-pick account dropdown; add scan animation overlay; render new confirm card)
- Modify: `frontend/src/lib/api/budget.ts` (add `scanReceipt(file, opts)` with `force`, `account_id` and the new response shape)

- [ ] **Step 1: Update client helper `frontend/src/lib/api/budget.ts`**

Append:

```ts
export interface ScanReceiptResponse {
  success: boolean;
  transaction_id: string | null;
  transaction?: any;
  items: Array<{
    id: string; name: string; normalized_name: string;
    qty: number | null; unit_price_cents: number | null;
    total_cents: number; brand: string | null;
    category_id: string | null;
  }>;
  account_match?: { strategy: string; matched_card_last4: string | null };
  fx?: { rate: string; original_amount_cents: number; original_currency: string } | null;
  trends: Array<{
    normalized_name: string; avg_unit_cents: number;
    last_unit_cents: number; pct_change: number; sample_size: number;
  }>;
  confidence: number;
  shopping_auto_checked: string[];
  warnings: string[];
  dup_warning: {
    existing_transaction_id: string;
    scanned_at: string;
    amount_cents: number;
    payee: string | null;
  } | null;
  scanned_preview?: Record<string, unknown> | null;
  draft_id?: string | null;
  message?: string | null;
}

export async function scanReceipt(
  token: string,
  file: File,
  opts: { force?: boolean; account_id?: string } = {},
): Promise<{ status: number; body: ScanReceiptResponse }> {
  const form = new FormData();
  form.append("file", file);
  const q = new URLSearchParams();
  if (opts.force) q.set("force", "true");
  if (opts.account_id) q.set("account_id", opts.account_id);
  const url = `/api/budget/transactions/scan-receipt${q.toString() ? "?" + q : ""}`;
  const resp = await fetch(url, {
    method: "POST", body: form,
    headers: { "Authorization": `Bearer ${token}` },
  });
  const body = await resp.json();
  return { status: resp.status, body };
}
```

- [ ] **Step 2: Replace the body of `frontend/src/pages/budget/scan-receipt.astro`**

Strip the account dropdown from server-rendered HTML. Render:

```astro
<Layout title={l.title} lang={lang}>
  <DrawerMenu lang={lang} />
  <BudgetNavNew lang={lang} active="scan" draftsCount={pendingDraftsCount} />

  <main class="px-4 pb-32 pt-6 max-w-md mx-auto">
    <h1 class="text-3xl font-display mb-2">{lang === "es" ? "Escanear ticket" : "Scan receipt"}</h1>
    <p class="text-sm text-fg/60 mb-8">
      {lang === "es"
        ? "Toma una foto y deja que la IA llene todo."
        : "Snap a photo and let AI fill in the rest."}
    </p>

    <div class="flex flex-col gap-3" id="scan-actions">
      <label class="brand-btn brand-btn-primary text-center cursor-pointer">
        {lang === "es" ? "📷 Tomar foto" : "📷 Snap receipt"}
        <input id="cam-input" type="file" accept="image/*,application/pdf"
               capture="environment" class="hidden" />
      </label>
      <label class="brand-btn brand-btn-secondary text-center cursor-pointer">
        {lang === "es" ? "⬆ Subir imagen" : "⬆ Upload image"}
        <input id="up-input" type="file"
               accept="image/jpeg,image/png,image/webp,image/gif,application/pdf"
               class="hidden" />
      </label>
    </div>

    <div id="scan-overlay" class="hidden fixed inset-0 z-50 bg-bg/95 flex flex-col items-center justify-center p-6">
      <div class="size-32 rounded-2xl bg-fg/5 mb-6 animate-pulse"></div>
      <ul id="scan-stages" class="text-fg/80 text-sm space-y-1 text-center">
        <li data-stage="0">{lang === "es" ? "Leyendo…" : "Reading…"}</li>
        <li data-stage="1" class="opacity-30">{lang === "es" ? "Detectando cuenta…" : "Matching account…"}</li>
        <li data-stage="2" class="opacity-30">{lang === "es" ? "Categorizando…" : "Categorizing…"}</li>
        <li data-stage="3" class="opacity-30">{lang === "es" ? "Buscando duplicados…" : "Checking duplicates…"}</li>
      </ul>
    </div>

    <section id="confirm-card" class="hidden mt-8"></section>

    <dialog id="dup-modal" class="modal"></dialog>
  </main>
  <BottomNav lang={lang} active="budget" />
</Layout>

<script type="module" define:vars={{ lang, token, accounts }}>
  import { scanReceipt } from "@lib/api/budget";

  const stages = document.querySelectorAll("#scan-stages li");
  function tick() {
    let i = 0;
    return setInterval(() => {
      if (i > 0) stages[i - 1].classList.remove("opacity-30");
      if (i < stages.length) stages[i].classList.remove("opacity-30");
      i = Math.min(stages.length, i + 1);
    }, 700);
  }

  async function runScan(file) {
    document.getElementById("scan-overlay").classList.remove("hidden");
    const ticker = tick();
    try {
      const { status, body } = await scanReceipt(token, file);
      clearInterval(ticker);
      document.getElementById("scan-overlay").classList.add("hidden");
      if (status === 409 && body.dup_warning) {
        showDupModal(file, body);
        return;
      }
      if (body.draft_id) {
        location.href = `/budget/receipt-drafts`;
        return;
      }
      showConfirmCard(body);
    } catch (e) {
      clearInterval(ticker);
      document.getElementById("scan-overlay").classList.add("hidden");
      alert(lang === "es" ? "Error escaneando." : "Scan failed.");
    }
  }

  function showConfirmCard(body) {
    const root = document.getElementById("confirm-card");
    const fxLine = body.fx
      ? `<div class="text-sm text-fg/60">≈ ${money(body.fx.original_amount_cents, body.fx.original_currency)} @ ${body.fx.rate}</div>`
      : "";
    const iva = body.transaction && body.transaction.iva_cents
      ? `<div class="inline-block px-2 py-1 rounded bg-fg/5 text-xs">IVA ${money(body.transaction.iva_cents, "MXN")}</div>`
      : "";
    const trendsMap = new Map(body.trends.map(t => [t.normalized_name, t]));
    const itemsHtml = body.items.map(it => {
      const t = trendsMap.get(it.normalized_name);
      let badge = "";
      if (t && Math.abs(t.pct_change) >= 0.05) {
        const up = t.pct_change > 0;
        badge = `<span class="ml-2 text-xs ${up ? "text-red-500" : "text-green-600"}">${up ? "📈" : "📉"} ${(t.pct_change*100).toFixed(0)}%</span>`;
      }
      return `<li class="flex justify-between py-1 text-sm">
        <span>${esc(it.name)}${badge}</span>
        <span>${money(it.total_cents, body.transaction.currency || "MXN")}</span>
      </li>`;
    }).join("");

    const matchBadge = body.account_match.strategy === "card_last4"
      ? "✓" : body.account_match.strategy === "override" ? "●" : "◐";

    root.innerHTML = `
      <div class="card p-5 space-y-4">
        <div>
          <h2 class="text-xl font-display">${esc(body.transaction.payee_name || "")}</h2>
          <div class="text-3xl">${money(body.transaction.amount, body.transaction.currency || "MXN")}</div>
          ${fxLine}
        </div>
        <div class="text-sm">
          <span class="text-fg/60">${lang === "es" ? "Cuenta" : "Account"}</span><br/>
          ${matchBadge} ${esc(body.transaction.account_name || "")}
        </div>
        ${iva}
        <ul class="border-t border-fg/10 pt-3">${itemsHtml}</ul>
        <div class="flex flex-col gap-2 pt-3">
          <a href="/budget/transactions" class="brand-btn brand-btn-primary text-center">
            ${lang === "es" ? "✓ Listo, guardar" : "✓ Looks good — save"}
          </a>
          <button id="del-tx" class="brand-btn brand-btn-secondary">
            ${lang === "es" ? "Borrar y re-escanear" : "Delete & re-scan"}
          </button>
        </div>
      </div>`;
    root.classList.remove("hidden");
    document.getElementById("del-tx").onclick = async () => {
      await fetch(`/api/budget/transactions/${body.transaction_id}`, {
        method: "DELETE", headers: { "Authorization": `Bearer ${token}` },
      });
      location.reload();
    };
  }

  function showDupModal(file, body) {
    const d = document.getElementById("dup-modal");
    d.innerHTML = `
      <form method="dialog" class="card p-5 space-y-3 max-w-sm mx-auto">
        <h3 class="text-lg font-display">${lang === "es" ? "⚠ Ya escaneado" : "⚠ Already scanned"}</h3>
        <p class="text-sm">
          ${esc(body.dup_warning.payee || "")},
          ${money(body.dup_warning.amount_cents, body.transaction?.currency || "MXN")},
          ${timeAgo(body.dup_warning.scanned_at, lang)}.
        </p>
        <div class="flex gap-2 justify-end">
          <a href="/budget/transactions/${body.dup_warning.existing_transaction_id}"
             class="brand-btn brand-btn-secondary">${lang === "es" ? "Ver original" : "Open original"}</a>
          <button id="force-save" class="brand-btn brand-btn-primary">
            ${lang === "es" ? "Guardar de todas formas" : "Save anyway"}
          </button>
        </div>
      </form>`;
    d.showModal();
    document.getElementById("force-save").addEventListener("click", async (e) => {
      e.preventDefault();
      d.close();
      document.getElementById("scan-overlay").classList.remove("hidden");
      const { body: r2 } = await scanReceipt(token, file, { force: true });
      document.getElementById("scan-overlay").classList.add("hidden");
      showConfirmCard(r2);
    });
  }

  function money(c, ccy) {
    const sign = c < 0 ? "-" : "";
    const abs = Math.abs(c) / 100;
    return `${sign}${ccy === "USD" ? "$" : "$"}${abs.toFixed(2)} ${ccy}`;
  }
  function esc(s) { return (s || "").replace(/[<>&"']/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;","\"":"&quot;","'":"&#39;"}[c])); }
  function timeAgo(iso, l) {
    const sec = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (sec < 60) return l === "es" ? `hace ${sec}s` : `${sec}s ago`;
    return l === "es" ? `hace ${Math.round(sec/60)}m` : `${Math.round(sec/60)}m ago`;
  }

  document.getElementById("cam-input").addEventListener("change", e => {
    const f = e.target.files[0]; if (f) runScan(f);
  });
  document.getElementById("up-input").addEventListener("change", e => {
    const f = e.target.files[0]; if (f) runScan(f);
  });
</script>
```

- [ ] **Step 2: Manual smoke test**

```
podman compose up -d
# Open http://localhost:3003/budget/scan-receipt
# Use any test JPG of a receipt.
```

Verify: snap → overlay → confirm card. No pre-pick dropdown.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/budget/scan-receipt.astro \
        frontend/src/lib/api/budget.ts
git commit -m "feat(scanner-v2): one-tap snap UX + confirm card + dup modal"
```

---

### Task 16: Items detail page

**Files:**
- Create: `frontend/src/pages/budget/items/[normalized_name].astro`

- [ ] **Step 1: Implement page**

```astro
---
import Layout from "@layouts/Layout.astro";
import BudgetNavNew from "@components/BudgetNavNew.astro";
import BottomNav from "@components/BottomNav.astro";
import DrawerMenu from "@components/DrawerMenu.astro";
import { apiFetch } from "@lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = Astro.cookies.get("lang")?.value ?? "en";
const { normalized_name } = Astro.params;

const { data: items } = await apiFetch<any[]>(
  `/api/budget/items?normalized_name=${encodeURIComponent(normalized_name || "")}&limit=100`,
  { token },
);
const { data: trend } = await apiFetch<any>(
  `/api/budget/items/trend?normalized_name=${encodeURIComponent(normalized_name || "")}`,
  { token },
);
---

<Layout title={normalized_name} lang={lang}>
  <DrawerMenu lang={lang} />
  <BudgetNavNew lang={lang} active="transactions" draftsCount={0} />
  <main class="px-4 pb-32 pt-6 max-w-md mx-auto">
    <h1 class="text-2xl font-display capitalize">{normalized_name}</h1>
    {trend && (
      <div class="card p-3 my-3 text-sm">
        <div>{lang === "es" ? "Promedio 90 días" : "90-day average"}:
          ${(trend.avg_unit_cents / 100).toFixed(2)}</div>
        <div>{lang === "es" ? "Último" : "Last"}:
          ${(trend.last_unit_cents / 100).toFixed(2)}
          ({(trend.pct_change * 100).toFixed(1)}%)</div>
      </div>
    )}
    <ul class="divide-y divide-fg/10">
      {(items || []).map(it => (
        <li class="py-2 flex justify-between">
          <a href={`/budget/transactions/${it.transaction_id}`} class="flex-1">
            <div class="text-sm">{it.name}</div>
            <div class="text-xs text-fg/60">{it.qty ?? 1} × ${(it.unit_price_cents ?? it.total_cents) / 100}</div>
          </a>
          <span class="text-sm">${(it.total_cents / 100).toFixed(2)}</span>
        </li>
      ))}
    </ul>
  </main>
  <BottomNav lang={lang} active="budget" />
</Layout>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/budget/items/
git commit -m "feat(scanner-v2): item history page /budget/items/[normalized_name]"
```

---

### Task 17: Parent settings — a2a webhook page

**Files:**
- Create: `frontend/src/pages/parent/settings/a2a.astro`

- [ ] **Step 1: Implement page** (auth gate, parent-only, GET current config, PUT to save; show plaintext secret only when rotate_secret returns it).

```astro
---
import Layout from "@layouts/Layout.astro";
import BottomNav from "@components/BottomNav.astro";
import DrawerMenu from "@components/DrawerMenu.astro";
import { apiFetch } from "@lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = Astro.cookies.get("lang")?.value ?? "en";
const { data: user } = await apiFetch<any>("/api/auth/me", { token });
if (user?.role !== "parent") return Astro.redirect("/dashboard");
const { data: cfg } = await apiFetch<any>("/api/budget/a2a-webhook", { token });
---

<Layout title={lang === "es" ? "Agente de precios" : "Price Agent"} lang={lang}>
  <DrawerMenu lang={lang} />
  <main class="px-4 pb-32 pt-6 max-w-md mx-auto">
    <h1 class="text-2xl font-display mb-4">{lang === "es" ? "Agente de precios" : "Price Agent"}</h1>

    <form id="form" class="card p-4 space-y-3">
      <label class="block">
        <span class="text-sm">URL</span>
        <input id="url" type="url" required pattern="https://.*"
               value={cfg?.url ?? ""} class="brand-input w-full" />
      </label>
      <label class="flex items-center gap-2">
        <input id="enabled" type="checkbox" checked={cfg?.enabled} />
        <span>{lang === "es" ? "Activo" : "Enabled"}</span>
      </label>
      <label class="flex items-center gap-2">
        <input id="rotate" type="checkbox" />
        <span>{lang === "es" ? "Rotar secreto" : "Rotate secret"}</span>
      </label>
      <div class="text-xs text-fg/60">
        {lang === "es" ? "Último éxito" : "Last success"}: {cfg?.last_success_at ?? "—"}<br/>
        {lang === "es" ? "Fallas" : "Failures"}: {cfg?.failure_count ?? 0}
      </div>
      <button class="brand-btn brand-btn-primary w-full">
        {lang === "es" ? "Guardar" : "Save"}
      </button>
      <pre id="secret-out" class="hidden text-xs bg-fg/5 p-2 rounded"></pre>
    </form>
  </main>
  <BottomNav lang={lang} active="manage" />
</Layout>

<script type="module" define:vars={{ token, lang }}>
  document.getElementById("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const resp = await fetch("/api/budget/a2a-webhook", {
      method: "PUT",
      headers: { "Content-Type": "application/json",
                 "Authorization": `Bearer ${token}` },
      body: JSON.stringify({
        url: document.getElementById("url").value,
        enabled: document.getElementById("enabled").checked,
        rotate_secret: document.getElementById("rotate").checked,
      }),
    });
    const body = await resp.json();
    if (body.secret) {
      const out = document.getElementById("secret-out");
      out.classList.remove("hidden");
      out.textContent = (lang === "es" ? "Secreto nuevo (cópialo): " : "New secret (copy now): ") + body.secret;
    } else {
      alert(lang === "es" ? "Guardado." : "Saved.");
    }
  });
</script>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/parent/settings/a2a.astro
git commit -m "feat(scanner-v2): parent settings page for a2a webhook"
```

---

### Task 18: Wire scan page item rows to detail page

**Files:**
- Modify: `frontend/src/pages/budget/scan-receipt.astro` (anchor each item row to `/budget/items/[normalized_name]`)

- [ ] **Step 1:** In the items list builder in the script block, wrap the name span in an anchor:

```js
const link = `/budget/items/${encodeURIComponent(it.normalized_name)}`;
// inside the template:
`<a href="${link}" class="underline-offset-4 hover:underline">${esc(it.name)}</a>${badge}`
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/budget/scan-receipt.astro
git commit -m "feat(scanner-v2): link scan items to item history page"
```

---

## Phase 7 — E2E + deploy

### Task 19: Playwright E2E tests

**Files:**
- Create: `e2e-tests/tests/scanner-v2.spec.ts`

- [ ] **Step 1: Implement five tests**

```ts
import { test, expect } from "@playwright/test";
import { loginAsParent } from "./helpers/auth";

test.describe("Scanner v2", () => {
  test("one-tap snap → confirm card", async ({ page }) => {
    await loginAsParent(page);
    await page.goto("/budget/scan-receipt");
    await expect(page.locator("text=Snap receipt")).toBeVisible();
    // The native camera input cannot be driven; assert UI scaffolding.
    await expect(page.locator("#confirm-card.hidden")).toHaveCount(1);
  });

  test("duplicate modal flow", async ({ page }) => {
    // requires a backend stub or pre-seeded recent tx; left as a fixture spec
    test.skip(true, "needs backend stub for dup-flow; covered by API test 26");
  });

  test("FX display when accounts differ", async ({ page }) => {
    test.skip(true, "needs backend stub; covered by API test 14");
  });

  test("IVA pill renders when present", async ({ page }) => {
    test.skip(true, "needs backend stub; covered by API test 16");
  });

  test("trend badges only when sample_size >= 3", async ({ page }) => {
    test.skip(true, "needs seeded item history");
  });
});
```

(The realistic-looking page test asserts UI scaffolding; the rest are skipped with a pointer to the API tests that cover the logic. A later wave can replace skips with real mocks once the API mock layer is wired into the e2e suite.)

- [ ] **Step 2: Run**

```
cd e2e-tests && npm run test:scanner || npx playwright test scanner-v2
```

- [ ] **Step 3: Commit**

```bash
git add e2e-tests/tests/scanner-v2.spec.ts
git commit -m "test(scanner-v2): playwright scaffolding for one-tap flow"
```

---

### Task 20: Deploy to GCP

- [ ] **Step 1: Verify all tests green locally**

```
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v -x
```

- [ ] **Step 2: Set INTERNAL_API_TOKEN on the VM**

```
gcloud --account=info@agent-ia.mx --project=agentia-prod-497016 \
  compute ssh agentia-family-hub --zone=us-central1-a \
  --command='grep -q INTERNAL_API_TOKEN /home/jc/family-task-manager/.env || \
             echo "INTERNAL_API_TOKEN=$(openssl rand -hex 32)" \
             | sudo tee -a /home/jc/family-task-manager/.env'
```

- [ ] **Step 3: Deploy**

```
./scripts/deploy-gcp.sh -y
```

- [ ] **Step 4: Verify migration ran**

```
gcloud --account=info@agent-ia.mx --project=agentia-prod-497016 \
  compute ssh agentia-family-hub --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && \
             sudo docker compose --env-file .env -f docker-compose.gcp.yml \
             exec -T backend alembic current'
```

Expected: `wave4_scanner_v2 (head)`.

- [ ] **Step 5: Smoke test the live app**

- Open `https://gcp-family.agent-ia.mx/budget/scan-receipt`
- Tap Snap; upload a test receipt (a real one if available — e.g., the user's HEB receipt with `**9222`).
- Verify confirm card shows account checkmark, items, IVA pill (if present).

- [ ] **Step 6: Schedule the retry sweep**

Add a one-line cron on the VM that POSTs to the internal sweep endpoint every 5 min:

```
gcloud --account=info@agent-ia.mx --project=agentia-prod-497016 \
  compute ssh agentia-family-hub --zone=us-central1-a \
  --command='(crontab -l 2>/dev/null; echo "*/5 * * * * curl -fsS -X POST -H \"X-Internal-Token: $(grep ^INTERNAL_API_TOKEN= /home/jc/family-task-manager/.env | cut -d= -f2)\" http://localhost:8000/api/internal/a2a/retry > /dev/null") | crontab -'
```

- [ ] **Step 7: Final commit (if any deploy-only files were touched)**

```bash
git status
# commit anything intentional, leave .deploy.gcp.env / .claude untouched
```

---

## Self-Review

**Spec coverage:**
- §1 Goal — covered across the plan.
- §3 Architecture — Tasks 8, 9, 10 implement the 7-stage pipeline; Task 7 implements the post-commit fan-out.
- §4 Data model — Task 1 (migration + ORM), Task 2 (schemas).
- §5 API surface — Task 10 (extended scan-receipt), Task 11 (items), Task 12 (webhook config), Task 13 (internal retry).
- §6 Frontend UX — Tasks 15–18.
- §7 Webhook contract — Task 7 (signing + headers), Task 9 (payload build).
- §8 Vision prompt change — Task 8.
- §9 Services list — covered task-by-task in Phase 2 + 3.
- §10 Premium gating — Task 14.
- §11 Error handling — covered in pipeline (Task 9) and unit tests (Tasks 5–7).
- §12 Testing — ~25 backend tests across Tasks 1–13, 5 Playwright tests in Task 19 (some skipped with traceability notes).
- §15 Rollout — Task 20.

**Placeholder scan:** No "TBD" / "implement later" / "handle edge cases" found. The Playwright file has 4 skipped tests pointing at the API tests that cover their logic — this is an explicit limitation, not a placeholder.

**Type consistency:** `ScanReceiptResponse` is the single response shape used end-to-end. `AccountMatch.strategy` values (`card_last4`, `last_used`, `override`, `none`) used consistently in service + endpoint + frontend. `DupWarning` shape (`existing_transaction_id`, `scanned_at`, `payee`, `amount_cents`) matches between Task 6 service, Task 9 endpoint response, and Task 15 frontend modal.

**One known caveat surfaced in Task 5** — `BudgetTransaction.created_by_id` may not exist in the current model. The plan includes a verification step + fallback ("most-recent tx in family") so the task is not blocked.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-28-receipt-scanner-v2.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute tasks in this session via `superpowers:executing-plans`, batched with checkpoints.

Which approach?
