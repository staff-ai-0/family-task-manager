"""
Tests for AuthService - Quick Wins for critical authentication flows

Covers:
- User registration edge cases
- Password update flows
- User activation/deactivation
"""

import pytest
from uuid import uuid4

from app.services.auth_service import AuthService
from app.schemas.user import UserCreate, UserLogin
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    UnauthorizedException,
)
from app.models.user import UserRole


@pytest.mark.asyncio
class TestUserRegistration:
    """Test user registration edge cases"""

    async def test_register_with_nonexistent_family(self, db_session):
        """Test registering user with family that doesn't exist"""
        user_data = UserCreate(
            email="newuser@example.com",
            name="New User",
            password="SecurePass123!",
            role=UserRole.CHILD,
            family_id=uuid4(),  # Non-existent family
        )

        with pytest.raises(NotFoundException) as exc_info:
            await AuthService.register_user(db_session, user_data)

        assert "family not found" in str(exc_info.value).lower()

    async def test_register_duplicate_email(
        self, db_session, test_parent_user, test_family
    ):
        """Test registering with an email that's already taken"""
        user_data = UserCreate(
            email=test_parent_user.email,  # Duplicate email
            name="Another User",
            password="SecurePass123!",
            role=UserRole.CHILD,
            family_id=test_family.id,
        )

        with pytest.raises(ValidationException) as exc_info:
            await AuthService.register_user(db_session, user_data)

        assert "already registered" in str(exc_info.value).lower()

    async def test_register_new_user_successfully(self, db_session, test_family):
        """Test successful user registration"""
        user_data = UserCreate(
            email="newchild@example.com",
            name="New Child",
            password="ChildPass123!",
            role=UserRole.CHILD,
            family_id=test_family.id,
        )

        user = await AuthService.register_user(db_session, user_data)

        assert user is not None
        assert user.email == "newchild@example.com"
        assert user.name == "New Child"
        assert user.role == UserRole.CHILD
        assert user.family_id == test_family.id
        assert user.points == 0
        assert user.is_active is True
        assert user.password_hash is not None
        assert user.password_hash != "ChildPass123!"  # Password should be hashed


@pytest.mark.asyncio
class TestUserAuthentication:
    """Test user authentication flows"""

    async def test_authenticate_with_wrong_password(self, db_session, test_parent_user):
        """Test login with incorrect password"""
        login_data = UserLogin(
            email=test_parent_user.email,
            password="WrongPassword123!",
        )

        with pytest.raises(UnauthorizedException) as exc_info:
            await AuthService.authenticate_user(db_session, login_data)

        assert "invalid email or password" in str(exc_info.value).lower()

    async def test_authenticate_nonexistent_user(self, db_session):
        """Test login with non-existent email"""
        login_data = UserLogin(
            email="nonexistent@example.com",
            password="SomePassword123!",
        )

        with pytest.raises(UnauthorizedException) as exc_info:
            await AuthService.authenticate_user(db_session, login_data)

        assert "invalid email or password" in str(exc_info.value).lower()

    async def test_authenticate_deactivated_user(self, db_session, test_parent_user):
        """Test authentication fails for deactivated user"""
        # Deactivate the user first
        test_parent_user.is_active = False
        await db_session.commit()

        login_data = UserLogin(
            email=test_parent_user.email,
            password="password123",
        )

        with pytest.raises(UnauthorizedException) as exc_info:
            await AuthService.authenticate_user(db_session, login_data)

        assert "deactivat" in str(exc_info.value).lower()

    async def test_authenticate_successful(self, db_session, test_parent_user):
        """Test successful authentication"""
        login_data = UserLogin(
            email=test_parent_user.email,
            password="password123",
        )

        user, access_token = await AuthService.authenticate_user(db_session, login_data)

        assert user is not None
        assert user.id == test_parent_user.id
        assert user.email == test_parent_user.email
        assert access_token is not None
        assert isinstance(access_token, str)
        assert len(access_token) > 0


@pytest.mark.asyncio
class TestPasswordUpdate:
    """Test password update flows"""

    async def test_update_password_with_wrong_current(
        self, db_session, test_parent_user
    ):
        """Test updating password with incorrect current password"""
        with pytest.raises(ValidationException) as exc_info:
            await AuthService.update_password(
                db_session,
                test_parent_user.id,
                current_password="WrongPassword123!",
                new_password="NewPassword123!",
            )

        assert "current password is incorrect" in str(exc_info.value).lower()

    async def test_update_password_for_nonexistent_user(self, db_session):
        """Test updating password for non-existent user"""
        with pytest.raises(NotFoundException):
            await AuthService.update_password(
                db_session,
                uuid4(),
                current_password="OldPassword123!",
                new_password="NewPassword123!",
            )

    async def test_update_password_successfully(self, db_session, test_parent_user):
        """Test successful password update"""
        new_password = "NewSecurePass456!"
        
        user = await AuthService.update_password(
            db_session,
            test_parent_user.id,
            current_password="password123",
            new_password=new_password,
        )

        assert user is not None
        assert user.id == test_parent_user.id
        
        # Verify old password no longer works
        from app.core.security import verify_password
        assert not verify_password("password123", user.password_hash)
        
        # Verify new password works
        assert verify_password(new_password, user.password_hash)

    async def test_update_password_and_login(self, db_session, test_parent_user):
        """Test that user can login with new password after update"""
        new_password = "UpdatedPassword789!"
        
        # Update password
        await AuthService.update_password(
            db_session,
            test_parent_user.id,
            current_password="password123",
            new_password=new_password,
        )

        # Try to login with new password
        login_data = UserLogin(
            email=test_parent_user.email,
            password=new_password,
        )
        
        user, token = await AuthService.authenticate_user(db_session, login_data)
        
        assert user is not None
        assert token is not None


@pytest.mark.asyncio
class TestUserActivation:
    """Test user activation/deactivation flows"""

    async def test_deactivate_user(self, db_session, test_child_user):
        """Test deactivating a user account"""
        assert test_child_user.is_active is True

        user = await AuthService.deactivate_user(db_session, test_child_user.id)

        assert user.is_active is False
        assert user.id == test_child_user.id

    async def test_deactivate_nonexistent_user(self, db_session):
        """Test deactivating non-existent user"""
        with pytest.raises(NotFoundException):
            await AuthService.deactivate_user(db_session, uuid4())

    async def test_activate_user(self, db_session, test_child_user):
        """Test activating a user account"""
        # First deactivate
        test_child_user.is_active = False
        await db_session.commit()

        user = await AuthService.activate_user(db_session, test_child_user.id)

        assert user.is_active is True
        assert user.id == test_child_user.id

    async def test_activate_nonexistent_user(self, db_session):
        """Test activating non-existent user"""
        with pytest.raises(NotFoundException):
            await AuthService.activate_user(db_session, uuid4())

    async def test_deactivate_then_reactivate(self, db_session, test_child_user):
        """Test full deactivation and reactivation cycle"""
        original_state = test_child_user.is_active
        assert original_state is True

        # Deactivate
        user = await AuthService.deactivate_user(db_session, test_child_user.id)
        assert user.is_active is False

        # Reactivate
        user = await AuthService.activate_user(db_session, test_child_user.id)
        assert user.is_active is True
        assert user.is_active == original_state


@pytest.mark.asyncio
class TestGetUserById:
    """Test getting user by ID"""

    async def test_get_user_by_id_success(self, db_session, test_parent_user):
        """Test getting existing user"""
        user = await AuthService.get_user_by_id(db_session, test_parent_user.id)

        assert user is not None
        assert user.id == test_parent_user.id
        assert user.email == test_parent_user.email

    async def test_get_user_by_id_not_found(self, db_session):
        """Test getting non-existent user"""
        with pytest.raises(NotFoundException) as exc_info:
            await AuthService.get_user_by_id(db_session, uuid4())

        assert "user not found" in str(exc_info.value).lower()
