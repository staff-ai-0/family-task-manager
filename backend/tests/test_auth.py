"""
Tests for User Authentication
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


class TestUserRegistration:
    """Test user registration functionality"""

    @pytest.mark.asyncio
    async def test_register_new_user(self, client: AsyncClient, test_family):
        """Test registering a new user"""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "newuser@test.com",
                "password": "SecurePass123!",
                "name": "New User",
                "family_id": str(test_family.id),
                "role": "child",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@test.com"
        assert data["name"] == "New User"
        assert "id" in data
        assert "password" not in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(
        self, client: AsyncClient, test_parent_user, test_family
    ):
        """Test registering with an email that already exists"""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": test_parent_user.email,
                "password": "SecurePass123!",
                "name": "Duplicate User",
                "family_id": str(test_family.id),
                "role": "child",
            },
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        """Test registering with invalid email format"""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "not-an-email",
                "password": "SecurePass123!",
                "name": "Invalid User",
                "family_name": "Test Family",
            },
        )

        assert response.status_code == 422  # Validation error


class TestUserLogin:
    """Test user login functionality"""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, test_parent_user):
        """Test successful login"""
        response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, test_parent_user):
        """Test login with wrong password"""
        response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "wrongpassword"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with non-existent email"""
        response = await client.post(
            "/api/auth/login",
            json={"email": "nonexistent@test.com", "password": "password123"},
        )

        assert response.status_code == 401


class TestProtectedEndpoints:
    """Test protected endpoints require authentication"""

    @pytest.mark.asyncio
    async def test_access_without_token(self, client: AsyncClient):
        """Test accessing protected endpoint without token"""
        response = await client.get("/api/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_access_with_valid_token(self, client: AsyncClient, test_parent_user):
        """Test accessing protected endpoint with valid token"""
        # Login first
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Access protected endpoint
        response = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_parent_user.email


class TestUserDeletion:
    """Test user deletion functionality"""

    @pytest.mark.asyncio
    async def test_parent_can_delete_child(
        self, client: AsyncClient, test_parent_user, test_child_user
    ):
        """Test that parent can delete a child user"""
        # Login as parent
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Delete child user
        response = await client.delete(
            f"/api/users/{test_child_user.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 204

        # Verify user is deleted (try to get user should fail)
        get_response = await client.get(
            f"/api/users/{test_child_user.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_parent_cannot_delete_self(
        self, client: AsyncClient, test_parent_user
    ):
        """Test that parent cannot delete themselves"""
        # Login as parent
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Try to delete self
        response = await client.delete(
            f"/api/users/{test_parent_user.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400
        assert "cannot delete your own account" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_child_cannot_delete_users(
        self, client: AsyncClient, test_child_user, test_parent_user
    ):
        """Test that child cannot delete users"""
        # Login as child
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_child_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Try to delete parent user
        response = await client.delete(
            f"/api/users/{test_parent_user.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403  # Forbidden

    @pytest.mark.asyncio
    async def test_delete_nonexistent_user(
        self, client: AsyncClient, test_parent_user
    ):
        """Test deleting a user that doesn't exist"""
        # Login as parent
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Try to delete non-existent user
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/users/{fake_uuid}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
