"""
Tests for advanced budget service methods:
- PayeeService.merge_payees, get_last_category
- CategoryService.delete_with_reassign
- CategorizationRuleService.apply_all_rules, suggest_new_rules
"""

import pytest
import pytest_asyncio
from datetime import date
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.budget import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetPayee,
    BudgetTransaction,
    BudgetCategorizationRule,
)
from app.services.budget.payee_service import PayeeService
from app.services.budget.category_service import CategoryService, CategoryGroupService
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.services.budget.account_service import AccountService
from app.schemas.budget import (
    PayeeCreate,
    CategoryGroupCreate,
    CategoryCreate,
    AccountCreate,
    CategorizationRuleCreate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_account(db: AsyncSession, family_id) -> BudgetAccount:
    """Create a checking account for test transactions."""
    return await AccountService.create(
        db, family_id, AccountCreate(name="Test Checking", type="checking")
    )


async def _create_group_and_category(
    db: AsyncSession, family_id, group_name: str = "Expenses", cat_name: str = "Groceries"
) -> tuple[BudgetCategoryGroup, BudgetCategory]:
    group = await CategoryGroupService.create(
        db, family_id, CategoryGroupCreate(name=group_name)
    )
    category = await CategoryService.create(
        db, family_id, CategoryCreate(name=cat_name, group_id=group.id)
    )
    return group, category


async def _create_payee(db: AsyncSession, family_id, name: str) -> BudgetPayee:
    return await PayeeService.create(db, family_id, PayeeCreate(name=name))


async def _add_transaction(
    db: AsyncSession,
    family_id,
    account_id,
    *,
    payee_id=None,
    category_id=None,
    amount: int = -1000,
    txn_date: date | None = None,
    notes: str | None = None,
) -> BudgetTransaction:
    """Insert a transaction directly (bypasses month-locking)."""
    txn = BudgetTransaction(
        id=uuid4(),
        family_id=family_id,
        account_id=account_id,
        payee_id=payee_id,
        category_id=category_id,
        amount=amount,
        date=txn_date or date(2026, 3, 15),
        notes=notes,
    )
    db.add(txn)
    await db.flush()
    return txn


# ===========================================================================
# PayeeService.merge_payees
# ===========================================================================

class TestMergePayees:

    @pytest.mark.asyncio
    async def test_transactions_reassigned_to_target(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Merging payees should reassign all source transactions to the target."""
        account = await _create_account(db, family_id)
        source = await _create_payee(db, family_id, "Source Payee")
        target = await _create_payee(db, family_id, "Target Payee")

        # Two transactions on source, one on target
        txn1 = await _add_transaction(db, family_id, account.id, payee_id=source.id, amount=-500)
        txn2 = await _add_transaction(db, family_id, account.id, payee_id=source.id, amount=-300)
        txn3 = await _add_transaction(db, family_id, account.id, payee_id=target.id, amount=-200)
        await db.commit()

        result = await PayeeService.merge_payees(db, family_id, source.id, target.id)

        assert result["merged_count"] == 2
        assert result["source_name"] == "Source Payee"
        assert result["target_name"] == "Target Payee"

        # Verify transactions are now on target
        await db.refresh(txn1)
        await db.refresh(txn2)
        await db.refresh(txn3)
        assert txn1.payee_id == target.id
        assert txn2.payee_id == target.id
        assert txn3.payee_id == target.id  # was already on target

    @pytest.mark.asyncio
    async def test_source_payee_deleted_after_merge(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """The source payee should no longer exist after merging."""
        account = await _create_account(db, family_id)
        source = await _create_payee(db, family_id, "Doomed Payee")
        target = await _create_payee(db, family_id, "Surviving Payee")

        await _add_transaction(db, family_id, account.id, payee_id=source.id)
        await db.commit()

        await PayeeService.merge_payees(db, family_id, source.id, target.id)

        # Source payee must not exist
        row = await db.execute(
            select(BudgetPayee).where(BudgetPayee.id == source.id)
        )
        assert row.scalar_one_or_none() is None

        # Target payee must still exist
        row2 = await db.execute(
            select(BudgetPayee).where(BudgetPayee.id == target.id)
        )
        assert row2.scalar_one_or_none() is not None


# ===========================================================================
# PayeeService.get_last_category
# ===========================================================================

class TestGetLastCategory:

    @pytest.mark.asyncio
    async def test_returns_category_from_latest_transaction(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Should return the category_id of the most recent transaction."""
        account = await _create_account(db, family_id)
        payee = await _create_payee(db, family_id, "Oxxo")
        _, old_cat = await _create_group_and_category(db, family_id, cat_name="Snacks")
        _, new_cat = await _create_group_and_category(db, family_id, group_name="Food", cat_name="Drinks")

        # Older transaction
        await _add_transaction(
            db, family_id, account.id,
            payee_id=payee.id, category_id=old_cat.id,
            txn_date=date(2026, 1, 10),
        )
        # Newer transaction
        await _add_transaction(
            db, family_id, account.id,
            payee_id=payee.id, category_id=new_cat.id,
            txn_date=date(2026, 3, 20),
        )
        await db.commit()

        result = await PayeeService.get_last_category(db, payee.id, family_id)
        assert result == new_cat.id

    @pytest.mark.asyncio
    async def test_returns_none_when_no_transactions(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Should return None for a payee with no transactions."""
        payee = await _create_payee(db, family_id, "Lonely Payee")
        await db.commit()

        result = await PayeeService.get_last_category(db, payee.id, family_id)
        assert result is None


# ===========================================================================
# CategoryService.delete_with_reassign
# ===========================================================================

class TestDeleteWithReassign:

    @pytest.mark.asyncio
    async def test_delete_without_reassignment(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Deleting without reassign_to_id leaves transactions uncategorized."""
        account = await _create_account(db, family_id)
        _, category = await _create_group_and_category(db, family_id)

        txn = await _add_transaction(
            db, family_id, account.id, category_id=category.id, amount=-2000
        )
        await db.commit()

        result = await CategoryService.delete_with_reassign(db, category.id, family_id)

        assert result["deleted_name"] == "Groceries"
        assert result["reassigned_count"] == 1

        await db.refresh(txn)
        assert txn.category_id is None

    @pytest.mark.asyncio
    async def test_delete_with_reassignment(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Deleting with reassign_to_id moves transactions to target category."""
        account = await _create_account(db, family_id)
        group, source_cat = await _create_group_and_category(db, family_id, cat_name="Old Cat")
        target_cat = await CategoryService.create(
            db, family_id, CategoryCreate(name="New Cat", group_id=group.id)
        )

        txn1 = await _add_transaction(
            db, family_id, account.id, category_id=source_cat.id, amount=-500
        )
        txn2 = await _add_transaction(
            db, family_id, account.id, category_id=source_cat.id, amount=-700
        )
        await db.commit()

        result = await CategoryService.delete_with_reassign(
            db, source_cat.id, family_id, reassign_to_id=target_cat.id
        )

        assert result["deleted_name"] == "Old Cat"
        assert result["reassigned_count"] == 2

        await db.refresh(txn1)
        await db.refresh(txn2)
        assert txn1.category_id == target_cat.id
        assert txn2.category_id == target_cat.id

        # Source category must be gone
        deleted = await db.execute(
            select(BudgetCategory).where(BudgetCategory.id == source_cat.id)
        )
        assert deleted.scalar_one_or_none() is None


# ===========================================================================
# CategorizationRuleService.apply_all_rules
# ===========================================================================

class TestApplyAllRules:

    @pytest.mark.asyncio
    async def test_matching_transactions_get_categorized(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Uncategorized transactions that match a rule should receive a category."""
        account = await _create_account(db, family_id)
        _, category = await _create_group_and_category(db, family_id, cat_name="Coffee")
        payee = await _create_payee(db, family_id, "Starbucks")

        # Create an exact rule: payee "Starbucks" -> Coffee
        rule = await CategorizationRuleService.create(
            db, family_id,
            CategorizationRuleCreate(
                category_id=category.id,
                rule_type="exact",
                match_field="payee",
                pattern="Starbucks",
            ),
        )

        # Uncategorized transaction matching the rule
        txn_match = await _add_transaction(
            db, family_id, account.id, payee_id=payee.id, category_id=None
        )
        # Uncategorized transaction with no payee (should not match)
        txn_no_payee = await _add_transaction(
            db, family_id, account.id, payee_id=None, category_id=None
        )
        await db.commit()

        result = await CategorizationRuleService.apply_all_rules(db, family_id)

        assert result["applied"] == 1
        assert result["skipped"] == 1

        await db.refresh(txn_match)
        assert txn_match.category_id == category.id

        await db.refresh(txn_no_payee)
        assert txn_no_payee.category_id is None

    @pytest.mark.asyncio
    async def test_already_categorized_transactions_not_affected(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Transactions that already have a category should not be changed."""
        account = await _create_account(db, family_id)
        _, cat_a = await _create_group_and_category(db, family_id, cat_name="Cat A")
        _, cat_b = await _create_group_and_category(db, family_id, group_name="G2", cat_name="Cat B")
        payee = await _create_payee(db, family_id, "Amazon")

        # Rule that maps "Amazon" -> Cat B
        await CategorizationRuleService.create(
            db, family_id,
            CategorizationRuleCreate(
                category_id=cat_b.id,
                rule_type="exact",
                match_field="payee",
                pattern="Amazon",
            ),
        )

        # Transaction already categorized as Cat A
        txn = await _add_transaction(
            db, family_id, account.id,
            payee_id=payee.id, category_id=cat_a.id,
        )
        await db.commit()

        result = await CategorizationRuleService.apply_all_rules(db, family_id)

        # Nothing should be applied (txn already categorized)
        assert result["applied"] == 0
        assert result["skipped"] == 0  # no uncategorized txns at all

        await db.refresh(txn)
        assert txn.category_id == cat_a.id  # unchanged


# ===========================================================================
# CategorizationRuleService.suggest_new_rules
# ===========================================================================

class TestSuggestNewRules:

    @pytest.mark.asyncio
    async def test_suggests_payee_with_enough_uncategorized(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Payees with >= min_count uncategorized transactions should be suggested."""
        account = await _create_account(db, family_id)
        payee = await _create_payee(db, family_id, "Walmart")

        # 3 uncategorized transactions for Walmart
        for _ in range(3):
            await _add_transaction(
                db, family_id, account.id, payee_id=payee.id, category_id=None
            )
        await db.commit()

        suggestions = await CategorizationRuleService.suggest_new_rules(
            db, family_id, min_count=2
        )

        assert len(suggestions) == 1
        assert suggestions[0]["payee_name"] == "Walmart"
        assert suggestions[0]["transaction_count"] == 3

    @pytest.mark.asyncio
    async def test_excludes_payees_with_existing_exact_rule(
        self, db: AsyncSession, test_family, test_parent_user, family_id
    ):
        """Payees that already have an exact rule should not be suggested."""
        account = await _create_account(db, family_id)
        _, category = await _create_group_and_category(db, family_id, cat_name="Supermarket")
        payee = await _create_payee(db, family_id, "Costco")

        # 5 uncategorized transactions
        for _ in range(5):
            await _add_transaction(
                db, family_id, account.id, payee_id=payee.id, category_id=None
            )

        # Create an exact rule for "Costco"
        await CategorizationRuleService.create(
            db, family_id,
            CategorizationRuleCreate(
                category_id=category.id,
                rule_type="exact",
                match_field="payee",
                pattern="Costco",
            ),
        )
        await db.commit()

        suggestions = await CategorizationRuleService.suggest_new_rules(
            db, family_id, min_count=2
        )

        # Costco should be excluded because an exact rule already exists
        payee_names = [s["payee_name"] for s in suggestions]
        assert "Costco" not in payee_names
