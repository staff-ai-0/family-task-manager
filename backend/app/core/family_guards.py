"""One place to decide whether a family may still be served.

`get_current_user` enforces both conditions for session auth, but the app has
four other authenticated entry points that never go through it — the kiosk
device token, the Jarvis MCP bearer token, and the a2a bank-sync HMAC. Each had
grown its own partial check, so operator suspension (`is_active = False`) was
honoured on the session path and silently ignored on all of them, even though
the super-admin design promises suspension "locks out all members immediately".

Any new token-authenticated surface should call this rather than re-deriving
the rule.
"""
from typing import Optional

from fastapi import HTTPException, status

from app.models.family import Family


def assert_family_usable(family: Optional[Family]) -> None:
    """Raise 401 when a family is closed or suspended.

    A missing family is left to the caller: some paths legitimately treat an
    absent row as "not registered" (404) rather than "unauthenticated".
    """
    if family is None:
        return
    if family.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account closed",
        )
    if family.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Family suspended",
        )
