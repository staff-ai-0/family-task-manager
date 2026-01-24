"""
Tests for base_service helper functions

Tests the query helper functions added in Phase 3:
- verify_user_in_family()
- get_user_by_id()
"""

import pytest
from uuid import uuid4

from app.services.base_service import verify_user_in_family, get_user_by_id
from app.core.exceptions import NotFoundException


@pytest.mark.asyncio
class TestVerifyUserInFamily:
    """Test verify_user_in_family helper function"""

    async def test_verify_user_exists_in_family(
        self, db_session, test_parent_user, test_family
    ):
        """Test verifying a user that exists and belongs to the family"""
        # Should not raise an exception
        user = await verify_user_in_family(
            db=db_session, user_id=test_parent_user.id, family_id=test_family.id
        )

        assert user is not None
        assert user.id == test_parent_user.id
        assert user.family_id == test_family.id
        assert user.email == test_parent_user.email

    async def test_verify_user_not_found(self, db_session, test_family):
        """Test verifying a user that doesn't exist"""
        non_existent_user_id = uuid4()

        with pytest.raises(NotFoundException) as exc_info:
            await verify_user_in_family(
                db=db_session, user_id=non_existent_user_id, family_id=test_family.id
            )

        assert "not found" in str(exc_info.value).lower()
        assert "does not belong to this family" in str(exc_info.value).lower()

    async def test_verify_user_wrong_family(self, db_session, test_parent_user):
        """Test verifying a user with wrong family ID"""
        wrong_family_id = uuid4()

        with pytest.raises(NotFoundException) as exc_info:
            await verify_user_in_family(
                db=db_session, user_id=test_parent_user.id, family_id=wrong_family_id
            )

        assert "not found" in str(exc_info.value).lower()

    async def test_verify_child_user_in_family(
        self, db_session, test_child_user, test_family
    ):
        """Test verifying a child user that belongs to the family"""
        user = await verify_user_in_family(
            db=db_session, user_id=test_child_user.id, family_id=test_family.id
        )

        assert user is not None
        assert user.id == test_child_user.id
        assert user.family_id == test_family.id
        assert user.role == "child"


@pytest.mark.asyncio
class TestGetUserById:
    """Test get_user_by_id helper function"""

    async def test_get_existing_user(self, db_session, test_parent_user):
        """Test getting a user that exists"""
        user = await get_user_by_id(db=db_session, user_id=test_parent_user.id)

        assert user is not None
        assert user.id == test_parent_user.id
        assert user.email == test_parent_user.email

    async def test_get_nonexistent_user(self, db_session):
        """Test getting a user that doesn't exist"""
        non_existent_user_id = uuid4()

        with pytest.raises(NotFoundException) as exc_info:
            await get_user_by_id(db=db_session, user_id=non_existent_user_id)

        assert "user not found" in str(exc_info.value).lower()

    async def test_get_child_user(self, db_session, test_child_user):
        """Test getting a child user"""
        user = await get_user_by_id(db=db_session, user_id=test_child_user.id)

        assert user is not None
        assert user.id == test_child_user.id
        assert user.role == "child"

    async def test_get_user_returns_correct_data(self, db_session, test_parent_user):
        """Test that get_user_by_id returns all expected user data"""
        user = await get_user_by_id(db=db_session, user_id=test_parent_user.id)

        # Verify all important attributes are present
        assert hasattr(user, "id")
        assert hasattr(user, "email")
        assert hasattr(user, "name")
        assert hasattr(user, "role")
        assert hasattr(user, "family_id")
        assert hasattr(user, "points")

        # Verify values match
        assert user.email == test_parent_user.email
        assert user.name == test_parent_user.name
        assert user.family_id == test_parent_user.family_id
