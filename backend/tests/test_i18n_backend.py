"""Guards for backend i18n wiring (register language + Jarvis language)."""

import pytest


def test_register_family_request_carries_preferred_lang():
    from app.schemas.user import RegisterFamilyRequest
    r = RegisterFamilyRequest(family_name="F", name="N", email="a@b.com",
                              password="password123", preferred_lang="es")
    assert r.preferred_lang == "es"
    # defaults to en
    r2 = RegisterFamilyRequest(family_name="F", name="N", email="c@d.com",
                               password="password123")
    assert r2.preferred_lang == "en"


def test_register_family_request_rejects_bad_lang():
    from app.schemas.user import RegisterFamilyRequest
    with pytest.raises(Exception):
        RegisterFamilyRequest(family_name="F", name="N", email="a@b.com",
                              password="password123", preferred_lang="fr")


def test_jarvis_system_prompt_has_language_directive():
    from app.services.jarvis_service import _build_system
    es = _build_system("CTX", "es")
    en = _build_system("CTX", "en")
    assert "Spanish" in es and "CTX" in es
    assert "English" in en
    # unknown lang falls back to English, never crashes
    assert "English" in _build_system("CTX", "zz")


def test_jarvis_empty_reply_localized():
    from app.services.jarvis_service import _EMPTY_REPLY
    assert _EMPTY_REPLY["es"].startswith("No tengo")
    assert _EMPTY_REPLY["en"]


@pytest.mark.asyncio
async def test_register_family_sets_spanish_user(client):
    """End-to-end: registering with preferred_lang=es stores a Spanish user so
    the welcome email + first login render in Spanish."""
    r = await client.post("/api/auth/register-family", json={
        "family_name": "Familia ES", "name": "Papa", "email": "papa-es@test.com",
        "password": "password123", "preferred_lang": "es",
    })
    assert r.status_code in (200, 201), r.text
    assert r.json()["user"]["preferred_lang"] == "es"
