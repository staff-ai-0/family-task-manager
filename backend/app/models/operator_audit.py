"""Append-only record of every platform-operator action.

Deliberately carries NO foreign keys. An audit row must outlive every row it
references: a FK with ON DELETE CASCADE would erase the record of a family
deletion at purge time, and one without a delete rule would block the purge
sweep outright. actor_email is denormalized for the same reason.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class OperatorAuditLog(Base):
    """One row per attempted operator action, successful or not."""

    __tablename__ = "operator_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id = Column(UUID(as_uuid=True), nullable=False)
    actor_email = Column(String(255), nullable=False)
    action = Column(String(64), nullable=False, index=True)
    target_family_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    target_user_id = Column(UUID(as_uuid=True), nullable=True)
    params = Column(JSONB, nullable=True)
    result = Column(String(16), nullable=False, default="ok")
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    def __repr__(self):
        return (
            f"<OperatorAuditLog(action={self.action}, "
            f"actor={self.actor_email}, result={self.result})>"
        )
