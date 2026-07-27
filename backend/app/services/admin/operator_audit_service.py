"""Staging of operator audit rows."""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operator_audit import OperatorAuditLog
from app.models.user import User

# Parameter names whose values must never reach the audit log verbatim.
_SECRET_KEYS = frozenset(
    {"password", "new_password", "token", "secret", "access_token", "refresh_token"}
)

# Every `error=` value is truncated to this many characters before it is
# persisted. `error` is normally `str(exc)` from a bare `except Exception`
# (see AdminActionService._record_failure) — for a DBAPIError raised inside
# EmailService.create_verification_token / create_password_reset_token,
# that string includes the SQL statement AND its bound parameters, i.e. the
# freshly-minted verification/reset token, which would otherwise live
# forever in an append-only, human-readable audit log. A hard length cap is
# a blunt instrument (it does not guarantee the token never falls inside
# the kept prefix), but it bounds the blast radius without needing this
# service to understand every exception type's string shape, and it caps
# what gets rendered verbatim on /admin/audit either way.
_ERROR_MAX_LEN = 500


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    """Replace secret-looking values with a fixed marker.

    The audit log is read by a human during incident review; a leaked token
    or password in it would be a second incident.
    """
    return {
        k: ("***" if k.lower() in _SECRET_KEYS else v) for k, v in params.items()
    }


class OperatorAuditService:
    """Writes the append-only operator trail.

    ``error`` is truncated (not just ``params``) — see ``_ERROR_MAX_LEN``.
    The truncation happens HERE, once, rather than at each call site: call
    sites pass whatever `str(exc)` gives them, and every one of them is
    covered automatically, including future ones that forget this rule
    exists.
    """

    @staticmethod
    def record(
        db: AsyncSession,
        *,
        actor: User,
        action: str,
        target_family_id: Optional[UUID] = None,
        target_user_id: Optional[UUID] = None,
        params: Optional[dict[str, Any]] = None,
        result: str = "ok",
        error: Optional[str] = None,
    ) -> OperatorAuditLog:
        """Stage an audit row on the CALLER'S session.

        Deliberately does not commit. The row must land in the same
        transaction as the mutation it describes, so a rolled-back mutation
        cannot leave an "ok" audit row behind, and a committed mutation
        cannot go unrecorded.
        """
        row = OperatorAuditLog(
            actor_user_id=actor.id,
            actor_email=actor.email,
            action=action,
            target_family_id=target_family_id,
            target_user_id=target_user_id,
            params=_redact(params or {}),
            result=result,
            error=error[:_ERROR_MAX_LEN] if error else error,
        )
        db.add(row)
        return row
