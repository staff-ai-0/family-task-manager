"""JarvisPendingAction model — HITL gate for destructive MCP tool calls.

When Jarvis calls a destructive tool (e.g. budget_account_delete), the dispatch
layer does NOT execute it inline.  Instead it inserts a JarvisPendingAction row
and emits an SSE ``confirm`` event.  The parent then approves or rejects via
POST /api/jarvis/actions/{id}/approve|reject, which re-runs dispatch under a
verified family context.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class JarvisPendingAction(Base):
    __tablename__ = "jarvis_pending_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="chk_jarvis_pending_action_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optional: Jarvis conversation message that triggered this action
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jarvis_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_name = Column(String(128), nullable=False)
    params = Column(JSONB, nullable=False, default=dict)
    summary = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
