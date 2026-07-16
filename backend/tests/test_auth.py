"""
Tests for User Authentication
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


class TestUserRegistration:
    """Parent-only member registration.

    /api/auth/register adds a member to the authenticated PARENT's family.
    The body family_id is ignored (cross-tenant escalation fixed 2026-06-04);
    public self-signup goes through /api/auth/register-family instead.
    """

    @staticmethod
    async def _parent_token(client: AsyncClient) -> str:
        r = await client.post(
            "/api/auth/login",
            json={"email": "parent@test.com", "password": "password123"},
        )
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    @pytest.mark.asyncio
    async def test_register_new_user(self, client: AsyncClient, test_parent_user):
        """A parent adds a new member to their family."""
        token = await self._parent_token(client)
        response = await client.post(
            "/api/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "newuser@test.com",
                "password": "SecurePass123!",
                "name": "New User",
                "family_id": str(test_parent_user.family_id),
                "role": "child",
            },
        )

        assert response.status_code == 201, response.text
        data = response.json()
        assert data["email"] == "newuser@test.com"
        assert data["name"] == "New User"
        assert "id" in data
        assert "password" not in data

    @pytest.mark.asyncio
    async def test_register_family_captures_browser_timezone(self, client, db):
        """A founding family stores the browser IANA timezone; garbage → UTC."""
        from sqlalchemy import select
        from app.models.family import Family

        ok = await client.post("/api/auth/register-family", json={
            "family_name": "TZ Family", "name": "Founder",
            "email": "tzfounder@test.com", "password": "SecurePass123!",
            "preferred_lang": "es", "accept_terms": True,
            "timezone": "America/Mexico_City",
        })
        assert ok.status_code in (200, 201), ok.text
        fam = (await db.execute(
            select(Family).where(Family.name == "TZ Family")
        )).scalar_one()
        assert fam.timezone == "America/Mexico_City"

        bad = await client.post("/api/auth/register-family", json={
            "family_name": "Bad TZ", "name": "F2",
            "email": "badtz@test.com", "password": "SecurePass123!",
            "preferred_lang": "en", "accept_terms": True,
            "timezone": "Not/AZone",
        })
        assert bad.status_code in (200, 201), bad.text
        fam2 = (await db.execute(
            select(Family).where(Family.name == "Bad TZ")
        )).scalar_one()
        assert fam2.timezone == "UTC"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(
        self, client: AsyncClient, test_parent_user
    ):
        """Registering an already-used email is rejected."""
        token = await self._parent_token(client)
        response = await client.post(
            "/api/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": test_parent_user.email,
                "password": "SecurePass123!",
                "name": "Duplicate User",
                "family_id": str(test_parent_user.family_id),
                "role": "child",
            },
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_register_invalid_email(
        self, client: AsyncClient, test_parent_user
    ):
        """Invalid email format is rejected with 422."""
        token = await self._parent_token(client)
        response = await client.post(
            "/api/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "not-an-email",
                "password": "SecurePass123!",
                "name": "Invalid User",
                "family_id": str(test_parent_user.family_id),
                "role": "child",
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


class TestCheckAuthMethods:
    """Tests for POST /api/auth/check-methods (used by email-match Google redirect)"""

    @pytest.mark.asyncio
    async def test_password_only_user(self, client: AsyncClient, test_parent_user):
        """Password-only user → has_password True, has_google False"""
        response = await client.post(
            "/api/auth/check-methods",
            json={"email": test_parent_user.email},
        )
        assert response.status_code == 200
        data = response.json()
        assert data == {"has_password": True, "has_google": False}

    @pytest.mark.asyncio
    async def test_google_only_user(
        self, client: AsyncClient, db_session: AsyncSession, test_family
    ):
        """Google-only user (no password_hash) → has_password False, has_google True"""
        from app.models.user import User, UserRole

        user = User(
            email="googleonly@test.com",
            password_hash=None,
            name="Google Only",
            role=UserRole.PARENT,
            family_id=test_family.id,
            oauth_provider="google",
            oauth_id="google-sub-1234",
            email_verified=True,
        )
        db_session.add(user)
        await db_session.commit()

        response = await client.post(
            "/api/auth/check-methods",
            json={"email": "googleonly@test.com"},
        )
        assert response.status_code == 200
        assert response.json() == {"has_password": False, "has_google": True}

    @pytest.mark.asyncio
    async def test_linked_user_has_both(
        self, client: AsyncClient, db_session: AsyncSession, test_family
    ):
        """User with both password and linked Google → both True"""
        from app.models.user import User, UserRole
        from app.core.security import get_password_hash

        user = User(
            email="linked@test.com",
            password_hash=get_password_hash("password123"),
            name="Linked User",
            role=UserRole.PARENT,
            family_id=test_family.id,
            oauth_provider="google",
            oauth_id="google-sub-5678",
            email_verified=True,
        )
        db_session.add(user)
        await db_session.commit()

        response = await client.post(
            "/api/auth/check-methods",
            json={"email": "linked@test.com"},
        )
        assert response.status_code == 200
        assert response.json() == {"has_password": True, "has_google": True}

    @pytest.mark.asyncio
    async def test_unknown_email(self, client: AsyncClient):
        """Unknown email → both False (does NOT 404, to avoid enumeration-via-status)"""
        response = await client.post(
            "/api/auth/check-methods",
            json={"email": "nobody@test.com"},
        )
        assert response.status_code == 200
        assert response.json() == {"has_password": False, "has_google": False}

    @pytest.mark.asyncio
    async def test_invalid_email_format(self, client: AsyncClient):
        """Invalid email format → 422 from Pydantic validator"""
        response = await client.post(
            "/api/auth/check-methods",
            json={"email": "not-an-email"},
        )
        assert response.status_code == 422


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
        """Parent can permanently delete a child — via the gated flow:
        deactivate first, then delete with typed-name confirmation (a
        one-click hard delete once destroyed a real account)."""
        # Login as parent
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # One-click delete is refused (member still active, no confirmation)
        response = await client.delete(
            f"/api/users/{test_child_user.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

        # Gated flow: deactivate, then delete with typed confirmation
        response = await client.put(
            f"/api/users/{test_child_user.id}/deactivate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        response = await client.delete(
            f"/api/users/{test_child_user.id}?confirm=Test%20Child",
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
