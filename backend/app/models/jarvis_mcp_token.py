"""JarvisMcpToken — per-family bearer tokens for the external /mcp HTTP transport.

Each token is minted once; only the SHA-256 hash is stored.  The plaintext is
shown to the user at creation time and never again.  Revocation sets
``revoked_at``; ``TokenService.resolve`` returns None for revoked rows.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class JarvisMcpToken(Base):
    __tablename__ = "jarvis_mcp_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    label = Column(String(128), nullable=False)
    # SHA-256 hex digest of the plaintext secret — never stored in plaintext.
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    # First 8 chars of the plaintext secret (e.g. "mcp_a1b2") shown in UI.
    token_prefix = Column(String(8), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
