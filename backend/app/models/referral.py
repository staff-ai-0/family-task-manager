"""Referral program model.

Tracks a give-a-month/get-a-month growth loop: when a brand-new family
registers with another family's ``referral_code`` (``?ref=CODE`` on the
register page), one ``Referral`` row records referrer → referred and both
families are granted a 30-day Plus credit.

Guards baked in at the DB level:
- ``referred_family_id`` is UNIQUE — a family can be referred only once
  (prevents double-credit even under a concurrent registration race).
- Both FKs are ``ON DELETE CASCADE`` so closing a family purges its
  referral rows with it (no ORM relationship needed — the DB handles it,
  same as the other family-scoped tables' delete cascade).

Self-referral (referrer == referred) and unknown-code are guarded in the
service layer; a brand-new family can never equal an existing referrer, so
the DB constraint plus the service checks fully cover the rules.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Referral(Base):
    """One referrer_family → referred_family link, with reward bookkeeping."""

    __tablename__ = "referrals"
    __table_args__ = (
        # A family can be the *referred* party at most once. This is the
        # authoritative double-credit guard.
        UniqueConstraint(
            "referred_family_id", name="uq_referrals_referred_family"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referrer_family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referred_family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stamped when BOTH families were successfully credited. Non-null means
    # the reward was applied; the row is created and stamped in one commit,
    # so in practice it is always set on a persisted row.
    reward_granted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Referral(referrer={self.referrer_family_id}, "
            f"referred={self.referred_family_id})>"
        )
