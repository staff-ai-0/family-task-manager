"""Access vs refresh token claims + typed decoding."""
import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from fastapi import HTTPException


def _decode_raw(token):
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def test_access_token_is_typed_access():
    tok = create_access_token({"sub": "u1"})
    assert _decode_raw(tok)["type"] == "access"


def test_refresh_token_carries_type_and_version():
    tok = create_refresh_token("u1", version=3)
    claims = _decode_raw(tok)
    assert claims["type"] == "refresh"
    assert claims["ver"] == 3
    assert claims["sub"] == "u1"
    assert "jti" in claims


def test_decode_token_rejects_wrong_type():
    refresh = create_refresh_token("u1", version=0)
    with pytest.raises(HTTPException) as exc:
        decode_token(refresh, expected_type="access")
    assert exc.value.status_code == 401


def test_decode_token_treats_missing_type_as_access():
    # A legacy token minted without a `type` claim must still decode as access.
    legacy = jwt.encode({"sub": "u1"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    payload = decode_token(legacy, expected_type="access")
    assert payload["sub"] == "u1"
