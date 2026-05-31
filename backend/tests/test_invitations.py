"""
Tests for the Family Invitations API
"""
import pytest
from datetime import datetime, timedelta, timezone
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
            "role": "parent",
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
            "role": "parent",
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
            "role": "parent",
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
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
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
                "role": "parent",
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
            "role": "parent",
        },
        headers=auth_headers,
    )
    
    invitation_id = send_response.json()["id"]
    
    # Cancel invitation
    cancel_response = await client.delete(
        f"/api/invitations/{test_family.id}/{invitation_id}",
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
                "role": "parent",
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


@pytest.mark.asyncio
async def test_resend_invitation_success(
    client, test_family, test_parent_user, db_session: AsyncSession, auth_headers
):
    """Resending a pending invitation returns 200 and refreshes its expiry."""
    send = await client.post(
        "/api/invitations/send",
        json={"email": "resend-me@example.com", "family_id": str(test_family.id), "role": "parent"},
        headers=auth_headers,
    )
    assert send.status_code == status.HTTP_201_CREATED
    inv_id = send.json()["id"]
    old_expiry = send.json()["expires_at"]

    resp = await client.post(
        f"/api/invitations/{test_family.id}/{inv_id}/resend",
        headers=auth_headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["id"] == inv_id
    assert body["invited_email"] == "resend-me@example.com"
    # expiry refreshed forward (or at least not earlier)
    assert body["expires_at"] >= old_expiry


@pytest.mark.asyncio
async def test_resend_invitation_requires_auth(client, test_family):
    """Resend requires authentication."""
    import uuid
    resp = await client.post(
        f"/api/invitations/{test_family.id}/{uuid.uuid4()}/resend",
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_invitation_email_link_uses_frontend_origin(
    test_family, test_parent_user, db_session: AsyncSession, monkeypatch
):
    """Regression: the acceptance link in the invite email must point at the
    public *frontend* origin (PUBLIC_URL), not the API origin (BASE_URL).

    The /accept-invitation page is an Astro frontend route — building the link
    from BASE_URL (the API domain) produced a dead 404 link in production.
    """
    from app.services.email_service import EmailService
    from app.core.config import settings

    # API origin vs frontend origin, as configured in production.
    monkeypatch.setattr(settings, "BASE_URL", "https://api-gcp-family.agent-ia.mx")
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://gcp-family.agent-ia.mx")

    captured = {}

    async def _fake_send(*, to, subject, html):
        captured["to"] = to
        captured["html"] = html
        return True

    monkeypatch.setattr(EmailService, "_send", staticmethod(_fake_send))

    invitation = FamilyInvitation(
        family_id=test_family.id,
        invited_email="adult@example.com",
        invited_by_user_id=test_parent_user.id,
        invitation_code=FamilyInvitation.generate_code(),
        role="parent",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
    )

    ok = await EmailService.send_invitation_email(
        db=db_session,
        invitation=invitation,
        inviting_user=test_parent_user,
        base_url=settings.email_link_base,
    )

    assert ok is True
    html = captured["html"]
    assert "https://gcp-family.agent-ia.mx/accept-invitation?code=" in html
    # Must NOT leak the API origin into a user-facing link.
    assert "api-gcp-family.agent-ia.mx/accept-invitation" not in html


@pytest.mark.asyncio
async def test_send_prefers_smtp_over_resend(monkeypatch):
    """When SMTP_* is configured, _send must use Workspace SMTP (not Resend),
    authenticate as SMTP_USER, STARTTLS, and send From the EMAIL_FROM address."""
    import smtplib
    from app.services.email_service import EmailService
    from app.core.config import settings

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USER", "info@agent-ia.mx")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "app-pw")
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(settings, "EMAIL_FROM", "info@agent-ia.mx")
    # Resend present too — SMTP must still win.
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_should_not_be_used")

    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            seen["host"], seen["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            seen["tls"] = True

        def login(self, user, password):
            seen["login"] = (user, password)

        def send_message(self, msg):
            seen["from"] = msg["From"]
            seen["to"] = msg["To"]
            seen["parts"] = [p.get_content_type() for p in msg.walk()]

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    ok = await EmailService._send(to="dest@example.com", subject="Hi", html="<b>x</b>")

    assert ok is True
    assert seen["host"] == "smtp.gmail.com" and seen["port"] == 587
    assert seen["tls"] is True
    assert seen["login"] == ("info@agent-ia.mx", "app-pw")
    assert "info@agent-ia.mx" in seen["from"]
    assert seen["to"] == "dest@example.com"
    # multipart/alternative with both a text and an html part
    assert "text/plain" in seen["parts"] and "text/html" in seen["parts"]
