"""
Tests for CategorizationRuleService

Comprehensive tests for rule creation, matching, and suggestion logic.
"""

import pytest
from uuid import UUID, uuid4
import re

from sqlalchemy.ext.asyncio import AsyncSession
import pytest_asyncio

from app.models import Family
from app.models.budget import (
    BudgetCategorizationRule,
    BudgetCategory,
    BudgetCategoryGroup,
)
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.schemas.budget import CategorizationRuleCreate, CategorizationRuleUpdate
from app.core.exceptions import NotFoundException, ValidationException


# ============================================================================
# FIXTURES
# ============================================================================

@pytest_asyncio.fixture
async def family(db_session: AsyncSession):
    """Create a test family"""
    family = Family(id=uuid4(), name="Test Family")
    db_session.add(family)
    await db_session.commit()
    await db_session.refresh(family)
    return family


@pytest_asyncio.fixture
async def category_group(db_session: AsyncSession, family: Family):
    """Create a test category group"""
    group = BudgetCategoryGroup(
        id=uuid4(),
        family_id=family.id,
        name="Groceries",
        is_income=False,
    )
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    return group


@pytest_asyncio.fixture
async def category(db_session: AsyncSession, family: Family, category_group: BudgetCategoryGroup):
    """Create a test category"""
    cat = BudgetCategory(
        id=uuid4(),
        family_id=family.id,
        group_id=category_group.id,
        name="Fruits",
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return cat


@pytest_asyncio.fixture
async def other_category(db_session: AsyncSession, family: Family, category_group: BudgetCategoryGroup):
    """Create another test category"""
    cat = BudgetCategory(
        id=uuid4(),
        family_id=family.id,
        group_id=category_group.id,
        name="Vegetables",
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return cat


# ============================================================================
# CREATE RULE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_create_rule_with_exact_match(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with exact match type"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="Whole Foods",
        enabled=True,
        priority=10,
        notes="Test rule",
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    assert rule.category_id == category.id
    assert rule.rule_type == "exact"
    assert rule.match_field == "payee"
    assert rule.pattern == "Whole Foods"
    assert rule.enabled is True
    assert rule.priority == 10
    assert rule.notes == "Test rule"
    assert rule.family_id == family.id


@pytest.mark.asyncio
async def test_create_rule_with_contains_match(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with contains match type"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="contains",
        match_field="description",
        pattern="grocery",
        enabled=True,
        priority=5,
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    assert rule.rule_type == "contains"
    assert rule.match_field == "description"
    assert rule.pattern == "grocery"


@pytest.mark.asyncio
async def test_create_rule_with_startswith_match(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with startswith match type"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="startswith",
        match_field="payee",
        pattern="TRADER",
        enabled=True,
        priority=8,
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    assert rule.rule_type == "startswith"
    assert rule.pattern == "TRADER"


@pytest.mark.asyncio
async def test_create_rule_with_regex_match(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with regex match type"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="regex",
        match_field="payee",
        pattern=r"^TRADER.*\d+$",
        enabled=True,
        priority=15,
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    assert rule.rule_type == "regex"
    assert rule.pattern == r"^TRADER.*\d+$"


@pytest.mark.asyncio
async def test_create_rule_with_both_match_field(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with 'both' match field"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="contains",
        match_field="both",
        pattern="store",
        enabled=True,
        priority=0,
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    assert rule.match_field == "both"


@pytest.mark.asyncio
async def test_create_rule_invalid_rule_type(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with invalid rule_type raises ValidationException"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="invalid_type",
        match_field="payee",
        pattern="test",
    )
    with pytest.raises(ValidationException):
        await CategorizationRuleService.create(db_session, family.id, data)


@pytest.mark.asyncio
async def test_create_rule_invalid_match_field(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with invalid match_field raises ValidationException"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="invalid_field",
        pattern="test",
    )
    with pytest.raises(ValidationException):
        await CategorizationRuleService.create(db_session, family.id, data)


@pytest.mark.asyncio
async def test_create_rule_invalid_regex(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with invalid regex raises ValidationException"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="regex",
        match_field="payee",
        pattern="[invalid(regex",  # Invalid regex
    )
    with pytest.raises(ValidationException):
        await CategorizationRuleService.create(db_session, family.id, data)


@pytest.mark.asyncio
async def test_create_rule_nonexistent_category(db_session: AsyncSession, family: Family):
    """Test creating a rule with non-existent category raises NotFoundException"""
    data = CategorizationRuleCreate(
        category_id=uuid4(),  # Non-existent category
        rule_type="exact",
        match_field="payee",
        pattern="test",
    )
    with pytest.raises(NotFoundException):
        await CategorizationRuleService.create(db_session, family.id, data)


@pytest.mark.asyncio
async def test_create_rule_category_from_different_family(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test creating a rule with category from different family raises NotFoundException"""
    other_family = Family(id=uuid4(), name="Other Family")
    db_session.add(other_family)
    await db_session.commit()

    data = CategorizationRuleCreate(
        category_id=category.id,  # Category belongs to 'family', not 'other_family'
        rule_type="exact",
        match_field="payee",
        pattern="test",
    )
    with pytest.raises(NotFoundException):
        await CategorizationRuleService.create(db_session, other_family.id, data)


# ============================================================================
# UPDATE RULE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_update_rule_pattern(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test updating a rule's pattern"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="Old Pattern",
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    update_data = CategorizationRuleUpdate(pattern="New Pattern")
    updated_rule = await CategorizationRuleService.update(db_session, rule.id, family.id, update_data)

    assert updated_rule.pattern == "New Pattern"


@pytest.mark.asyncio
async def test_update_rule_category(db_session: AsyncSession, family: Family, category: BudgetCategory, other_category: BudgetCategory):
    """Test updating a rule's category"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="test",
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    update_data = CategorizationRuleUpdate(category_id=other_category.id)
    updated_rule = await CategorizationRuleService.update(db_session, rule.id, family.id, update_data)

    assert updated_rule.category_id == other_category.id


@pytest.mark.asyncio
async def test_update_rule_enabled_status(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test toggling rule enabled status"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="test",
        enabled=True,
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)
    assert rule.enabled is True

    update_data = CategorizationRuleUpdate(enabled=False)
    updated_rule = await CategorizationRuleService.update(db_session, rule.id, family.id, update_data)

    assert updated_rule.enabled is False


@pytest.mark.asyncio
async def test_update_rule_priority(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test updating rule priority"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="test",
        priority=5,
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    update_data = CategorizationRuleUpdate(priority=20)
    updated_rule = await CategorizationRuleService.update(db_session, rule.id, family.id, update_data)

    assert updated_rule.priority == 20


@pytest.mark.asyncio
async def test_update_rule_invalid_regex(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test updating a rule with invalid regex raises ValidationException"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="regex",
        match_field="payee",
        pattern=r"^valid$",
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    update_data = CategorizationRuleUpdate(pattern="[invalid(regex")
    with pytest.raises(ValidationException):
        await CategorizationRuleService.update(db_session, rule.id, family.id, update_data)


# ============================================================================
# LIST RULES TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_list_rules_empty(db_session: AsyncSession, family: Family):
    """Test listing rules when none exist"""
    rules = await CategorizationRuleService.list_rules(db_session, family.id)
    assert rules == []


@pytest.mark.asyncio
async def test_list_rules_all(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test listing all rules"""
    rule1_data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="test1",
        priority=5,
    )
    rule2_data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="contains",
        match_field="description",
        pattern="test2",
        priority=10,
    )
    rule1 = await CategorizationRuleService.create(db_session, family.id, rule1_data)
    rule2 = await CategorizationRuleService.create(db_session, family.id, rule2_data)

    rules = await CategorizationRuleService.list_rules(db_session, family.id)

    assert len(rules) == 2
    # Rules should be ordered by priority DESC, then created_at ASC
    assert rules[0].id == rule2.id  # Higher priority (10) first
    assert rules[1].id == rule1.id


@pytest.mark.asyncio
async def test_list_rules_enabled_only(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test listing only enabled rules"""
    rule1_data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="test1",
        enabled=True,
    )
    rule2_data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="contains",
        match_field="description",
        pattern="test2",
        enabled=False,
    )
    rule1 = await CategorizationRuleService.create(db_session, family.id, rule1_data)
    rule2 = await CategorizationRuleService.create(db_session, family.id, rule2_data)

    enabled_rules = await CategorizationRuleService.list_rules(db_session, family.id, enabled_only=True)

    assert len(enabled_rules) == 1
    assert enabled_rules[0].id == rule1.id


# ============================================================================
# PATTERN MATCHING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_match_pattern_exact_case_insensitive():
    """Test exact matching is case-insensitive"""
    assert CategorizationRuleService._match_pattern("Trader Joe's", "TRADER JOE'S", "exact")
    assert CategorizationRuleService._match_pattern("trader joe's", "Trader Joe's", "exact")
    assert CategorizationRuleService._match_pattern("Trader Joe's", "Different Store", "exact") is False


@pytest.mark.asyncio
async def test_match_pattern_contains_case_insensitive():
    """Test contains matching is case-insensitive"""
    assert CategorizationRuleService._match_pattern("trader", "TRADER JOE'S", "contains")
    assert CategorizationRuleService._match_pattern("TRADER", "trader joe's", "contains")
    assert CategorizationRuleService._match_pattern("grocery", "TRADER JOE'S", "contains") is False


@pytest.mark.asyncio
async def test_match_pattern_startswith_case_insensitive():
    """Test startswith matching is case-insensitive"""
    assert CategorizationRuleService._match_pattern("trader", "TRADER JOE'S", "startswith")
    assert CategorizationRuleService._match_pattern("TRADER", "trader joe's", "startswith")
    assert CategorizationRuleService._match_pattern("joe", "TRADER JOE'S", "startswith") is False


@pytest.mark.asyncio
async def test_match_pattern_regex_case_insensitive():
    """Test regex matching is case-insensitive"""
    assert CategorizationRuleService._match_pattern(r"trader.*\d+", "Trader 123 Store", "regex")
    assert CategorizationRuleService._match_pattern(r"TRADER.*\d+", "trader 456 grocery", "regex")
    assert CategorizationRuleService._match_pattern(r"^\d+", "123 Store", "regex")


@pytest.mark.asyncio
async def test_match_pattern_regex_invalid():
    """Test invalid regex returns False"""
    assert CategorizationRuleService._match_pattern("[invalid(regex", "text", "regex") is False


# ============================================================================
# RULE MATCHING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_match_rule_payee_field():
    """Test matching on payee field only"""
    rule = BudgetCategorizationRule(
        rule_type="exact",
        match_field="payee",
        pattern="Whole Foods",
    )
    assert CategorizationRuleService._match_rule(rule, payee="Whole Foods", description="Weekly groceries") is True
    assert CategorizationRuleService._match_rule(rule, payee="Trader Joe's", description="Weekly groceries") is False
    assert CategorizationRuleService._match_rule(rule, payee=None, description="Whole Foods") is False


@pytest.mark.asyncio
async def test_match_rule_description_field():
    """Test matching on description field only"""
    rule = BudgetCategorizationRule(
        rule_type="contains",
        match_field="description",
        pattern="grocery",
    )
    assert CategorizationRuleService._match_rule(rule, payee="Store", description="Weekly grocery shopping") is True
    assert CategorizationRuleService._match_rule(rule, payee="grocery store", description=None) is False
    assert CategorizationRuleService._match_rule(rule, payee="Store", description="Weekly purchase") is False


@pytest.mark.asyncio
async def test_match_rule_both_field_either_matches():
    """Test 'both' match field matches if either payee or description matches"""
    rule = BudgetCategorizationRule(
        rule_type="exact",
        match_field="both",
        pattern="Whole Foods",
    )
    # Payee matches
    assert CategorizationRuleService._match_rule(rule, payee="Whole Foods", description="Other") is True
    # Description matches
    assert CategorizationRuleService._match_rule(rule, payee="Other", description="Whole Foods") is True
    # Neither matches
    assert CategorizationRuleService._match_rule(rule, payee="Other", description="Other") is False


# ============================================================================
# SUGGEST CATEGORY TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_suggest_category_no_rules(db_session: AsyncSession, family: Family):
    """Test suggesting category when no rules exist"""
    result = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="Whole Foods", description="Groceries"
    )
    assert result is None


@pytest.mark.asyncio
async def test_suggest_category_no_match(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test suggesting category when no rules match"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="Specific Store",
    )
    await CategorizationRuleService.create(db_session, family.id, data)

    result = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="Different Store", description="Groceries"
    )
    assert result is None


@pytest.mark.asyncio
async def test_suggest_category_payee_match(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test suggesting category from payee match"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="Whole Foods",
    )
    rule = await CategorizationRuleService.create(db_session, family.id, data)

    result = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="Whole Foods", description="Groceries"
    )
    assert result == category.id


@pytest.mark.asyncio
async def test_suggest_category_description_match(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test suggesting category from description match"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="contains",
        match_field="description",
        pattern="grocery",
    )
    await CategorizationRuleService.create(db_session, family.id, data)

    result = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="Generic Store", description="Weekly grocery shopping"
    )
    assert result == category.id


@pytest.mark.asyncio
async def test_suggest_category_priority_ordering(db_session: AsyncSession, family: Family, category: BudgetCategory, other_category: BudgetCategory):
    """Test that higher priority rules are matched first"""
    # Create low priority rule for category
    low_priority_data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="contains",
        match_field="payee",
        pattern="store",
        priority=5,
    )
    # Create high priority rule for other_category
    high_priority_data = CategorizationRuleCreate(
        category_id=other_category.id,
        rule_type="contains",
        match_field="payee",
        pattern="store",
        priority=10,
    )
    await CategorizationRuleService.create(db_session, family.id, low_priority_data)
    await CategorizationRuleService.create(db_session, family.id, high_priority_data)

    # Should return other_category (higher priority)
    result = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="Any store", description="Something"
    )
    assert result == other_category.id


@pytest.mark.asyncio
async def test_suggest_category_disabled_rules_ignored(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test that disabled rules are not matched"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="Whole Foods",
        enabled=False,
    )
    await CategorizationRuleService.create(db_session, family.id, data)

    result = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="Whole Foods", description="Groceries"
    )
    assert result is None


@pytest.mark.asyncio
async def test_suggest_category_no_payee_or_description(db_session: AsyncSession, family: Family):
    """Test suggesting category with no payee or description returns None"""
    result = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee=None, description=None
    )
    assert result is None


@pytest.mark.asyncio
async def test_suggest_category_case_insensitive(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test that suggestion matching is case-insensitive"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="exact",
        match_field="payee",
        pattern="Whole Foods",
    )
    await CategorizationRuleService.create(db_session, family.id, data)

    # Should match despite different case
    result = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="WHOLE FOODS", description="Groceries"
    )
    assert result == category.id


@pytest.mark.asyncio
async def test_suggest_category_regex_pattern(db_session: AsyncSession, family: Family, category: BudgetCategory):
    """Test suggesting category with regex pattern"""
    data = CategorizationRuleCreate(
        category_id=category.id,
        rule_type="regex",
        match_field="payee",
        pattern=r"^(WHOLE|TRADER).*",
    )
    await CategorizationRuleService.create(db_session, family.id, data)

    result1 = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="WHOLE FOODS MARKET", description="Groceries"
    )
    result2 = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="TRADER JOE'S", description="Groceries"
    )
    result3 = await CategorizationRuleService.suggest_category(
        db_session, family.id, payee="RANDOM STORE", description="Groceries"
    )

    assert result1 == category.id
    assert result2 == category.id
    assert result3 is None
