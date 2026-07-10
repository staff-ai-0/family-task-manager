"""Email links must build from the FRONTEND origin (email_link_base).

Regression: POST /api/auth/register ("Register new member") passed
settings.BASE_URL — the API origin (api-family.agent-ia.mx in prod) — so the
verification email linked to a host with no /verify-email page. Report:
"emails go to api-family, not family.agent-ia.mx".
"""

import pytest

from app.core.config import settings
from app.services.email_service import EmailService


@pytest.mark.asyncio
async def test_register_member_verification_email_uses_frontend_origin(
    client, db_session, test_family, test_parent_user, monkeypatch
):
    captured = {}

    async def fake_send_verification_email(db, user, base_url="", **kwargs):
        captured["base_url"] = base_url
        return True

    monkeypatch.setattr(
        EmailService,
        "send_verification_email",
        staticmethod(fake_send_verification_email),
    )
    # Simulate prod: API origin differs from the public frontend origin.
    monkeypatch.setattr(settings, "BASE_URL", "https://api-family.example.mx")
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://family.example.mx")

    login = await client.post("/api/auth/login", json={
        "email": test_parent_user.email, "password": "password123",
    })
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    r = await client.post(
        "/api/auth/register",
        json={
            "email": "new-kid@test.com",
            "name": "New Kid",
            "password": "password123",
            "role": "child",
            "family_id": str(test_family.id),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert captured["base_url"] == "https://family.example.mx"
