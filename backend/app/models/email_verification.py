"""
Email Verification Token Model

Stores tokens for email verification and password reset.
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import backref, relationship
from datetime import datetime, timedelta, timezone, timezone
import uuid
import secrets

from app.core.database import Base


class EmailVerificationToken(Base):
    """Email verification token model"""
    __tablename__ = "email_verification_tokens"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationship. delete-orphan + passive_deletes: without it, deleting a
    # User whose unconsumed token is present would make the ORM NULL out
    # user_id (NOT NULL violation) instead of letting the row be removed —
    # broke parent 'reject pending member' and member deletion of
    # never-verified accounts. The DB FK already has ON DELETE CASCADE.
    user = relationship(
        "User",
        backref=backref(
            "verification_tokens",
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )
    
    @staticmethod
    def generate_token() -> str:
        """Generate a secure random token"""
        return secrets.token_urlsafe(32)
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired"""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not used and not expired)"""
        return not self.is_used and not self.is_expired
    
    def mark_as_used(self) -> None:
        """Mark token as used"""
        self.is_used = True
        self.used_at = datetime.now(timezone.utc)
    
    def __repr__(self):
        return f"<EmailVerificationToken(user_id={self.user_id}, is_used={self.is_used})>"
