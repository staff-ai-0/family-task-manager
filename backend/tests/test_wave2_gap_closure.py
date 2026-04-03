"""
Tests for Wave 2 Budget Gap Closure features:
- Feature 4: Saved Transaction Filters
- Feature 5: Advanced Rule Actions
- Feature 6: Tags
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from datetime import date

from app.models.budget import (
    BudgetCategorizationRule,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetAccount,
    BudgetTransaction,
    BudgetSavedFilter,
    BudgetTag,
    BudgetTransactionTag,
)
from app.services.budget.categorization_rule_service import CategorizationRuleService


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def budget_group(db_session: AsyncSession, test_family):
    """Create a category group for tests."""
    group = BudgetCategoryGroup(
        family_id=test_family.id,
        name="Test Group",
        sort_order=0,
    )
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    return group


@pytest_asyncio.fixture
async def budget_category(db_session: AsyncSession, test_family, budget_group):
    """Create a budget category."""
    cat = BudgetCategory(
        family_id=test_family.id,
        group_id=budget_group.id,
        name="Groceries",
        sort_order=0,
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return cat


@pytest_asyncio.fixture
async def budget_category_2(db_session: AsyncSession, test_family, budget_group):
    """Create a second budget category."""
    cat = BudgetCategory(
        family_id=test_family.id,
        group_id=budget_group.id,
        name="Utilities",
        sort_order=1,
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return cat


@pytest_asyncio.fixture
async def budget_account(db_session: AsyncSession, test_family):
    """Create a budget account."""
    acct = BudgetAccount(
        family_id=test_family.id,
        name="Checking",
        type="checking",
    )
    db_session.add(acct)
    await db_session.commit()
    await db_session.refresh(acct)
    return acct


@pytest_asyncio.fixture
async def budget_transaction(db_session: AsyncSession, test_family, budget_account, budget_category):
    """Create a budget transaction."""
    txn = BudgetTransaction(
        family_id=test_family.id,
        account_id=budget_account.id,
        category_id=budget_category.id,
        date=date(2026, 3, 15),
        amount=-5000,
        notes="Original note",
    )
    db_session.add(txn)
    await db_session.commit()
    await db_session.refresh(txn)
    return txn


# =============================================================================
# FEATURE 4: SAVED TRANSACTION FILTERS
# =============================================================================

class TestSavedFiltersAPI:
    """Test saved filter CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_saved_filter(self, client: AsyncClient, auth_headers):
        """Parent can create a saved filter."""
        resp = await client.post(
            "/api/budget/saved-filters/",
            json={
                "name": "High Value",
                "conditions": [{"field": "amount", "operator": "gt", "value": 10000}],
                "conditions_op": "and",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "High Value"
        assert len(data["conditions"]) == 1
        assert data["conditions_op"] == "and"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_list_saved_filters(self, client: AsyncClient, auth_headers):
        """List saved filters for the family."""
        # Create two
        await client.post(
            "/api/budget/saved-filters/",
            json={"name": "Filter A", "conditions": [{"field": "amount", "operator": "gt", "value": 100}]},
            headers=auth_headers,
        )
        await client.post(
            "/api/budget/saved-filters/",
            json={"name": "Filter B", "conditions": [{"field": "payee", "operator": "eq", "value": "Oxxo"}]},
            headers=auth_headers,
        )
        resp = await client.get("/api/budget/saved-filters/", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    @pytest.mark.asyncio
    async def test_get_saved_filter(self, client: AsyncClient, auth_headers):
        """Get a saved filter by ID."""
        create_resp = await client.post(
            "/api/budget/saved-filters/",
            json={"name": "My Filter", "conditions": []},
            headers=auth_headers,
        )
        filter_id = create_resp.json()["id"]
        resp = await client.get(f"/api/budget/saved-filters/{filter_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "My Filter"

    @pytest.mark.asyncio
    async def test_update_saved_filter(self, client: AsyncClient, auth_headers):
        """Parent can update a saved filter."""
        create_resp = await client.post(
            "/api/budget/saved-filters/",
            json={"name": "Old Name", "conditions": []},
            headers=auth_headers,
        )
        filter_id = create_resp.json()["id"]
        resp = await client.put(
            f"/api/budget/saved-filters/{filter_id}",
            json={"name": "New Name"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_delete_saved_filter(self, client: AsyncClient, auth_headers):
        """Parent can delete a saved filter."""
        create_resp = await client.post(
            "/api/budget/saved-filters/",
            json={"name": "To Delete", "conditions": []},
            headers=auth_headers,
        )
        filter_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/budget/saved-filters/{filter_id}", headers=auth_headers)
        assert resp.status_code == 204

        # Verify deleted
        resp = await client.get(f"/api/budget/saved-filters/{filter_id}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_child_cannot_create_filter(self, client: AsyncClient, test_child_user):
        """Child users cannot create saved filters."""
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": "child@test.com", "password": "password123"},
        )
        token = login_resp.json()["access_token"]
        child_headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            "/api/budget/saved-filters/",
            json={"name": "Not allowed", "conditions": []},
            headers=child_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_filter_not_found(self, client: AsyncClient, auth_headers):
        """Getting a non-existent filter returns 404."""
        resp = await client.get(
            f"/api/budget/saved-filters/{uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_conditions_op_or(self, client: AsyncClient, auth_headers):
        """Can create a filter with 'or' conditions_op."""
        resp = await client.post(
            "/api/budget/saved-filters/",
            json={
                "name": "Multi",
                "conditions": [
                    {"field": "amount", "operator": "gt", "value": 100},
                    {"field": "payee", "operator": "eq", "value": "Oxxo"},
                ],
                "conditions_op": "or",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["conditions_op"] == "or"


# =============================================================================
# FEATURE 5: ADVANCED RULE ACTIONS
# =============================================================================

class TestAdvancedRuleActions:
    """Test advanced rule actions on categorization rules."""

    @pytest.mark.asyncio
    async def test_create_rule_with_actions(
        self, client: AsyncClient, auth_headers, budget_category
    ):
        """Create a rule with advanced actions."""
        resp = await client.post(
            "/api/budget/categorization-rules/",
            json={
                "category_id": str(budget_category.id),
                "rule_type": "contains",
                "match_field": "payee",
                "pattern": "oxxo",
                "actions": [
                    {"field": "category", "operation": "set", "value": str(budget_category.id)},
                    {"field": "notes", "operation": "set", "value": "Auto-categorized"},
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["actions"] is not None
        assert len(data["actions"]) == 2

    @pytest.mark.asyncio
    async def test_create_rule_without_actions(
        self, client: AsyncClient, auth_headers, budget_category
    ):
        """Create a rule without actions (backward compat)."""
        resp = await client.post(
            "/api/budget/categorization-rules/",
            json={
                "category_id": str(budget_category.id),
                "rule_type": "exact",
                "match_field": "payee",
                "pattern": "CFE",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["actions"] is None

    @pytest.mark.asyncio
    async def test_update_rule_actions(
        self, client: AsyncClient, auth_headers, budget_category
    ):
        """Update a rule to add actions."""
        create_resp = await client.post(
            "/api/budget/categorization-rules/",
            json={
                "category_id": str(budget_category.id),
                "rule_type": "contains",
                "match_field": "payee",
                "pattern": "test",
            },
            headers=auth_headers,
        )
        rule_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/budget/categorization-rules/{rule_id}",
            json={
                "actions": [
                    {"field": "notes", "operation": "append", "value": " [auto]"},
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["actions"] is not None

    @pytest.mark.asyncio
    async def test_apply_rule_legacy_no_actions(
        self, db_session: AsyncSession, test_family, budget_category, budget_category_2, budget_account
    ):
        """apply_rule with no actions falls back to setting category_id."""
        rule = BudgetCategorizationRule(
            family_id=test_family.id,
            category_id=budget_category_2.id,
            rule_type="contains",
            match_field="payee",
            pattern="oxxo",
            actions=None,
        )
        db_session.add(rule)
        await db_session.commit()

        txn = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            category_id=budget_category.id,
            date=date(2026, 3, 15),
            amount=-1000,
        )
        db_session.add(txn)
        await db_session.commit()

        result = await CategorizationRuleService.apply_rule(db_session, txn, rule)
        assert result.category_id == budget_category_2.id

    @pytest.mark.asyncio
    async def test_apply_rule_set_notes(
        self, db_session: AsyncSession, test_family, budget_category, budget_account
    ):
        """apply_rule can set notes."""
        rule = BudgetCategorizationRule(
            family_id=test_family.id,
            category_id=budget_category.id,
            rule_type="contains",
            match_field="payee",
            pattern="oxxo",
            actions=[{"field": "notes", "operation": "set", "value": "Auto note"}],
        )
        db_session.add(rule)
        await db_session.commit()

        txn = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            date=date(2026, 3, 15),
            amount=-500,
            notes="Old note",
        )
        db_session.add(txn)
        await db_session.commit()

        result = await CategorizationRuleService.apply_rule(db_session, txn, rule)
        assert result.notes == "Auto note"

    @pytest.mark.asyncio
    async def test_apply_rule_append_notes(
        self, db_session: AsyncSession, test_family, budget_category, budget_account
    ):
        """apply_rule can append to notes."""
        rule = BudgetCategorizationRule(
            family_id=test_family.id,
            category_id=budget_category.id,
            rule_type="contains",
            match_field="payee",
            pattern="test",
            actions=[{"field": "notes", "operation": "append", "value": " [tagged]"}],
        )
        db_session.add(rule)
        await db_session.commit()

        txn = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            date=date(2026, 3, 15),
            amount=-500,
            notes="Existing",
        )
        db_session.add(txn)
        await db_session.commit()

        result = await CategorizationRuleService.apply_rule(db_session, txn, rule)
        assert result.notes == "Existing [tagged]"

    @pytest.mark.asyncio
    async def test_apply_rule_prepend_notes(
        self, db_session: AsyncSession, test_family, budget_category, budget_account
    ):
        """apply_rule can prepend to notes."""
        rule = BudgetCategorizationRule(
            family_id=test_family.id,
            category_id=budget_category.id,
            rule_type="contains",
            match_field="payee",
            pattern="test",
            actions=[{"field": "notes", "operation": "prepend", "value": "[auto] "}],
        )
        db_session.add(rule)
        await db_session.commit()

        txn = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            date=date(2026, 3, 15),
            amount=-500,
            notes="Some note",
        )
        db_session.add(txn)
        await db_session.commit()

        result = await CategorizationRuleService.apply_rule(db_session, txn, rule)
        assert result.notes == "[auto] Some note"

    @pytest.mark.asyncio
    async def test_apply_rule_set_category_via_action(
        self, db_session: AsyncSession, test_family, budget_category, budget_category_2, budget_account
    ):
        """apply_rule can set category via action."""
        rule = BudgetCategorizationRule(
            family_id=test_family.id,
            category_id=budget_category.id,
            rule_type="contains",
            match_field="payee",
            pattern="test",
            actions=[{"field": "category", "operation": "set", "value": str(budget_category_2.id)}],
        )
        db_session.add(rule)
        await db_session.commit()

        txn = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            category_id=budget_category.id,
            date=date(2026, 3, 15),
            amount=-500,
        )
        db_session.add(txn)
        await db_session.commit()

        result = await CategorizationRuleService.apply_rule(db_session, txn, rule)
        assert result.category_id == budget_category_2.id

    @pytest.mark.asyncio
    async def test_apply_rule_multiple_actions(
        self, db_session: AsyncSession, test_family, budget_category, budget_category_2, budget_account
    ):
        """apply_rule applies multiple actions in order."""
        rule = BudgetCategorizationRule(
            family_id=test_family.id,
            category_id=budget_category.id,
            rule_type="contains",
            match_field="payee",
            pattern="test",
            actions=[
                {"field": "category", "operation": "set", "value": str(budget_category_2.id)},
                {"field": "notes", "operation": "set", "value": "Multi-action"},
            ],
        )
        db_session.add(rule)
        await db_session.commit()

        txn = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            date=date(2026, 3, 15),
            amount=-500,
        )
        db_session.add(txn)
        await db_session.commit()

        result = await CategorizationRuleService.apply_rule(db_session, txn, rule)
        assert result.category_id == budget_category_2.id
        assert result.notes == "Multi-action"


# =============================================================================
# FEATURE 6: TAGS
# =============================================================================

class TestTagsAPI:
    """Test tag CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_tag(self, client: AsyncClient, auth_headers):
        """Parent can create a tag."""
        resp = await client.post(
            "/api/budget/tags/",
            json={"name": "Groceries", "color": "#4CAF50"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Groceries"
        assert data["color"] == "#4CAF50"

    @pytest.mark.asyncio
    async def test_list_tags(self, client: AsyncClient, auth_headers):
        """List all tags for the family."""
        await client.post("/api/budget/tags/", json={"name": "Tag A"}, headers=auth_headers)
        await client.post("/api/budget/tags/", json={"name": "Tag B"}, headers=auth_headers)
        resp = await client.get("/api/budget/tags/", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    @pytest.mark.asyncio
    async def test_update_tag(self, client: AsyncClient, auth_headers):
        """Parent can update a tag."""
        create_resp = await client.post(
            "/api/budget/tags/",
            json={"name": "Old Tag"},
            headers=auth_headers,
        )
        tag_id = create_resp.json()["id"]
        resp = await client.put(
            f"/api/budget/tags/{tag_id}",
            json={"name": "Renamed Tag", "color": "#FF0000"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed Tag"
        assert resp.json()["color"] == "#FF0000"

    @pytest.mark.asyncio
    async def test_delete_tag(self, client: AsyncClient, auth_headers):
        """Parent can delete a tag."""
        create_resp = await client.post(
            "/api/budget/tags/",
            json={"name": "To Delete"},
            headers=auth_headers,
        )
        tag_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/budget/tags/{tag_id}", headers=auth_headers)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_child_cannot_create_tag(self, client: AsyncClient, test_child_user):
        """Child users cannot create tags."""
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": "child@test.com", "password": "password123"},
        )
        token = login_resp.json()["access_token"]
        child_headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            "/api/budget/tags/",
            json={"name": "Not allowed"},
            headers=child_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_tag_no_color(self, client: AsyncClient, auth_headers):
        """Can create a tag without color."""
        resp = await client.post(
            "/api/budget/tags/",
            json={"name": "Plain"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["color"] is None


class TestTransactionTags:
    """Test transaction-tag association endpoints."""

    @pytest.mark.asyncio
    async def test_set_and_get_transaction_tags(
        self, client: AsyncClient, auth_headers, budget_transaction
    ):
        """Set tags on a transaction and retrieve them."""
        # Create tags
        tag1_resp = await client.post(
            "/api/budget/tags/",
            json={"name": "Urgent", "color": "#F00"},
            headers=auth_headers,
        )
        tag2_resp = await client.post(
            "/api/budget/tags/",
            json={"name": "Reviewed"},
            headers=auth_headers,
        )
        tag1_id = tag1_resp.json()["id"]
        tag2_id = tag2_resp.json()["id"]

        txn_id = str(budget_transaction.id)

        # Set tags
        resp = await client.put(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            json={"tag_ids": [tag1_id, tag2_id]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

        # Get tags
        resp = await client.get(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        tag_names = {t["name"] for t in resp.json()}
        assert "Urgent" in tag_names
        assert "Reviewed" in tag_names

    @pytest.mark.asyncio
    async def test_replace_transaction_tags(
        self, client: AsyncClient, auth_headers, budget_transaction
    ):
        """Setting tags replaces existing ones."""
        tag1_resp = await client.post(
            "/api/budget/tags/", json={"name": "First"}, headers=auth_headers
        )
        tag2_resp = await client.post(
            "/api/budget/tags/", json={"name": "Second"}, headers=auth_headers
        )
        txn_id = str(budget_transaction.id)

        # Set first tag
        await client.put(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            json={"tag_ids": [tag1_resp.json()["id"]]},
            headers=auth_headers,
        )

        # Replace with second tag
        await client.put(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            json={"tag_ids": [tag2_resp.json()["id"]]},
            headers=auth_headers,
        )

        resp = await client.get(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            headers=auth_headers,
        )
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "Second"

    @pytest.mark.asyncio
    async def test_clear_transaction_tags(
        self, client: AsyncClient, auth_headers, budget_transaction
    ):
        """Setting empty tag list clears all tags."""
        tag_resp = await client.post(
            "/api/budget/tags/", json={"name": "Temp"}, headers=auth_headers
        )
        txn_id = str(budget_transaction.id)

        # Set a tag
        await client.put(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            json={"tag_ids": [tag_resp.json()["id"]]},
            headers=auth_headers,
        )

        # Clear tags
        await client.put(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            json={"tag_ids": []},
            headers=auth_headers,
        )

        resp = await client.get(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            headers=auth_headers,
        )
        assert len(resp.json()) == 0

    @pytest.mark.asyncio
    async def test_set_tags_invalid_transaction(self, client: AsyncClient, auth_headers):
        """Setting tags on a non-existent transaction returns 404."""
        resp = await client.put(
            f"/api/budget/tags/transactions/{uuid4()}/tags",
            json={"tag_ids": []},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_set_tags_invalid_tag_id(
        self, client: AsyncClient, auth_headers, budget_transaction
    ):
        """Setting tags with invalid tag ID returns 400/422."""
        txn_id = str(budget_transaction.id)
        resp = await client.put(
            f"/api/budget/tags/transactions/{txn_id}/tags",
            json={"tag_ids": [str(uuid4())]},
            headers=auth_headers,
        )
        # ValidationException mapped to 400
        assert resp.status_code == 400
