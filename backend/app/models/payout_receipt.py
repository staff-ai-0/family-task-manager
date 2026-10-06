"""A bank-transfer receipt (BBVA "Comprobante de la operación") that paid a
kid's chore paycheck. One row per transfer; the (family, folio) pair is the
dedupe key that stops the same screenshot being recorded twice.

Only the folio and what the parent confirmed are kept — never the image and
never account numbers.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class PayoutReceipt(Base):
    __tablename__ = "payout_receipts"
    __table_args__ = (
        UniqueConstraint("family_id", "folio", name="uq_payout_receipts_family_folio"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    folio = Column(String(40), nullable=False)
    receipt_date = Column(Date, nullable=True)
    amount_cents = Column(Integer, nullable=False)
    concept = Column(Text, nullable=True)
    weeks = Column(JSONB, nullable=False, default=list)   # [{week_of, amount_cents, top_up}]
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
