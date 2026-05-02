"""Tests for split transaction service."""

import pytest
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.budget import BudgetTransaction
from app.services.budget.account_service import AccountService
from app.services.budget.category_service import CategoryGroupService, CategoryService
from app.services.budget.transaction_service import TransactionService
from app.schemas.budget import (
    AccountCreate,
    CategoryGroupCreate,
    CategoryCreate,
    SplitChild,
)
from app.core.exceptions import ValidationError, NotFoundException


@pytest.mark.asyncio
async def test_create_split_creates_parent_and_children(db: AsyncSession, family_id):
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )
    group = await CategoryGroupService.create(
        db, family_id, CategoryGroupCreate(name="Food", is_income=False)
    )
    cat_a = await CategoryService.create(
        db, family_id, CategoryCreate(name="Groceries", group_id=group.id)
    )
    cat_b = await CategoryService.create(
        db, family_id, CategoryCreate(name="Snacks", group_id=group.id)
    )

    parent = await TransactionService.create_split(
        db, family_id,
        account_id=account.id,
        txn_date=date(2026, 5, 1),
        splits=[
            SplitChild(amount=-7000, category_id=cat_a.id),
            SplitChild(amount=-3000, category_id=cat_b.id),
        ],
    )

    assert parent.is_parent is True
    assert parent.parent_id is None
    assert parent.amount == -10000
    assert parent.category_id is None

    children = await TransactionService.get_split_children(db, parent.id, family_id)
    assert len(children) == 2
    assert sum(c.amount for c in children) == parent.amount
    assert {c.category_id for c in children} == {cat_a.id, cat_b.id}
    for c in children:
        assert c.parent_id == parent.id
        assert c.is_parent is False


@pytest.mark.asyncio
async def test_create_split_rejects_single_leg(db: AsyncSession, family_id):
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )
    group = await CategoryGroupService.create(
        db, family_id, CategoryGroupCreate(name="Food", is_income=False)
    )
    cat = await CategoryService.create(
        db, family_id, CategoryCreate(name="Groceries", group_id=group.id)
    )
    with pytest.raises(ValidationError):
        await TransactionService.create_split(
            db, family_id,
            account_id=account.id,
            txn_date=date(2026, 5, 1),
            splits=[SplitChild(amount=-100, category_id=cat.id)],
        )


@pytest.mark.asyncio
async def test_replace_split_children_updates_parent_total(db: AsyncSession, family_id):
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )
    group = await CategoryGroupService.create(
        db, family_id, CategoryGroupCreate(name="Food", is_income=False)
    )
    cat_a = await CategoryService.create(
        db, family_id, CategoryCreate(name="Groceries", group_id=group.id)
    )
    cat_b = await CategoryService.create(
        db, family_id, CategoryCreate(name="Snacks", group_id=group.id)
    )

    parent = await TransactionService.create_split(
        db, family_id,
        account_id=account.id,
        txn_date=date(2026, 5, 1),
        splits=[
            SplitChild(amount=-7000, category_id=cat_a.id),
            SplitChild(amount=-3000, category_id=cat_b.id),
        ],
    )
    assert parent.amount == -10000

    parent = await TransactionService.replace_split_children(
        db, parent.id, family_id,
        splits=[
            SplitChild(amount=-2000, category_id=cat_a.id),
            SplitChild(amount=-2500, category_id=cat_b.id),
            SplitChild(amount=-1500, category_id=cat_a.id),
        ],
    )
    assert parent.amount == -6000

    children = await TransactionService.get_split_children(db, parent.id, family_id)
    assert len(children) == 3
    assert sum(c.amount for c in children) == -6000


@pytest.mark.asyncio
async def test_delete_parent_cascades_children(db: AsyncSession, family_id):
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
    parent_id = parent.id

    await TransactionService.delete_by_id(db, parent_id, family_id)

    # Children should be gone via FK cascade (parent_id ondelete=CASCADE)
    remaining = (await db.execute(
        select(BudgetTransaction).where(BudgetTransaction.parent_id == parent_id)
    )).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_get_split_children_rejects_non_parent(db: AsyncSession, family_id):
    from app.schemas.budget import TransactionCreate
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )
    standalone = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-100),
    )
    with pytest.raises(ValidationError):
        await TransactionService.get_split_children(db, standalone.id, family_id)


@pytest.mark.asyncio
async def test_bulk_update_rejects_cross_family_category(db: AsyncSession, family_id):
    """bulk_update_transactions must refuse to set a category from another family."""
    from app.schemas.budget import TransactionCreate
    from app.models.family import Family

    # Owner family + transaction
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )
    txn = await TransactionService.create(
        db, family_id,
        TransactionCreate(account_id=account.id, date=date(2026, 5, 1), amount=-100),
    )

    # Foreign family + category that the owner must not be allowed to attach
    other_family = Family(name="Other Family")
    db.add(other_family)
    await db.commit()
    await db.refresh(other_family)

    other_group = await CategoryGroupService.create(
        db, other_family.id, CategoryGroupCreate(name="Other Food", is_income=False)
    )
    other_cat = await CategoryService.create(
        db, other_family.id, CategoryCreate(name="Their Groceries", group_id=other_group.id)
    )

    with pytest.raises(NotFoundException):
        await TransactionService.bulk_update_transactions(
            db, family_id, [txn.id], {"category_id": other_cat.id}
        )

    # Verify txn untouched
    await db.refresh(txn)
    assert txn.category_id is None
