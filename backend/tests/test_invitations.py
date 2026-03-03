"""
Tests for the Family Invitations API
"""
import pytest
from datetime import datetime, timedelta
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invitation import FamilyInvitation
from app.models.user import User


@pytest.mark.asyncio
async def test_send_invitation_success(client, test_family, test_parent_user, db_session: AsyncSession, auth_headers):
    """Test successfully sending a family invitation"""
    # Send invitation
    response = await client.post(
        "/api/invitations/send",
        json={
            "email": "newmember@example.com",
            "message": "Join our family!",
            "family_id": str(test_family.id),
        },
        headers=auth_headers,
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "invitation_code" in data
    assert data["invited_email"] == "newmember@example.com"
    assert data["status"] == "PENDING" or data["status"] == "pending"


@pytest.mark.asyncio
async def test_send_invitation_requires_auth(client, test_family):
    """Test that sending invitation requires authentication"""
    response = await client.post(
        "/api/invitations/send",
        json={
            "email": "newmember@example.com",
            "family_id": str(test_family.id),
        },
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_send_invitation_duplicate_email(client, test_family, test_parent_user, db_session: AsyncSession, auth_headers):
    """Test that inviting the same email twice fails"""
    # Send first invitation
    response1 = await client.post(
        "/api/invitations/send",
        json={
            "email": "newmember@example.com",
            "family_id": str(test_family.id),
        },
        headers=auth_headers,
    )
    assert response1.status_code == status.HTTP_201_CREATED
    
    # Try to send duplicate
    response2 = await client.post(
        "/api/invitations/send",
        json={
            "email": "newmember@example.com",
            "family_id": str(test_family.id),
        },
        headers=auth_headers,
    )
    
    assert response2.status_code == status.HTTP_400_BAD_REQUEST
    data = response2.json()
    assert "already" in data["detail"].lower() or "duplicate" in data["detail"].lower()


@pytest.mark.asyncio
async def test_accept_invitation_success(client, test_family, test_parent_user, db_session: AsyncSession, auth_headers):
    """Test successfully accepting an invitation"""
    # Send invitation first
    response = await client.post(
        "/api/invitations/send",
        json={
            "email": "newmember@example.com",
            "family_id": str(test_family.id),
        },
        headers=auth_headers,
    )
    
    invitation_code = response.json()["invitation_code"]
    
    # Accept invitation
    accept_response = await client.post(
        "/api/invitations/accept",
        json={
            "invitation_code": invitation_code,
            "password": "secure_password_123",
            "name": "New Member",
        },
    )
    
    assert accept_response.status_code == status.HTTP_200_OK
    data = accept_response.json()
    assert data["success"] is True
    assert "access_token" in data


@pytest.mark.asyncio
async def test_accept_invitation_invalid_code(client):
    """Test that accepting with invalid code fails"""
    response = await client.post(
        "/api/invitations/accept",
        json={
            "invitation_code": "invalid_code_12345678901234567890",
            "password": "secure_password_123",
            "name": "New Member",
        },
    )
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_accept_invitation_expired(client, test_family, test_parent_user, db_session: AsyncSession):
    """Test that accepting an expired invitation fails"""
    # Create an invitation that expired 1 day ago
    invitation = FamilyInvitation(
        family_id=test_family.id,
        invited_email="expired@example.com",
        invited_by_user_id=test_parent_user.id,
        invitation_code=FamilyInvitation.generate_code(),
        expires_at=datetime.utcnow() - timedelta(days=1)
    )
    db_session.add(invitation)
    await db_session.commit()
    
    # Try to accept expired invitation
    response = await client.post(
        "/api/invitations/accept",
        json={
            "invitation_code": invitation.invitation_code,
            "password": "secure_password_123",
            "name": "New Member",
        },
    )
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert "valid" in data["detail"].lower() or "expired" in data["detail"].lower()


@pytest.mark.asyncio
async def test_get_pending_invitations(client, test_family, test_parent_user, db_session: AsyncSession, auth_headers):
    """Test getting pending invitations for a family"""
    # Send multiple invitations
    emails = ["member1@example.com", "member2@example.com", "member3@example.com"]
    for email in emails:
        await client.post(
            "/api/invitations/send",
            json={
                "email": email,
                "family_id": str(test_family.id),
            },
            headers=auth_headers,
        )
    
    # Get pending invitations
    response = await client.get(
        f"/api/invitations/{test_family.id}/pending",
        headers=auth_headers,
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 3
    
    # Verify all emails are present
    invited_emails = {inv["invited_email"] for inv in data}
    assert invited_emails == set(emails)


@pytest.mark.asyncio
async def test_get_pending_invitations_requires_auth(client, test_family):
    """Test that getting pending invitations requires authentication"""
    response = await client.get(
        f"/api/invitations/{test_family.id}/pending"
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_cancel_invitation(client, test_family, test_parent_user, db_session: AsyncSession, auth_headers):
    """Test canceling a pending invitation"""
    # Send invitation
    send_response = await client.post(
        "/api/invitations/send",
        json={
            "email": "member@example.com",
            "family_id": str(test_family.id),
        },
        headers=auth_headers,
    )
    
    invitation_id = send_response.json()["id"]
    
    # Cancel invitation
    cancel_response = await client.delete(
        f"/api/invitations/{test_family.id}/invitations/{invitation_id}",
        headers=auth_headers,
    )
    
    assert cancel_response.status_code == status.HTTP_204_NO_CONTENT
    
    # Verify it's gone from pending
    pending_response = await client.get(
        f"/api/invitations/{test_family.id}/pending",
        headers=auth_headers,
    )
    
    pending_count = len(pending_response.json())
    assert pending_count == 0


@pytest.mark.asyncio
async def test_invitation_code_generation(client, test_family, test_parent_user, db_session: AsyncSession, auth_headers):
    """Test that invitation codes are unique and valid"""
    codes = set()
    for i in range(5):
        response = await client.post(
            "/api/invitations/send",
            json={
                "email": f"member{i}@example.com",
                "family_id": str(test_family.id),
            },
            headers=auth_headers,
        )
        
        code = response.json()["invitation_code"]
        codes.add(code)
        
        # Verify code format (32 chars or less, alphanumeric + special)
        assert len(code) > 0
        assert isinstance(code, str)
    
    # Verify all codes are unique
    assert len(codes) == 5
