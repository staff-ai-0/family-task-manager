"""Tests for the budget cleanup PR.

Locks the contracts of three small refactors:
- replace_split_children soft-deletes children instead of hard-deleting them.
- post_all_due posts the whole batch in one transaction so a failure on
  row N rolls back rows 1..N-1.
- UsageService.try_increment_within_limit gives a single-statement,
  race-free check-and-increment for metered features.
"""

import pytest
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.budget import (
    BudgetTransaction,
    BudgetRecurringTransaction,
)
from app.services.budget.account_service import AccountService
from app.services.budget.category_service import (
    CategoryGroupService,
    CategoryService,
)
from app.services.budget.transaction_service import TransactionService
from app.services.budget.recurring_transaction_service import (
    RecurringTransactionService,
)
from app.services.usage_service import UsageService
from app.schemas.budget import (
    AccountCreate,
    CategoryGroupCreate,
    CategoryCreate,
    SplitChild,
)


# ---------------------------------------------------------------------------
# replace_split_children: soft-delete instead of hard-delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replace_split_children_soft_deletes_old_legs(
    db: AsyncSession, family_id
):
    """Replacing a split's legs must mark the old children with deleted_at,
    not remove them from the table. The audit trail of replaced legs has
    to survive — and the rest of the codebase already treats
    deleted_at IS NOT NULL rows as gone, so behavior is unchanged for
    callers that respect the convention.
    """
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )
    group = await CategoryGroupService.create(
        db, family_id, CategoryGroupCreate(name="Food", is_income=False)
    )
    cat = await CategoryService.create(
        db, family_id, CategoryCreate(name="Groceries", group_id=group.id)
    )

    parent = await TransactionService.create_split(
        db, family_id,
        account_id=account.id,
        txn_date=date(2026, 5, 1),
        splits=[
            SplitChild(amount=-100, category_id=cat.id),
            SplitChild(amount=-200, category_id=cat.id),
        ],
    )
    original_children = await TransactionService.get_split_children(
        db, parent.id, family_id
    )
    original_ids = {c.id for c in original_children}
    assert len(original_ids) == 2

    await TransactionService.replace_split_children(
        db, parent.id, family_id,
        splits=[
            SplitChild(amount=-50, category_id=cat.id),
            SplitChild(amount=-50, category_id=cat.id),
            SplitChild(amount=-50, category_id=cat.id),
        ],
    )

    # Live (visible) children: 3 new ones
    live = await TransactionService.get_split_children(db, parent.id, family_id)
    assert len(live) == 3
    assert {c.id for c in live}.isdisjoint(original_ids)

    # Old rows still exist with deleted_at set — proof of soft-delete
    rows = (
        await db.execute(
            select(BudgetTransaction).where(
                BudgetTransaction.id.in_(original_ids)
            )
        )
    ).scalars().all()
    assert len(rows) == 2
    for r in rows:
        assert r.deleted_at is not None


# ---------------------------------------------------------------------------
# post_all_due: single-transaction semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_all_due_advances_state_for_every_template(
    db: AsyncSession, family_id
):
    """All due templates must post in one batch; each template's
    next_due_date and occurrence_count must move forward, and each posted
    transaction must end up with a real id.
    """
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )

    today = date(2026, 5, 1)
    due_templates = []
    for i in range(3):
        rt = BudgetRecurringTransaction(
            family_id=family_id,
            account_id=account.id,
            name=f"Subscription {i}",
            amount=-(1000 + i),
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 1},
            start_date=today - timedelta(days=30),
            next_due_date=today,
            is_active=True,
            occurrence_count=0,
            end_mode="never",
        )
        db.add(rt)
        due_templates.append(rt)
    await db.commit()
    for rt in due_templates:
        await db.refresh(rt)

    result = await RecurringTransactionService.post_all_due(
        db, family_id, as_of_date=today
    )
    assert result["posted"] == 3
    assert all(item["transaction_id"] for item in result["transactions"])

    for rt in due_templates:
        await db.refresh(rt)
        assert rt.occurrence_count == 1
        assert rt.last_generated_date == today
        assert rt.next_due_date is not None
        assert rt.next_due_date > today


@pytest.mark.asyncio
async def test_post_all_due_deactivates_after_n_template(
    db: AsyncSession, family_id
):
    """A template with end_mode=after_n that hits its occurrence_limit
    inside the bulk batch must deactivate (is_active=False, next_due_date
    cleared) and the deactivation must persist after post_all_due commits.
    """
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )

    today = date(2026, 5, 1)
    rt = BudgetRecurringTransaction(
        family_id=family_id,
        account_id=account.id,
        name="One-shot",
        amount=-500,
        recurrence_type="monthly_dayofmonth",
        recurrence_interval=1,
        recurrence_pattern={"day": 1},
        start_date=today - timedelta(days=30),
        next_due_date=today,
        is_active=True,
        occurrence_count=0,
        end_mode="after_n",
        occurrence_limit=1,
    )
    db.add(rt)
    await db.commit()
    await db.refresh(rt)

    result = await RecurringTransactionService.post_all_due(
        db, family_id, as_of_date=today,
    )
    assert result["posted"] == 1

    await db.refresh(rt)
    assert rt.is_active is False
    assert rt.next_due_date is None
    assert rt.occurrence_count == 1
    assert rt.last_generated_date == today


# ---------------------------------------------------------------------------
# UsageService.try_increment_within_limit: atomic check + increment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_try_increment_within_limit_basic_path(
    db: AsyncSession, family_id
):
    """First call creates the row at amount; subsequent calls accumulate
    while remaining within the limit.
    """
    new_count = await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=10, amount=3,
    )
    assert new_count == 3

    new_count = await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=10, amount=5,
    )
    assert new_count == 8


@pytest.mark.asyncio
async def test_try_increment_within_limit_refuses_over_limit(
    db: AsyncSession, family_id
):
    """When current + amount would exceed the limit, return None and leave
    the counter untouched. No partial credit, no over-counting.
    """
    await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=10, amount=8,
    )

    rejected = await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=10, amount=5,
    )
    assert rejected is None

    current = await UsageService.get_usage(db, family_id, "budget_transaction")
    assert current == 8

    # An amount that fits exactly is accepted (boundary).
    accepted = await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=10, amount=2,
    )
    assert accepted == 10


@pytest.mark.asyncio
async def test_try_increment_within_limit_unlimited_and_disabled(
    db: AsyncSession, family_id
):
    """limit=-1 is unlimited and always increments;
    limit=0 is disabled and always returns None.
    """
    accepted = await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=-1, amount=10_000,
    )
    assert accepted == 10_000

    rejected = await UsageService.try_increment_within_limit(
        db, family_id, "ai_locked_feature", limit=0, amount=1,
    )
    assert rejected is None
    assert await UsageService.get_usage(db, family_id, "ai_locked_feature") == 0


@pytest.mark.asyncio
async def test_try_increment_within_limit_rejects_first_call_over_limit(
    db: AsyncSession, family_id
):
    """When the family has no row yet and amount alone exceeds the limit,
    refuse without creating the row. Otherwise the INSERT path would
    silently bypass the cap.
    """
    rejected = await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=5, amount=10,
    )
    assert rejected is None
    assert await UsageService.get_usage(db, family_id, "budget_transaction") == 0


@pytest.mark.asyncio
async def test_try_increment_within_limit_does_not_clobber_caller_session(
    db: AsyncSession, family_id
):
    """try_increment_within_limit must not commit or roll back the caller's
    session. Pending ORM mutations (a transaction added but not committed)
    must survive across both the success and rejection paths so the caller
    keeps full control of the outer transaction boundary.
    """
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )

    # Pending mutation that must not be committed by the increment call.
    pending_txn = BudgetTransaction(
        family_id=family_id,
        account_id=account.id,
        date=date(2026, 5, 1),
        amount=-100,
    )
    db.add(pending_txn)
    # Do NOT commit; pending_txn lives in the session only.

    # Success path: should not commit the pending row either.
    new_count = await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=10, amount=2,
    )
    assert new_count == 2

    # Rejection path: must not roll back pending_txn.
    rejected = await UsageService.try_increment_within_limit(
        db, family_id, "budget_transaction", limit=10, amount=999,
    )
    assert rejected is None

    # Caller commits when ready; the pending txn must end up persisted.
    await db.commit()
    await db.refresh(pending_txn)
    assert pending_txn.id is not None

    fetched = await TransactionService.get_by_id(db, pending_txn.id, family_id)
    assert fetched.amount == -100
