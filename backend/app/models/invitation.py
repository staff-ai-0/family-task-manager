"""
Family Invitation Model

Represents an invitation sent to a user to join a family.
"""

from datetime import datetime, timedelta
from uuid import uuid4, UUID
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base
from app.models.user import UserRole


class InvitationStatus(str, enum.Enum):
    """Invitation status"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class FamilyInvitation(Base):
    """Family invitation model"""
    __tablename__ = "family_invitations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(ForeignKey("families.id"), nullable=False)
    invited_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    invited_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    invitation_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(SQLEnum(InvitationStatus), default=InvitationStatus.PENDING, nullable=False)
    role: Mapped[str] = mapped_column(SQLEnum(UserRole), default=UserRole.CHILD, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # 30 days from creation
    accepted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    accepted_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Relationships
    family = relationship("Family", backref="invitations")
    invited_by = relationship("User", foreign_keys=[invited_by_user_id], backref="invitations_sent")
    accepted_by = relationship("User", foreign_keys=[accepted_by_user_id], backref="invitations_accepted")

    @classmethod
    def generate_code(cls) -> str:
        """Generate a unique invitation code"""
        import secrets
        return secrets.token_urlsafe(24)

    def is_expired(self) -> bool:
        """Check if invitation has expired"""
        return datetime.utcnow() > self.expires_at

    def is_valid(self) -> bool:
        """Check if invitation is still valid"""
        return (
            self.status == InvitationStatus.PENDING
            and not self.is_expired()
        )
