"""
Tests for Goal Service

Comprehensive unit tests for budget goal creation, updates, and progress tracking.
"""

import pytest
import pytest_asyncio
from datetime import date, timedelta
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import (
    BudgetGoal,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetTransaction,
)
from app.models.family import Family
from app.services.budget.goal_service import GoalService
from app.schemas.budget import (
    GoalCreate,
    GoalUpdate,
)
from app.core.exceptions import NotFoundException


@pytest_asyncio.fixture
async def family_with_category(db_session: AsyncSession):
    """Create a family with a budget category for testing"""
    family = Family(id=uuid4(), name="Test Family")
    db_session.add(family)
    await db_session.flush()

    group = BudgetCategoryGroup(
        id=uuid4(),
        family_id=family.id,
        name="Test Group",
        is_income=False,
    )
    db_session.add(group)
    await db_session.flush()

    category = BudgetCategory(
        id=uuid4(),
        family_id=family.id,
        group_id=group.id,
        name="Groceries",
    )
    db_session.add(category)
    await db_session.commit()

    return family, category


@pytest.mark.asyncio
async def test_create_spending_limit_goal(
    db_session: AsyncSession, family_with_category
):
    """Test creating a spending limit goal"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,  # $200
        period="monthly",
        start_date=date.today(),
        end_date=None,
        is_active=True,
        name="Monthly Grocery Limit",
        notes="Keep groceries under $200/month",
    )

    goal = await GoalService.create(db_session, family.id, goal_data)

    assert goal.id is not None
    assert goal.family_id == family.id
    assert goal.category_id == category.id
    assert goal.goal_type == "spending_limit"
    assert goal.target_amount == 20000
    assert goal.period == "monthly"
    assert goal.name == "Monthly Grocery Limit"
    assert goal.is_active is True


@pytest.mark.asyncio
async def test_create_savings_target_goal(
    db_session: AsyncSession, family_with_category
):
    """Test creating a savings target goal"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="savings_target",
        target_amount=50000,  # $500
        period="annual",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        is_active=True,
        name="Annual Savings Goal",
        notes="Save $500 this year",
    )

    goal = await GoalService.create(db_session, family.id, goal_data)

    assert goal.goal_type == "savings_target"
    assert goal.target_amount == 50000
    assert goal.period == "annual"
    assert goal.end_date == date(2026, 12, 31)


@pytest.mark.asyncio
async def test_get_goal_by_id(db_session: AsyncSession, family_with_category):
    """Test retrieving a goal by ID"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date.today(),
        is_active=True,
        name="Test Goal",
    )

    created_goal = await GoalService.create(db_session, family.id, goal_data)
    retrieved_goal = await GoalService.get_by_id(
        db_session, created_goal.id, family.id
    )

    assert retrieved_goal.id == created_goal.id
    assert retrieved_goal.name == "Test Goal"


@pytest.mark.asyncio
async def test_get_goal_wrong_family(db_session: AsyncSession, family_with_category):
    """Test that getting a goal from wrong family raises error"""
    family, category = family_with_category
    wrong_family_id = uuid4()

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date.today(),
        is_active=True,
        name="Test Goal",
    )

    goal = await GoalService.create(db_session, family.id, goal_data)

    with pytest.raises(NotFoundException):
        await GoalService.get_by_id(db_session, goal.id, wrong_family_id)


@pytest.mark.asyncio
async def test_update_goal(db_session: AsyncSession, family_with_category):
    """Test updating a goal"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date.today(),
        is_active=True,
        name="Original Name",
    )

    goal = await GoalService.create(db_session, family.id, goal_data)

    # Update the goal
    update_data = GoalUpdate(
        name="Updated Name",
        target_amount=30000,
        is_active=False,
    )

    updated_goal = await GoalService.update(
        db_session, goal.id, family.id, update_data
    )

    assert updated_goal.name == "Updated Name"
    assert updated_goal.target_amount == 30000
    assert updated_goal.is_active is False
    assert updated_goal.goal_type == "spending_limit"  # Unchanged


@pytest.mark.asyncio
async def test_delete_goal(db_session: AsyncSession, family_with_category):
    """Test deleting a goal"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date.today(),
        is_active=True,
        name="Test Goal",
    )

    goal = await GoalService.create(db_session, family.id, goal_data)
    goal_id = goal.id

    await GoalService.delete_by_id(db_session, goal_id, family.id)

    with pytest.raises(NotFoundException):
        await GoalService.get_by_id(db_session, goal_id, family.id)


@pytest.mark.asyncio
async def test_list_goals_by_category(
    db_session: AsyncSession, family_with_category
):
    """Test listing goals for a specific category"""
    family, category = family_with_category

    # Create multiple goals
    for i in range(3):
        goal_data = GoalCreate(
            category_id=category.id,
            goal_type="spending_limit",
            target_amount=20000 + (i * 1000),
            period="monthly",
            start_date=date.today(),
            is_active=True,
            name=f"Goal {i+1}",
        )
        await GoalService.create(db_session, family.id, goal_data)

    goals = await GoalService.list_by_category(
        db_session, category.id, family.id, active_only=True
    )

    assert len(goals) == 3


@pytest.mark.asyncio
async def test_list_active_goals(db_session: AsyncSession, family_with_category):
    """Test listing active goals"""
    family, category = family_with_category

    # Create an active goal
    active_goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date.today() - timedelta(days=10),
        end_date=date.today() + timedelta(days=20),
        is_active=True,
        name="Active Goal",
    )
    await GoalService.create(db_session, family.id, active_goal_data)

    # Create an inactive goal
    inactive_goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=15000,
        period="monthly",
        start_date=date.today(),
        is_active=False,
        name="Inactive Goal",
    )
    await GoalService.create(db_session, family.id, inactive_goal_data)

    active_goals = await GoalService.list_active(db_session, family.id)

    assert len(active_goals) == 1
    assert active_goals[0].name == "Active Goal"


@pytest.mark.asyncio
async def test_list_active_goals_with_date_filtering(
    db_session: AsyncSession, family_with_category
):
    """Test that date ranges are respected when listing active goals"""
    family, category = family_with_category

    # Goal that started in past and ends in future
    valid_goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date.today() - timedelta(days=10),
        end_date=date.today() + timedelta(days=20),
        is_active=True,
        name="Valid Goal",
    )
    await GoalService.create(db_session, family.id, valid_goal_data)

    # Goal that starts in future
    future_goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date.today() + timedelta(days=30),
        is_active=True,
        name="Future Goal",
    )
    await GoalService.create(db_session, family.id, future_goal_data)

    # Goal that already ended
    past_goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date.today() - timedelta(days=30),
        end_date=date.today() - timedelta(days=5),
        is_active=True,
        name="Past Goal",
    )
    await GoalService.create(db_session, family.id, past_goal_data)

    active_goals = await GoalService.list_active(db_session, family.id)

    assert len(active_goals) == 1
    assert active_goals[0].name == "Valid Goal"


@pytest.mark.asyncio
async def test_calculate_progress_spending_limit_under_budget(
    db_session: AsyncSession, family_with_category
):
    """Test progress calculation for spending limit when under budget"""
    family, category = family_with_category

    # Create goal for $200/month
    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date(2026, 3, 1),
        is_active=True,
        name="Monthly Grocery Limit",
    )
    goal = await GoalService.create(db_session, family.id, goal_data)

    # Add $100 in expenses
    transaction = BudgetTransaction(
        id=uuid4(),
        family_id=family.id,
        category_id=category.id,
        account_id=uuid4(),
        payee_id=None,
        amount=-10000,  # -$100 (expense)
        transaction_date=date(2026, 3, 15),
        description="Grocery shopping",
    )
    db_session.add(transaction)
    await db_session.commit()

    progress = await GoalService.calculate_progress(db_session, goal.id, family.id)

    assert progress["goal_type"] == "spending_limit"
    assert progress["target_amount"] == 20000
    assert progress["actual_amount"] == 10000
    assert progress["on_track"] is True
    assert progress["percentage"] == 50.0


@pytest.mark.asyncio
async def test_calculate_progress_spending_limit_over_budget(
    db_session: AsyncSession, family_with_category
):
    """Test progress calculation for spending limit when over budget"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date(2026, 3, 1),
        is_active=True,
        name="Monthly Grocery Limit",
    )
    goal = await GoalService.create(db_session, family.id, goal_data)

    # Add $300 in expenses (over budget)
    transaction = BudgetTransaction(
        id=uuid4(),
        family_id=family.id,
        category_id=category.id,
        account_id=uuid4(),
        payee_id=None,
        amount=-30000,  # -$300 (expense)
        transaction_date=date(2026, 3, 15),
        description="Grocery shopping",
    )
    db_session.add(transaction)
    await db_session.commit()

    progress = await GoalService.calculate_progress(db_session, goal.id, family.id)

    assert progress["on_track"] is False
    assert progress["actual_amount"] == 30000
    assert progress["percentage"] == 100.0  # Capped at 100


@pytest.mark.asyncio
async def test_calculate_progress_savings_target_under_goal(
    db_session: AsyncSession, family_with_category
):
    """Test progress calculation for savings target below goal"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="savings_target",
        target_amount=50000,
        period="quarterly",
        start_date=date(2026, 1, 1),
        is_active=True,
        name="Quarterly Savings Goal",
    )
    goal = await GoalService.create(db_session, family.id, goal_data)

    # Add $300 in income
    transaction = BudgetTransaction(
        id=uuid4(),
        family_id=family.id,
        category_id=category.id,
        account_id=uuid4(),
        payee_id=None,
        amount=30000,  # +$300 (income)
        transaction_date=date(2026, 2, 15),
        description="Savings deposit",
    )
    db_session.add(transaction)
    await db_session.commit()

    progress = await GoalService.calculate_progress(db_session, goal.id, family.id)

    assert progress["goal_type"] == "savings_target"
    assert progress["target_amount"] == 50000
    assert progress["actual_amount"] == 30000
    assert progress["on_track"] is False
    assert progress["percentage"] == 60.0


@pytest.mark.asyncio
async def test_calculate_progress_savings_target_met(
    db_session: AsyncSession, family_with_category
):
    """Test progress calculation for savings target when met"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="savings_target",
        target_amount=50000,
        period="annual",
        start_date=date(2026, 1, 1),
        is_active=True,
        name="Annual Savings Goal",
    )
    goal = await GoalService.create(db_session, family.id, goal_data)

    # Add $600 in income
    transaction = BudgetTransaction(
        id=uuid4(),
        family_id=family.id,
        category_id=category.id,
        account_id=uuid4(),
        payee_id=None,
        amount=60000,  # +$600 (income)
        transaction_date=date(2026, 6, 15),
        description="Savings deposit",
    )
    db_session.add(transaction)
    await db_session.commit()

    progress = await GoalService.calculate_progress(db_session, goal.id, family.id)

    assert progress["on_track"] is True
    assert progress["actual_amount"] == 60000
    assert progress["percentage"] == 100.0  # Capped at 100


@pytest.mark.asyncio
async def test_calculate_progress_no_transactions(
    db_session: AsyncSession, family_with_category
):
    """Test progress when there are no transactions"""
    family, category = family_with_category

    goal_data = GoalCreate(
        category_id=category.id,
        goal_type="spending_limit",
        target_amount=20000,
        period="monthly",
        start_date=date(2026, 3, 1),
        is_active=True,
        name="Monthly Grocery Limit",
    )
    goal = await GoalService.create(db_session, family.id, goal_data)

    progress = await GoalService.calculate_progress(db_session, goal.id, family.id)

    assert progress["actual_amount"] == 0
    assert progress["on_track"] is True  # On track because no overspending
    assert progress["percentage"] == 0.0
