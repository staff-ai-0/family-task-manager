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


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    """Replace secret-looking values with a fixed marker.

    The audit log is read by a human during incident review; a leaked token
    or password in it would be a second incident.
    """
    return {
        k: ("***" if k.lower() in _SECRET_KEYS else v) for k, v in params.items()
    }


class OperatorAuditService:
    """Writes the append-only operator trail."""

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
            error=error,
        )
        db.add(row)
        return row
