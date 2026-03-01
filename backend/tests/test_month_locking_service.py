"""
Tests for Month Locking Service (Phase 8)

Tests for closing/reopening months and preventing edits to closed months.
"""

import pytest
from datetime import date, datetime
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetAllocation, BudgetTransaction
from app.services.budget.month_locking_service import MonthLockingService
from app.services.budget.allocation_service import AllocationService
from app.services.budget.transaction_service import TransactionService
from app.services.budget.category_service import CategoryService
from app.services.budget.account_service import AccountService
from app.core.exceptions import NotFoundException, ValidationError
from app.schemas.budget import (
    AllocationCreate,
    TransactionCreate,
    CategoryCreate,
    CategoryGroupCreate,
    AccountCreate,
)


@pytest.mark.asyncio
async def test_close_month_basic(db_session: AsyncSession, test_family):
    """Test basic month closing functionality"""
    month_date = date(2024, 3, 1)
    test_family_id = test_family.id
    
    # Create a test allocation for the month
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    allocation = await AllocationService.create(
        db_session,
        test_family_id,
        AllocationCreate(
            category_id=category.id,
            month=month_date,
            budgeted_amount=10000,
        ),
    )
    
    # Close the month
    result = await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    assert result["allocation_count"] == 1
    assert result["month"] == month_date
    assert result["closed_at"] is not None
    assert isinstance(result["closed_at"], datetime)
    
    # Verify allocation has closed_at set
    refreshed = await AllocationService.get_by_id(db_session, allocation.id, test_family_id)
    assert refreshed.closed_at is not None


@pytest.mark.asyncio
async def test_close_month_not_found(db_session: AsyncSession, test_family):
    """Test closing a month with no allocations raises error"""
    month_date = date(2024, 3, 1)
    test_family_id = test_family.id
    
    with pytest.raises(NotFoundException):
        await MonthLockingService.close_month(db_session, test_family_id, month_date)


@pytest.mark.asyncio
async def test_reopen_month(db_session: AsyncSession, test_family):
    """Test reopening a closed month"""
    month_date = date(2024, 3, 1)
    test_family_id = test_family.id
    
    # Create and close a month
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    allocation = await AllocationService.create(
        db_session,
        test_family_id,
        AllocationCreate(
            category_id=category.id,
            month=month_date,
            budgeted_amount=10000,
        ),
    )
    
    await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Reopen the month
    result = await MonthLockingService.reopen_month(db_session, test_family_id, month_date)
    
    assert result["allocation_count"] == 1
    assert result["month"] == month_date
    
    # Verify allocation has closed_at cleared
    refreshed = await AllocationService.get_by_id(db_session, allocation.id, test_family_id)
    assert refreshed.closed_at is None


@pytest.mark.asyncio
async def test_reopen_month_not_found(db_session: AsyncSession, test_family):
    """Test reopening a month that's not closed"""
    month_date = date(2024, 3, 1)
    test_family_id = test_family.id
    
    with pytest.raises(NotFoundException):
        await MonthLockingService.reopen_month(db_session, test_family_id, month_date)


@pytest.mark.asyncio
async def test_is_month_closed(db_session: AsyncSession, test_family):
    """Test checking if month is closed"""
    month_date = date(2024, 3, 1)
    test_family_id = test_family.id
    
    # Create allocation
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    await AllocationService.create(
        db_session,
        test_family_id,
        AllocationCreate(
            category_id=category.id,
            month=month_date,
            budgeted_amount=10000,
        ),
    )
    
    # Month should not be closed initially
    is_closed = await MonthLockingService.is_month_closed(db_session, test_family_id, month_date)
    assert is_closed is False
    
    # Close the month
    await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Now it should be closed
    is_closed = await MonthLockingService.is_month_closed(db_session, test_family_id, month_date)
    assert is_closed is True


@pytest.mark.asyncio
async def test_get_month_status(db_session: AsyncSession, test_family):
    """Test getting month status details"""
    month_date = date(2024, 3, 1)
    test_family_id = test_family.id
    
    # Create allocation
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    await AllocationService.create(
        db_session,
        test_family_id,
        AllocationCreate(
            category_id=category.id,
            month=month_date,
            budgeted_amount=10000,
        ),
    )
    
    # Get status before closing
    status = await MonthLockingService.get_month_status(db_session, test_family_id, month_date)
    assert status["is_closed"] is False
    assert status["closed_at"] is None
    assert status["allocation_count"] == 1
    assert status["month"] == month_date
    
    # Close the month
    await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Get status after closing
    status = await MonthLockingService.get_month_status(db_session, test_family_id, month_date)
    assert status["is_closed"] is True
    assert status["closed_at"] is not None
    assert status["allocation_count"] == 1


@pytest.mark.asyncio
async def test_get_closed_months(db_session: AsyncSession, test_family):
    """Test listing closed months"""
    test_family_id = test_family.id
    
    # Create and close multiple months
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    for month_num in [1, 2, 3]:
        month_date = date(2024, month_num, 1)
        await AllocationService.create(
            db_session,
            test_family_id,
            AllocationCreate(
                category_id=category.id,
                month=month_date,
                budgeted_amount=10000,
            ),
        )
        await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Get closed months
    closed_months = await MonthLockingService.get_closed_months(db_session, test_family_id)
    
    assert len(closed_months) == 3
    assert closed_months[0]["month"] == date(2024, 3, 1)  # Most recent first
    assert closed_months[1]["month"] == date(2024, 2, 1)
    assert closed_months[2]["month"] == date(2024, 1, 1)


@pytest.mark.asyncio
async def test_get_closed_months_pagination(db_session: AsyncSession, test_family):
    """Test pagination of closed months"""
    test_family_id = test_family.id
    
    # Create and close 5 months
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    for month_num in range(1, 6):
        month_date = date(2024, month_num, 1)
        await AllocationService.create(
            db_session,
            test_family_id,
            AllocationCreate(
                category_id=category.id,
                month=month_date,
                budgeted_amount=10000,
            ),
        )
        await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Get first 2 months
    closed_months = await MonthLockingService.get_closed_months(db_session, test_family_id, limit=2, offset=0)
    assert len(closed_months) == 2
    
    # Get next 2 months
    closed_months = await MonthLockingService.get_closed_months(db_session, test_family_id, limit=2, offset=2)
    assert len(closed_months) == 2
    
    # Get remaining month
    closed_months = await MonthLockingService.get_closed_months(db_session, test_family_id, limit=2, offset=4)
    assert len(closed_months) == 1


@pytest.mark.asyncio
async def test_validate_month_not_closed(db_session: AsyncSession, test_family):
    """Test validation of closed months"""
    month_date = date(2024, 3, 1)
    test_family_id = test_family.id
    
    # Create and close a month
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    await AllocationService.create(
        db_session,
        test_family_id,
        AllocationCreate(
            category_id=category.id,
            month=month_date,
            budgeted_amount=10000,
        ),
    )
    
    await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Should raise ValidationError for closed month
    with pytest.raises(ValidationError):
        await MonthLockingService.validate_month_not_closed(db_session, test_family_id, month_date)
    
    # Should not raise for open month
    open_month = date(2024, 4, 1)
    await MonthLockingService.validate_month_not_closed(db_session, test_family_id, open_month)


@pytest.mark.asyncio
async def test_cannot_create_transaction_in_closed_month(db_session: AsyncSession, test_family):
    """Test that transactions cannot be created in closed months"""
    month_date = date(2024, 3, 1)
    transaction_date = date(2024, 3, 15)
    test_family_id = test_family.id
    
    # Create account and category
    account = await AccountService.create(
        db_session,
        test_family_id,
        AccountCreate(
            name="Test Account",
            type="checking",
        ),
    )
    
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    # Create and close the month
    await AllocationService.create(
        db_session,
        test_family_id,
        AllocationCreate(
            category_id=category.id,
            month=month_date,
            budgeted_amount=10000,
        ),
    )
    
    await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Should not be able to create transaction in closed month
    with pytest.raises(ValidationError):
        await TransactionService.create(
            db_session,
            test_family_id,
            TransactionCreate(
                account_id=account.id,
                date=transaction_date,
                amount=5000,
                cleared=False,
                reconciled=False,
            ),
        )


@pytest.mark.asyncio
async def test_cannot_update_allocation_in_closed_month(db_session: AsyncSession, test_family):
    """Test that allocations cannot be updated in closed months"""
    month_date = date(2024, 3, 1)
    test_family_id = test_family.id
    
    # Create and close a month
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    allocation = await AllocationService.create(
        db_session,
        test_family_id,
        AllocationCreate(
            category_id=category.id,
            month=month_date,
            budgeted_amount=10000,
        ),
    )
    
    await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Should not be able to update allocation in closed month
    from app.schemas.budget import AllocationUpdate
    with pytest.raises(ValidationError):
        await AllocationService.update(
            db_session,
            allocation.id,
            test_family_id,
            AllocationUpdate(budgeted_amount=15000),
        )


@pytest.mark.asyncio
async def test_can_create_transaction_after_reopen(db_session: AsyncSession, test_family):
    """Test that transactions can be created after reopening a month"""
    month_date = date(2024, 3, 1)
    transaction_date = date(2024, 3, 15)
    test_family_id = test_family.id
    
    # Create account and category
    account = await AccountService.create(
        db_session,
        test_family_id,
        AccountCreate(
            name="Test Account",
            type="checking",
        ),
    )
    
    category = await CategoryService.create(
        db_session,
        test_family_id,
        CategoryCreate(
            name="Test Category",
            group_id=uuid4(),
            sort_order=0,
        ),
    )
    
    # Create and close the month
    await AllocationService.create(
        db_session,
        test_family_id,
        AllocationCreate(
            category_id=category.id,
            month=month_date,
            budgeted_amount=10000,
        ),
    )
    
    await MonthLockingService.close_month(db_session, test_family_id, month_date)
    
    # Reopen the month
    await MonthLockingService.reopen_month(db_session, test_family_id, month_date)
    
    # Now we should be able to create a transaction
    transaction = await TransactionService.create(
        db_session,
        test_family_id,
        TransactionCreate(
            account_id=account.id,
            date=transaction_date,
            amount=5000,
            cleared=False,
            reconciled=False,
        ),
    )
    
    assert transaction.id is not None
    assert transaction.amount == 5000
