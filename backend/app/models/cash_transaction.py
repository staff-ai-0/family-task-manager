"""CashTransaction model — ledger for the cash currency (gigs → payouts).

Mirror of PointTransaction, but cash lives in centavos. Points (privileges)
and cash (money) are intentionally separate currencies; see
docs/superpowers/specs/2026-06-30-two-currency-economy-design.md.
"""
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class CashTransactionType(str, enum.Enum):
    """Types of cash transactions."""
    GIG_EARNED = "gig_earned"   # cash credited when a gig is approved
    PAYOUT = "payout"           # parent paid the kid (debit)
    ADJUSTMENT = "adjustment"   # manual parent adjustment (signed)


class CashTransaction(Base):
    """Cash ledger row (centavos). Positive = credit, negative = debit."""

    __tablename__ = "cash_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    type = Column(SQLEnum(CashTransactionType), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    family_id = Column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    balance_before = Column(Integer, nullable=False, default=0)
    balance_after = Column(Integer, nullable=False)

    # Links — both nullable. Gig settlement keys off assignment_id (mirrors
    # PointTransaction); gig_claim_id kept for parity with the gig-claim flow.
    assignment_id = Column(
        UUID(as_uuid=True), ForeignKey("task_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    gig_claim_id = Column(
        UUID(as_uuid=True), ForeignKey("gig_claims.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True,
    )

    user = relationship(
        "User", foreign_keys=[user_id], back_populates="cash_transactions",
    )
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return (
            f"<CashTransaction(id={self.id}, type={self.type.value}, "
            f"amount_cents={self.amount_cents})>"
        )
