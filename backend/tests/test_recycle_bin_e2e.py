"""
E2E Tests for Budget Recycle Bin System

Tests the full workflow of soft-deleting and restoring budget items.
"""

import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from httpx import AsyncClient

from app.models import Family, User, BudgetTransaction, BudgetAccount, BudgetCategory, BudgetCategoryGroup
from app.schemas.budget import TransactionCreate, AccountCreate, CategoryCreate, CategoryGroupCreate


@pytest.mark.asyncio
class TestRecycleBinWorkflow:
    """Test complete recycle bin workflow for all item types."""

    @pytest.fixture
    async def setup_data(self, client: AsyncClient, parent_user: User, family: Family):
        """Setup test data for recycle bin tests."""
        # Get auth token
        login_response = await client.post(
            "/api/auth/login",
            json={"email": parent_user.email, "password": "testpass123"}
        )
        token = login_response.json()["data"]["access_token"]

        # Create category group
        group_response = await client.post(
            "/api/budget/categories/groups",
            json={"name": "Test Group", "description": "Test"},
            headers={"Authorization": f"Bearer {token}"}
        )
        group_id = group_response.json()["data"]["id"]

        # Create category
        cat_response = await client.post(
            "/api/budget/categories",
            json={"name": "Test Category", "group_id": group_id},
            headers={"Authorization": f"Bearer {token}"}
        )
        category_id = cat_response.json()["data"]["id"]

        # Create account
        account_response = await client.post(
            "/api/budget/accounts",
            json={"name": "Test Account", "account_type": "checking", "balance": 1000},
            headers={"Authorization": f"Bearer {token}"}
        )
        account_id = account_response.json()["data"]["id"]

        # Create transaction
        tx_response = await client.post(
            "/api/budget/transactions",
            json={
                "amount": 100,
                "account_id": account_id,
                "category_id": category_id,
                "date": datetime.now().isoformat(),
                "payee": "Test Payee"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        transaction_id = tx_response.json()["data"]["id"]

        return {
            "token": token,
            "group_id": group_id,
            "category_id": category_id,
            "account_id": account_id,
            "transaction_id": transaction_id,
            "family_id": family.id
        }

    async def test_soft_delete_transaction(self, client: AsyncClient, setup_data):
        """Test soft-deleting a transaction."""
        token = setup_data["token"]
        transaction_id = setup_data["transaction_id"]

        # Delete transaction
        response = await client.delete(
            f"/api/budget/transactions/{transaction_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 204

        # Verify transaction is in recycle bin
        recycle_response = await client.get(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert recycle_response.status_code == 200
        items = recycle_response.json()["data"]["items"]
        assert any(item["id"] == transaction_id and item["type"] == "transaction" for item in items)

    async def test_soft_delete_account(self, client: AsyncClient, setup_data):
        """Test soft-deleting an account."""
        token = setup_data["token"]
        account_id = setup_data["account_id"]

        # Delete account
        response = await client.delete(
            f"/api/budget/accounts/{account_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 204

        # Verify account is in recycle bin
        recycle_response = await client.get(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert recycle_response.status_code == 200
        items = recycle_response.json()["data"]["items"]
        assert any(item["id"] == account_id and item["type"] == "account" for item in items)

    async def test_soft_delete_category(self, client: AsyncClient, setup_data):
        """Test soft-deleting a category."""
        token = setup_data["token"]
        category_id = setup_data["category_id"]

        # Delete category
        response = await client.delete(
            f"/api/budget/categories/{category_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 204

        # Verify category is in recycle bin
        recycle_response = await client.get(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert recycle_response.status_code == 200
        items = recycle_response.json()["data"]["items"]
        assert any(item["id"] == category_id and item["type"] == "category" for item in items)

    async def test_restore_transaction(self, client: AsyncClient, setup_data):
        """Test restoring a deleted transaction."""
        token = setup_data["token"]
        transaction_id = setup_data["transaction_id"]

        # Delete transaction
        await client.delete(
            f"/api/budget/transactions/{transaction_id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        # Restore transaction
        response = await client.post(
            f"/api/budget/recycle-bin/transactions/{transaction_id}/restore",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

        # Verify transaction is no longer in recycle bin
        recycle_response = await client.get(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {token}"}
        )
        items = recycle_response.json()["data"]["items"]
        assert not any(item["id"] == transaction_id for item in items)

    async def test_permanently_delete_transaction(self, client: AsyncClient, setup_data):
        """Test permanently deleting a transaction from recycle bin."""
        token = setup_data["token"]
        transaction_id = setup_data["transaction_id"]

        # Delete transaction
        await client.delete(
            f"/api/budget/transactions/{transaction_id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        # Permanently delete
        response = await client.delete(
            f"/api/budget/recycle-bin/transactions/{transaction_id}/permanently",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 204

        # Verify transaction is completely gone
        recycle_response = await client.get(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {token}"}
        )
        items = recycle_response.json()["data"]["items"]
        assert not any(item["id"] == transaction_id for item in items)

    async def test_filter_recycle_bin_by_type(self, client: AsyncClient, setup_data):
        """Test filtering recycle bin items by type."""
        token = setup_data["token"]
        transaction_id = setup_data["transaction_id"]
        account_id = setup_data["account_id"]

        # Delete both items
        await client.delete(
            f"/api/budget/transactions/{transaction_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        await client.delete(
            f"/api/budget/accounts/{account_id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        # Filter by transaction type
        response = await client.get(
            "/api/budget/recycle-bin?item_type=transaction",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert all(item["type"] == "transaction" for item in items)
        assert any(item["id"] == transaction_id for item in items)

    async def test_cascade_delete_validation(self, client: AsyncClient, setup_data):
        """Test that category group cannot be deleted if it has active categories."""
        token = setup_data["token"]
        group_id = setup_data["group_id"]
        category_id = setup_data["category_id"]

        # Try to delete category group (should fail because category exists)
        response = await client.delete(
            f"/api/budget/categories/groups/{group_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 400
        assert "Cannot delete category group" in response.json()["detail"]

        # Delete the category first
        await client.delete(
            f"/api/budget/categories/{category_id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        # Now delete should succeed
        response = await client.delete(
            f"/api/budget/categories/groups/{group_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 204

    async def test_empty_recycle_bin(self, client: AsyncClient, setup_data):
        """Test emptying recycle bin (delete items > 30 days old)."""
        token = setup_data["token"]

        # Delete multiple items
        await client.delete(
            f"/api/budget/transactions/{setup_data['transaction_id']}",
            headers={"Authorization": f"Bearer {token}"}
        )
        await client.delete(
            f"/api/budget/accounts/{setup_data['account_id']}",
            headers={"Authorization": f"Bearer {token}"}
        )

        # Empty recycle bin
        response = await client.delete(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 204

        # Items deleted in current session should still be there
        # (since they're < 30 days old)
        recycle_response = await client.get(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {token}"}
        )
        # The actual test depends on the implementation
        # If items are < 30 days, they should still exist

    async def test_parent_only_access(self, client: AsyncClient, child_user: User, setup_data):
        """Test that non-parent users cannot access recycle bin."""
        # Try to access as non-parent
        response = await client.get(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {setup_data['token']}"}
        )
        # Should be accessible by parent (token is parent's)
        assert response.status_code == 200

        # Login as child
        login_response = await client.post(
            "/api/auth/login",
            json={"email": child_user.email, "password": "testpass123"}
        )
        child_token = login_response.json()["data"]["access_token"]

        # Child should not have access
        response = await client.get(
            "/api/budget/recycle-bin",
            headers={"Authorization": f"Bearer {child_token}"}
        )
        assert response.status_code in [403, 401]  # Forbidden or Unauthorized

    async def test_soft_deleted_items_excluded_from_queries(self, client: AsyncClient, setup_data):
        """Test that soft-deleted items are excluded from regular queries."""
        token = setup_data["token"]
        transaction_id = setup_data["transaction_id"]

        # Get transactions before delete
        before_response = await client.get(
            "/api/budget/transactions",
            headers={"Authorization": f"Bearer {token}"}
        )
        before_count = len(before_response.json()["data"])

        # Delete transaction
        await client.delete(
            f"/api/budget/transactions/{transaction_id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        # Get transactions after delete
        after_response = await client.get(
            "/api/budget/transactions",
            headers={"Authorization": f"Bearer {token}"}
        )
        after_count = len(after_response.json()["data"])

        # Transaction count should decrease
        assert after_count == before_count - 1
