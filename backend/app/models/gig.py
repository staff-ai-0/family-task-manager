from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    Index,
    text,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import Enum
import uuid

from app.core.database import Base


class GigCategory(str, Enum):
    CHORES = "chores"
    ERRANDS = "errands"
    CREATIVE = "creative"
    LEARNING = "learning"
    OUTDOOR = "outdoor"
    OTHER = "other"


class GigClaimStatus(str, Enum):
    CLAIMED = "claimed"
    COMPLETED = "completed"
    APPROVED = "approved"
    REJECTED = "rejected"


class GigOfferingStatus(str, Enum):
    """Lifecycle of an offering on the board (W4.4 kid proposals).

    - approved: live on the board (all parent-created offerings start here).
    - pending:  kid-proposed draft awaiting parent review (is_active=False,
                never claimable).
    - rejected: parent declined the proposal (review_notes says why).
    """
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class GigOffering(Base):
    """A gig posted by a parent that kids can claim independently."""

    __tablename__ = "gig_offerings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    points = Column(Integer, nullable=False)  # 1 point = $1 MXN
    difficulty = Column(Integer, nullable=False, default=1)  # 1=Easy 2=Medium 3=Hard
    category = Column(
        SQLEnum(GigCategory, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GigCategory.OTHER,
        server_default=GigCategory.OTHER.value,
    )
    allowed_roles = Column(
        JSONB,
        nullable=True,
        comment="List of role strings eligible to claim; null = all non-parent roles",
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    # Single-slot by default: the first APPROVED claim closes the gig and
    # releases every other active claim, so a family never pays twice for the
    # same job (2026-07-16 double-pay incident). Set true for gigs that several
    # kids may legitimately complete and get paid for independently.
    allow_multiple = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Kid-proposed gigs (W4.4): parent-created offerings are 'approved';
    # kid proposals start 'pending' (with is_active=False) until a parent
    # approves (→ 'approved' + active) or rejects (→ 'rejected').
    status = Column(
        String(16), nullable=False,
        default=GigOfferingStatus.APPROVED.value,
        server_default=GigOfferingStatus.APPROVED.value,
        index=True,
    )
    review_notes = Column(Text, nullable=True)
    reviewed_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    family = relationship("Family")
    creator = relationship("User", foreign_keys=[created_by])
    claims = relationship("GigClaim", back_populates="offering", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<GigOffering(id={self.id}, title={self.title!r}, points={self.points})>"


class GigClaim(Base):
    """One kid's claim on a gig offering."""

    __tablename__ = "gig_claims"
    __table_args__ = (
        # Partial unique: one ACTIVE (non-rejected) claim per user per gig.
        # A rejected claim must not block re-claiming, so the index excludes
        # status='rejected'. Mirrors the raw SQL in migration
        # 2026_06_01_gig_tables.py exactly so create_all (test DB) and the
        # deployed schema enforce the same rule.
        Index(
            "uq_gig_claim_active",
            "gig_id",
            "claimed_by",
            unique=True,
            postgresql_where=text("status != 'rejected'"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    gig_id = Column(
        UUID(as_uuid=True), ForeignKey("gig_offerings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id = Column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claimed_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = Column(
        SQLEnum(GigClaimStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GigClaimStatus.CLAIMED,
        server_default=GigClaimStatus.CLAIMED.value,
        index=True,
    )
    proof_text = Column(Text, nullable=True)
    proof_image_url = Column(String(500), nullable=True)
    points_awarded = Column(Integer, nullable=True)  # snapshot at approval time
    completed_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approval_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    offering = relationship("GigOffering", back_populates="claims")
    claimer = relationship("User", foreign_keys=[claimed_by])
    approver = relationship("User", foreign_keys=[approved_by])
    point_transactions = relationship("PointTransaction", back_populates="gig_claim")

    def __repr__(self):
        return f"<GigClaim(id={self.id}, gig_id={self.gig_id}, claimed_by={self.claimed_by}, status={self.status})>"


class GigClaimComment(Base):
    """Parent ↔ kid conversation attached to a gig claim.

    Visibility mirrors the claim itself: the family's parents plus the kid
    who claimed it. One flat thread per claim (no nesting).
    """

    __tablename__ = "gig_claim_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    claim_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gig_claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    author = relationship("User", foreign_keys=[author_id])
