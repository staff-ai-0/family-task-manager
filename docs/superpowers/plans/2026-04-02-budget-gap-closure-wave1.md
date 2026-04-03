# Budget Gap Closure Wave 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 3 low-effort P0/P1 gaps: Payee Merging, Schedule End Modes, Favorite Payees

**Architecture:** Extend existing models/services/routes with new columns, methods, and endpoints. Single Alembic migration for all 3 features. Backend-only (no frontend).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL 15, pytest

**Spec:** `docs/superpowers/specs/2026-04-02-budget-gap-closure-design.md` (Wave 1 section)

---

## File Structure

**Modified files:**
- `backend/app/models/budget.py` — Add `is_favorite` to BudgetPayee; add `end_mode`, `occurrence_limit`, `occurrence_count`, `weekend_behavior` to BudgetRecurringTransaction
- `backend/app/schemas/budget.py` — Add new fields to payee and recurring transaction schemas; add `PayeeMergeRequest`
- `backend/app/services/budget/payee_service.py` — Add `merge` method
- `backend/app/services/budget/recurring_transaction_service.py` — Update `_calculate_next_occurrence` (yearly, weekend), update `post_transaction` (occurrence counting), fix existing field mapping bugs
- `backend/app/api/routes/budget/payees.py` — Add merge endpoint, favorites filter
- `backend/app/api/routes/budget/recurring_transactions.py` — Pass new fields through

**New files:**
- `backend/migrations/versions/2026_04_02_xxxx-wave1_payee_merge_schedule_modes_favorites.py` — Alembic migration
- `backend/tests/test_wave1_gap_closure.py` — Tests for all 3 features

---

### Task 1: Alembic Migration

**Files:**
- Create: `backend/migrations/versions/` (auto-generated)
- Modify: `backend/app/models/budget.py`

- [ ] **Step 1: Add new columns to BudgetPayee model**

In `backend/app/models/budget.py`, add to the `BudgetPayee` class after the `notes` field:

```python
is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

- [ ] **Step 2: Add new columns to BudgetRecurringTransaction model**

In `backend/app/models/budget.py`, add to `BudgetRecurringTransaction` after the `end_date` field:

```python
end_mode: Mapped[str] = mapped_column(
    String(20), default="never", nullable=False,
    comment="'never', 'on_date', 'after_n'"
)
occurrence_limit: Mapped[Optional[int]] = mapped_column(
    Integer, nullable=True,
    comment="Max occurrences for after_n mode"
)
occurrence_count: Mapped[int] = mapped_column(
    Integer, default=0, nullable=False,
    comment="Current count of posted occurrences"
)
weekend_behavior: Mapped[str] = mapped_column(
    String(20), default="none", nullable=False,
    comment="'none', 'before' (shift to Fri), 'after' (shift to Mon)"
)
```

- [ ] **Step 3: Generate Alembic migration**

```bash
docker exec family_app_backend alembic revision --autogenerate -m "wave1: payee favorites, schedule end modes"
```

- [ ] **Step 4: Review and apply migration**

```bash
docker exec family_app_backend alembic upgrade head
```

Verify columns exist:
```bash
docker exec family_app_db psql -U familyapp -d familyapp -c "\d budget_payees" | grep is_favorite
docker exec family_app_db psql -U familyapp -d familyapp -c "\d budget_recurring_transactions" | grep end_mode
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/budget.py backend/migrations/versions/
git commit -m "feat: add model columns for payee favorites and schedule end modes"
```

---

### Task 2: Favorite Payees (Schema + Service + Route)

**Files:**
- Modify: `backend/app/schemas/budget.py`
- Modify: `backend/app/services/budget/payee_service.py`
- Modify: `backend/app/api/routes/budget/payees.py`
- Create: `backend/tests/test_wave1_gap_closure.py`

- [ ] **Step 1: Update schemas**

In `backend/app/schemas/budget.py`, update the payee schemas:

```python
class PayeeBase(BaseModel):
    """Base payee schema"""
    name: str = Field(..., min_length=1, max_length=200, description="Payee name (e.g., 'Oxxo', 'CFE')")
    notes: Optional[str] = Field(None, description="Optional notes")
    is_favorite: bool = Field(False, description="Mark as favorite for quick access")


class PayeeUpdate(BaseModel):
    """Schema for updating a payee"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = None
    is_favorite: Optional[bool] = None
```

`PayeeCreate` inherits from `PayeeBase` so it gets `is_favorite` automatically.

Update `PayeeResponse` — it already inherits from `PayeeBase` so it gets `is_favorite` automatically.

- [ ] **Step 2: Update payee service create method**

In `backend/app/services/budget/payee_service.py`, update `create`:

```python
@classmethod
async def create(
    cls,
    db: AsyncSession,
    family_id: UUID,
    data: PayeeCreate,
) -> BudgetPayee:
    payee = BudgetPayee(
        family_id=family_id,
        name=data.name,
        notes=data.notes,
        is_favorite=data.is_favorite,
    )
    db.add(payee)
    await db.commit()
    await db.refresh(payee)
    return payee
```

- [ ] **Step 3: Add favorites filter to list route**

In `backend/app/api/routes/budget/payees.py`, update the list endpoint:

```python
from sqlalchemy import select

@router.get("/", response_model=List[PayeeResponse])
async def list_payees(
    favorites_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all payees, optionally filtered to favorites only"""
    family_id = to_uuid_required(current_user.family_id)
    if favorites_only:
        from app.models.budget import BudgetPayee
        query = (
            select(BudgetPayee)
            .where(BudgetPayee.family_id == family_id)
            .where(BudgetPayee.is_favorite == True)
            .order_by(BudgetPayee.name)
        )
        result = await db.execute(query)
        return list(result.scalars().all())
    payees = await PayeeService.list_by_family(db, family_id)
    return payees
```

- [ ] **Step 4: Write tests**

Create `backend/tests/test_wave1_gap_closure.py`:

```python
"""Tests for Wave 1 gap closure: Favorite Payees, Payee Merging, Schedule End Modes"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPayee, BudgetTransaction, BudgetAccount, BudgetRecurringTransaction
from app.models.budget import BudgetCategoryGroup, BudgetCategory
from app.services.budget.payee_service import PayeeService
from app.schemas.budget import PayeeCreate, PayeeUpdate


# ============================================================================
# FIXTURES
# ============================================================================

@pytest_asyncio.fixture
async def budget_account(db_session: AsyncSession, test_family):
    """Create a test budget account"""
    account = BudgetAccount(
        family_id=test_family.id,
        name="Test Checking",
        type="checking",
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest_asyncio.fixture
async def budget_category_group(db_session: AsyncSession, test_family):
    """Create a test category group"""
    group = BudgetCategoryGroup(
        family_id=test_family.id,
        name="Test Group",
    )
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    return group


@pytest_asyncio.fixture
async def budget_category(db_session: AsyncSession, test_family, budget_category_group):
    """Create a test category"""
    cat = BudgetCategory(
        family_id=test_family.id,
        group_id=budget_category_group.id,
        name="Test Category",
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return cat


# ============================================================================
# FAVORITE PAYEES TESTS
# ============================================================================

class TestFavoritePayees:
    @pytest.mark.asyncio
    async def test_create_payee_with_favorite(self, db_session, test_family):
        """Creating a payee with is_favorite=True persists the flag"""
        data = PayeeCreate(name="Oxxo", is_favorite=True)
        payee = await PayeeService.create(db_session, test_family.id, data)
        assert payee.is_favorite is True

    @pytest.mark.asyncio
    async def test_create_payee_default_not_favorite(self, db_session, test_family):
        """Payees default to is_favorite=False"""
        data = PayeeCreate(name="Random Store")
        payee = await PayeeService.create(db_session, test_family.id, data)
        assert payee.is_favorite is False

    @pytest.mark.asyncio
    async def test_update_payee_favorite_flag(self, db_session, test_family):
        """Can toggle is_favorite via update"""
        data = PayeeCreate(name="Walmart")
        payee = await PayeeService.create(db_session, test_family.id, data)
        assert payee.is_favorite is False

        updated = await PayeeService.update(
            db_session, payee.id, test_family.id,
            PayeeUpdate(is_favorite=True),
        )
        assert updated.is_favorite is True
```

- [ ] **Step 5: Run tests**

```bash
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_wave1_gap_closure.py -v -x
```

Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/budget.py backend/app/services/budget/payee_service.py backend/app/api/routes/budget/payees.py backend/tests/test_wave1_gap_closure.py
git commit -m "feat: add favorite payees with is_favorite flag and filter"
```

---

### Task 3: Payee Merging (Service + Route + Tests)

**Files:**
- Modify: `backend/app/schemas/budget.py`
- Modify: `backend/app/services/budget/payee_service.py`
- Modify: `backend/app/api/routes/budget/payees.py`
- Modify: `backend/tests/test_wave1_gap_closure.py`

- [ ] **Step 1: Add merge schema**

In `backend/app/schemas/budget.py`, after the `PayeeResponse` class:

```python
class PayeeMergeRequest(BaseModel):
    """Request to merge multiple payees into one target"""
    target_id: UUID = Field(..., description="Payee to keep (merge target)")
    source_ids: List[UUID] = Field(..., min_length=1, description="Payees to merge into target (will be deleted)")
```

Add `PayeeMergeRequest` to the imports as needed (it uses `List` and `UUID` already imported).

- [ ] **Step 2: Add merge method to service**

In `backend/app/services/budget/payee_service.py`, add:

```python
from sqlalchemy import update
from app.models.budget import BudgetPayee, BudgetTransaction, BudgetRecurringTransaction, BudgetCategorizationRule
from app.core.exceptions import NotFoundException, ValidationException

class PayeeService(BaseFamilyService[BudgetPayee]):
    # ... existing methods ...

    @classmethod
    async def merge(
        cls,
        db: AsyncSession,
        family_id: UUID,
        target_id: UUID,
        source_ids: list[UUID],
    ) -> BudgetPayee:
        """
        Merge source payees into target. Updates all FK references then deletes sources.
        """
        if target_id in source_ids:
            raise ValidationException("Target payee cannot be in source list")

        # Verify target exists
        target = await cls.get_by_id(db, target_id, family_id)

        # Verify all sources exist and belong to family
        for source_id in source_ids:
            await cls.get_by_id(db, source_id, family_id)

        # Update transactions pointing to source payees
        await db.execute(
            update(BudgetTransaction)
            .where(BudgetTransaction.family_id == family_id)
            .where(BudgetTransaction.payee_id.in_(source_ids))
            .values(payee_id=target_id)
        )

        # Update recurring transactions pointing to source payees
        await db.execute(
            update(BudgetRecurringTransaction)
            .where(BudgetRecurringTransaction.family_id == family_id)
            .where(BudgetRecurringTransaction.payee_id.in_(source_ids))
            .values(payee_id=target_id)
        )

        # Delete source payees
        for source_id in source_ids:
            source = await cls.get_by_id(db, source_id, family_id)
            await db.delete(source)

        await db.commit()
        await db.refresh(target)
        return target
```

- [ ] **Step 3: Add merge endpoint**

In `backend/app/api/routes/budget/payees.py`, add:

```python
from app.schemas.budget import PayeeCreate, PayeeUpdate, PayeeResponse, PayeeMergeRequest

@router.post("/merge", response_model=PayeeResponse)
async def merge_payees(
    data: PayeeMergeRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Merge multiple payees into one target (parent only)"""
    payee = await PayeeService.merge(
        db,
        family_id=to_uuid_required(current_user.family_id),
        target_id=data.target_id,
        source_ids=data.source_ids,
    )
    return payee
```

- [ ] **Step 4: Add merge tests**

Append to `backend/tests/test_wave1_gap_closure.py`:

```python
from app.schemas.budget import PayeeMergeRequest
from datetime import date


class TestPayeeMerging:
    @pytest.mark.asyncio
    async def test_merge_updates_transactions(self, db_session, test_family, budget_account):
        """Merging payees moves all transactions to target"""
        target = await PayeeService.create(db_session, test_family.id, PayeeCreate(name="Walmart"))
        source1 = await PayeeService.create(db_session, test_family.id, PayeeCreate(name="WALMART MX"))
        source2 = await PayeeService.create(db_session, test_family.id, PayeeCreate(name="WAL-MART"))

        # Create transactions linked to source payees
        tx1 = BudgetTransaction(
            family_id=test_family.id, account_id=budget_account.id,
            date=date(2026, 4, 1), amount=-10000, payee_id=source1.id,
        )
        tx2 = BudgetTransaction(
            family_id=test_family.id, account_id=budget_account.id,
            date=date(2026, 4, 2), amount=-20000, payee_id=source2.id,
        )
        db_session.add_all([tx1, tx2])
        await db_session.commit()

        result = await PayeeService.merge(
            db_session, test_family.id, target.id, [source1.id, source2.id]
        )
        assert result.id == target.id

        # Verify transactions now point to target
        await db_session.refresh(tx1)
        await db_session.refresh(tx2)
        assert tx1.payee_id == target.id
        assert tx2.payee_id == target.id

    @pytest.mark.asyncio
    async def test_merge_deletes_sources(self, db_session, test_family):
        """Source payees are deleted after merge"""
        target = await PayeeService.create(db_session, test_family.id, PayeeCreate(name="Target"))
        source = await PayeeService.create(db_session, test_family.id, PayeeCreate(name="Source"))

        await PayeeService.merge(db_session, test_family.id, target.id, [source.id])

        from app.core.exceptions import NotFoundException
        with pytest.raises(NotFoundException):
            await PayeeService.get_by_id(db_session, source.id, test_family.id)

    @pytest.mark.asyncio
    async def test_merge_target_in_sources_raises(self, db_session, test_family):
        """Cannot merge a payee into itself"""
        payee = await PayeeService.create(db_session, test_family.id, PayeeCreate(name="Self"))

        from app.core.exceptions import ValidationException
        with pytest.raises(ValidationException):
            await PayeeService.merge(db_session, test_family.id, payee.id, [payee.id])

    @pytest.mark.asyncio
    async def test_merge_updates_recurring_transactions(self, db_session, test_family, budget_account):
        """Merging payees updates recurring transaction templates too"""
        target = await PayeeService.create(db_session, test_family.id, PayeeCreate(name="CFE"))
        source = await PayeeService.create(db_session, test_family.id, PayeeCreate(name="CFE SUMINISTRA"))

        recurring = BudgetRecurringTransaction(
            family_id=test_family.id, account_id=budget_account.id,
            name="Electric Bill", amount=-150000, payee_id=source.id,
            recurrence_type="monthly_dayofmonth", start_date=date(2026, 1, 1),
        )
        db_session.add(recurring)
        await db_session.commit()

        await PayeeService.merge(db_session, test_family.id, target.id, [source.id])

        await db_session.refresh(recurring)
        assert recurring.payee_id == target.id
```

- [ ] **Step 5: Run tests**

```bash
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_wave1_gap_closure.py -v -x
```

Expected: 7 tests PASS (3 favorites + 4 merge)

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/budget.py backend/app/services/budget/payee_service.py backend/app/api/routes/budget/payees.py backend/tests/test_wave1_gap_closure.py
git commit -m "feat: add payee merging with FK cascade updates"
```

---

### Task 4: Schedule End Modes (Schema + Service + Tests)

**Files:**
- Modify: `backend/app/schemas/budget.py`
- Modify: `backend/app/services/budget/recurring_transaction_service.py`
- Modify: `backend/tests/test_wave1_gap_closure.py`

- [ ] **Step 1: Update recurring transaction schemas**

In `backend/app/schemas/budget.py`, update `RecurringTransactionBase`:

```python
class RecurringTransactionBase(BaseModel):
    """Base recurring transaction schema"""
    account_id: UUID = Field(..., description="Account ID")
    category_id: Optional[UUID] = Field(None, description="Category ID (optional)")
    payee_id: Optional[UUID] = Field(None, description="Payee ID (optional)")
    name: str = Field(..., min_length=1, max_length=255, description="Template name (e.g., 'Monthly Rent')")
    description: Optional[str] = Field(None, description="Optional description")
    amount: int = Field(..., description="Amount in cents (negative=expense, positive=income)")
    recurrence_type: str = Field(
        ...,
        description="'daily', 'weekly', 'monthly_dayofmonth', 'monthly_dayofweek', 'yearly'"
    )
    recurrence_interval: int = Field(1, ge=1, le=52, description="Repeat every N periods")
    recurrence_pattern: Optional[dict] = Field(None, description="Pattern-specific configuration (JSON)")
    start_date: DateType = Field(..., description="First occurrence date")
    end_date: Optional[DateType] = Field(None, description="Last occurrence date (used with end_mode='on_date')")
    end_mode: str = Field("never", description="'never', 'on_date', 'after_n'")
    occurrence_limit: Optional[int] = Field(None, ge=1, description="Max occurrences (for end_mode='after_n')")
    weekend_behavior: str = Field("none", description="'none', 'before' (shift to Fri), 'after' (shift to Mon)")
    is_active: bool = Field(True, description="Is template currently active?")
```

Update `RecurringTransactionUpdate` — add the new optional fields:

```python
class RecurringTransactionUpdate(BaseModel):
    # ... existing fields ...
    end_mode: Optional[str] = None
    occurrence_limit: Optional[int] = Field(None, ge=1)
    weekend_behavior: Optional[str] = None
```

Update `RecurringTransactionResponse` — add `occurrence_count`:

```python
class RecurringTransactionResponse(RecurringTransactionBase):
    """Recurring transaction response with metadata"""
    id: UUID
    family_id: UUID
    last_generated_date: Optional[DateType] = None
    next_due_date: Optional[DateType] = None
    occurrence_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Update _calculate_next_occurrence for yearly + weekend**

In `backend/app/services/budget/recurring_transaction_service.py`, update `_calculate_next_occurrence`:

Add `weekend_behavior: str = "none"` parameter, add `end_mode: str = "never"`, `occurrence_limit: Optional[int] = None`, `occurrence_count: int = 0` parameters.

Replace the full method:

```python
@classmethod
def _calculate_next_occurrence(
    cls,
    start_date: date,
    recurrence_type: str,
    recurrence_interval: int,
    recurrence_pattern: Optional[dict],
    end_date: Optional[date],
    from_date: Optional[date] = None,
    weekend_behavior: str = "none",
    end_mode: str = "never",
    occurrence_limit: Optional[int] = None,
    occurrence_count: int = 0,
) -> Optional[date]:
    """Calculate the next occurrence date for a recurring transaction."""
    if from_date is None:
        from_date = date.today()

    # If start date is in future, return start date (with weekend adjust)
    if start_date > from_date:
        return cls._adjust_weekend(start_date, weekend_behavior)

    # Check if already expired by end_date
    if end_mode == "on_date" and end_date and from_date > end_date:
        return None

    # Check if occurrence limit reached
    if end_mode == "after_n" and occurrence_limit and occurrence_count >= occurrence_limit:
        return None

    next_date = None

    if recurrence_type == "daily":
        days_since_start = (from_date - start_date).days
        intervals_passed = days_since_start // recurrence_interval
        next_date = start_date + timedelta(days=(intervals_passed + 1) * recurrence_interval)

    elif recurrence_type == "weekly":
        if not recurrence_pattern or "days" not in recurrence_pattern:
            target_days = [start_date.weekday()]
        else:
            target_days = recurrence_pattern["days"]

        current_check = from_date
        for _ in range(14):
            if current_check.weekday() in target_days and current_check >= start_date:
                weeks_diff = (current_check - start_date).days // 7
                if weeks_diff % recurrence_interval == 0 and current_check > from_date:
                    next_date = current_check
                    break
            current_check += timedelta(days=1)

    elif recurrence_type == "monthly_dayofmonth":
        if not recurrence_pattern or "day" not in recurrence_pattern:
            target_day = start_date.day
        else:
            target_day = recurrence_pattern["day"]

        current_date = from_date.replace(day=1)
        months_offset = 0
        while months_offset < 24:
            target_date = (current_date + relativedelta(months=months_offset)).replace(day=1)
            try:
                target_date = target_date.replace(day=target_day)
            except ValueError:
                target_date = (target_date + relativedelta(months=1)) - timedelta(days=1)

            if target_date > from_date:
                months_diff = (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)
                if months_diff % recurrence_interval == 0:
                    next_date = target_date
                    break
            months_offset += recurrence_interval

    elif recurrence_type == "monthly_dayofweek":
        if not recurrence_pattern or "week" not in recurrence_pattern or "day" not in recurrence_pattern:
            pattern_week = (start_date.day - 1) // 7
            pattern_day = start_date.weekday()
        else:
            pattern_week = recurrence_pattern["week"]
            pattern_day = recurrence_pattern["day"]

        months_offset = 0
        while months_offset < 24:
            check_date = from_date + relativedelta(months=months_offset)
            check_date = check_date.replace(day=1)
            current_day = check_date.weekday()
            days_until_target = (pattern_day - current_day) % 7
            target_date = check_date + timedelta(days=days_until_target)

            if pattern_week == -1:
                target_date = (target_date + relativedelta(months=1)).replace(day=1) - timedelta(days=1)
                while target_date.weekday() != pattern_day:
                    target_date -= timedelta(days=1)
            else:
                target_date += timedelta(weeks=pattern_week)

            if target_date > from_date:
                months_diff = (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)
                if months_diff % recurrence_interval == 0:
                    next_date = target_date
                    break
            months_offset += recurrence_interval

    elif recurrence_type == "yearly":
        # Yearly: same month/day, every N years
        years_since = from_date.year - start_date.year
        intervals_passed = years_since // recurrence_interval
        for attempt in range(intervals_passed, intervals_passed + 3):
            try:
                candidate = start_date.replace(year=start_date.year + (attempt + 1) * recurrence_interval)
            except ValueError:
                # Feb 29 on non-leap year -> use Feb 28
                candidate = date(
                    start_date.year + (attempt + 1) * recurrence_interval,
                    start_date.month,
                    28,
                )
            if candidate > from_date:
                next_date = candidate
                break

    # Check end_date constraint
    if next_date and end_mode == "on_date" and end_date and next_date > end_date:
        return None

    # Apply weekend adjustment
    if next_date:
        next_date = cls._adjust_weekend(next_date, weekend_behavior)

    return next_date

@classmethod
def _adjust_weekend(cls, d: date, behavior: str) -> date:
    """Shift weekend dates to Friday (before) or Monday (after)."""
    if behavior == "none":
        return d
    weekday = d.weekday()  # 0=Mon, 5=Sat, 6=Sun
    if weekday == 5:  # Saturday
        return d - timedelta(days=1) if behavior == "before" else d + timedelta(days=2)
    elif weekday == 6:  # Sunday
        return d - timedelta(days=2) if behavior == "before" else d + timedelta(days=1)
    return d
```

- [ ] **Step 3: Update create/update/post methods to pass new fields**

In `recurring_transaction_service.py`, update `create`:

```python
recurring_tx = BudgetRecurringTransaction(
    family_id=family_id,
    account_id=data.account_id,
    category_id=data.category_id,
    payee_id=data.payee_id,
    name=data.name,
    description=data.description,
    amount=data.amount,
    recurrence_type=data.recurrence_type,
    recurrence_interval=data.recurrence_interval,
    recurrence_pattern=data.recurrence_pattern,
    start_date=data.start_date,
    end_date=data.end_date,
    end_mode=data.end_mode,
    occurrence_limit=data.occurrence_limit,
    weekend_behavior=data.weekend_behavior,
    is_active=data.is_active,
    next_due_date=next_due_date,
)
```

Update `_calculate_next_occurrence` call in `create` to pass new params:

```python
next_due_date = cls._calculate_next_occurrence(
    data.start_date,
    data.recurrence_type,
    data.recurrence_interval,
    data.recurrence_pattern,
    data.end_date,
    weekend_behavior=data.weekend_behavior,
    end_mode=data.end_mode,
    occurrence_limit=data.occurrence_limit,
)
```

Update all other `_calculate_next_occurrence` calls in `update` and `post_transaction` to pass the new fields from the model instance.

- [ ] **Step 4: Fix post_transaction field mapping bug and add occurrence counting**

The existing `post_transaction` has bugs: it references `transaction_date` and `description` which don't exist on `BudgetTransaction` model. Fix and add occurrence counting:

```python
@classmethod
async def post_transaction(
    cls,
    db: AsyncSession,
    recurring_id: UUID,
    family_id: UUID,
    transaction_date: Optional[date] = None,
) -> BudgetTransaction:
    if transaction_date is None:
        transaction_date = date.today()

    recurring = await cls.get_by_id(db, recurring_id, family_id)

    # Check if occurrence limit reached
    if (recurring.end_mode == "after_n"
        and recurring.occurrence_limit
        and recurring.occurrence_count >= recurring.occurrence_limit):
        raise ValidationException("Occurrence limit reached for this recurring transaction")

    # Create transaction from template (use correct model field names)
    transaction = BudgetTransaction(
        family_id=family_id,
        account_id=recurring.account_id,
        category_id=recurring.category_id,
        payee_id=recurring.payee_id,
        amount=recurring.amount,
        date=transaction_date,
        notes=recurring.description or recurring.name,
        cleared=False,
        reconciled=False,
    )
    db.add(transaction)

    # Increment occurrence count
    recurring.occurrence_count += 1
    recurring.last_generated_date = transaction_date

    # Calculate next due date
    recurring.next_due_date = cls._calculate_next_occurrence(
        recurring.start_date,
        recurring.recurrence_type,
        recurring.recurrence_interval,
        recurring.recurrence_pattern,
        recurring.end_date,
        from_date=transaction_date,
        weekend_behavior=recurring.weekend_behavior,
        end_mode=recurring.end_mode,
        occurrence_limit=recurring.occurrence_limit,
        occurrence_count=recurring.occurrence_count,
    )

    # Auto-deactivate if limit reached
    if (recurring.end_mode == "after_n"
        and recurring.occurrence_limit
        and recurring.occurrence_count >= recurring.occurrence_limit):
        recurring.is_active = False
        recurring.next_due_date = None

    await db.commit()
    await db.refresh(transaction)
    return transaction
```

Add the import at the top of the file:
```python
from app.core.exceptions import NotFoundException, ValidationException
```

- [ ] **Step 5: Add schedule end mode tests**

Append to `backend/tests/test_wave1_gap_closure.py`:

```python
from app.services.budget.recurring_transaction_service import RecurringTransactionService
from app.schemas.budget import RecurringTransactionCreate


class TestScheduleEndModes:
    def test_yearly_recurrence(self):
        """Yearly recurrence calculates next year correctly"""
        next_date = RecurringTransactionService._calculate_next_occurrence(
            start_date=date(2025, 6, 15),
            recurrence_type="yearly",
            recurrence_interval=1,
            recurrence_pattern=None,
            end_date=None,
            from_date=date(2026, 4, 1),
        )
        assert next_date == date(2027, 6, 15)

    def test_yearly_every_2_years(self):
        """Yearly recurrence with interval=2 skips a year"""
        next_date = RecurringTransactionService._calculate_next_occurrence(
            start_date=date(2024, 3, 1),
            recurrence_type="yearly",
            recurrence_interval=2,
            recurrence_pattern=None,
            end_date=None,
            from_date=date(2026, 4, 1),
        )
        assert next_date == date(2028, 3, 1)

    def test_after_n_occurrences_returns_none_when_exhausted(self):
        """After N occurrences mode returns None when count >= limit"""
        next_date = RecurringTransactionService._calculate_next_occurrence(
            start_date=date(2026, 1, 1),
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 1},
            end_date=None,
            from_date=date(2026, 4, 1),
            end_mode="after_n",
            occurrence_limit=3,
            occurrence_count=3,
        )
        assert next_date is None

    def test_after_n_occurrences_returns_date_when_under_limit(self):
        """After N occurrences mode returns date when count < limit"""
        next_date = RecurringTransactionService._calculate_next_occurrence(
            start_date=date(2026, 1, 1),
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 1},
            end_date=None,
            from_date=date(2026, 4, 1),
            end_mode="after_n",
            occurrence_limit=12,
            occurrence_count=3,
        )
        assert next_date == date(2026, 5, 1)

    def test_weekend_behavior_before(self):
        """Weekend 'before' shifts Saturday to Friday"""
        # 2026-04-04 is a Saturday
        next_date = RecurringTransactionService._adjust_weekend(
            date(2026, 4, 4), "before"
        )
        assert next_date == date(2026, 4, 3)  # Friday

    def test_weekend_behavior_after(self):
        """Weekend 'after' shifts Sunday to Monday"""
        # 2026-04-05 is a Sunday
        next_date = RecurringTransactionService._adjust_weekend(
            date(2026, 4, 5), "after"
        )
        assert next_date == date(2026, 4, 6)  # Monday

    def test_weekend_behavior_none(self):
        """Weekend 'none' keeps weekend dates unchanged"""
        next_date = RecurringTransactionService._adjust_weekend(
            date(2026, 4, 4), "none"
        )
        assert next_date == date(2026, 4, 4)  # Saturday unchanged

    def test_weekday_unaffected_by_weekend_behavior(self):
        """Weekday dates are never adjusted regardless of behavior"""
        # 2026-04-01 is a Wednesday
        for behavior in ["none", "before", "after"]:
            result = RecurringTransactionService._adjust_weekend(
                date(2026, 4, 1), behavior
            )
            assert result == date(2026, 4, 1)

    @pytest.mark.asyncio
    async def test_post_transaction_increments_count(self, db_session, test_family, budget_account):
        """Posting a transaction increments occurrence_count"""
        recurring = BudgetRecurringTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            name="Monthly Test",
            amount=-50000,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            start_date=date(2026, 1, 1),
            end_mode="after_n",
            occurrence_limit=3,
        )
        db_session.add(recurring)
        await db_session.commit()
        await db_session.refresh(recurring)

        tx = await RecurringTransactionService.post_transaction(
            db_session, recurring.id, test_family.id, date(2026, 4, 1)
        )
        await db_session.refresh(recurring)
        assert recurring.occurrence_count == 1
        assert recurring.is_active is True

    @pytest.mark.asyncio
    async def test_post_transaction_deactivates_at_limit(self, db_session, test_family, budget_account):
        """Recurring template deactivates when occurrence limit is reached"""
        recurring = BudgetRecurringTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            name="Limited Test",
            amount=-10000,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            start_date=date(2026, 1, 1),
            end_mode="after_n",
            occurrence_limit=1,
        )
        db_session.add(recurring)
        await db_session.commit()
        await db_session.refresh(recurring)

        await RecurringTransactionService.post_transaction(
            db_session, recurring.id, test_family.id, date(2026, 4, 1)
        )
        await db_session.refresh(recurring)
        assert recurring.occurrence_count == 1
        assert recurring.is_active is False
        assert recurring.next_due_date is None
```

- [ ] **Step 6: Run all Wave 1 tests**

```bash
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_wave1_gap_closure.py -v
```

Expected: All 17+ tests PASS

- [ ] **Step 7: Run full test suite**

```bash
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v --tb=short
```

Expected: No regressions in existing tests

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/budget.py backend/app/services/budget/recurring_transaction_service.py backend/tests/test_wave1_gap_closure.py
git commit -m "feat: add schedule end modes (yearly, after_n, weekend behavior)"
```

---

### Task 5: Rebuild, Deploy, and Verify

**Files:** None (deployment task)

- [ ] **Step 1: Rebuild and restart backend**

```bash
docker compose up -d --build backend
```

- [ ] **Step 2: Apply migration**

```bash
docker exec family_app_backend alembic upgrade head
```

- [ ] **Step 3: Verify API endpoints**

Test payee favorites:
```bash
# Login first
TOKEN=$(curl -s -X POST http://localhost:8003/api/auth/login -H "Content-Type: application/json" -d '{"email":"mom@demo.com","password":"password123"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

# Create favorite payee
curl -s -X POST http://localhost:8003/api/budget/payees -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"name":"Oxxo","is_favorite":true}' | python3 -m json.tool

# List favorites only
curl -s "http://localhost:8003/api/budget/payees?favorites_only=true" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

- [ ] **Step 4: Reseed demo data**

```bash
docker exec family_app_backend python /app/seed_data.py
```

- [ ] **Step 5: Final commit (if any seed data changes needed)**

```bash
git add -A && git commit -m "chore: wave 1 deployment verification"
```
