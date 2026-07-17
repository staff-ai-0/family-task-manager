"""KidBankAccount model — Family Bank per-kid jar balances + parent config.

One row per kid. Carries the three materialized jar balances (spend / save /
share, centavos) AND the parent-set automation config (weekly allowance,
auto-split percentages, parent-paid interest, parent match). See
``docs/specs/family-bank.md`` (§4 DDL).

INVARIANT #1 (enforced in CashService, asserted in tests):
    spend_cents + save_cents + share_cents == users.cash_cents  — always.

Rows are lazily created the first time a kid's cash is touched (or the parent
opens Family Bank settings). A freshly created row seeds ``spend_cents`` from
the kid's existing ``cash_cents`` — all historical cash was spendable, which
mirrors the ``jar='spend'`` server_default backfill on the ledger and keeps the
invariant true for pre-existing balances. Config defaults are no-op (100/0/0
split, 0 allowance/interest/match) so a family that never configures the bank
sees zero behaviour change.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class KidBankAccount(Base):
    """Per-kid Family Bank account: jar balances (materialized) + parent config."""

    __tablename__ = "kid_bank_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Jar balances, centavos. Sum == users.cash_cents (invariant #1).
    spend_cents = Column(Integer, nullable=False, default=0, server_default="0")
    save_cents = Column(Integer, nullable=False, default=0, server_default="0")
    share_cents = Column(Integer, nullable=False, default=0, server_default="0")

    # Weekly allowance ("domingo"). 0 = no allowance. Weekday 0=Mon..6=Sun
    # (default 6 — Sunday, the literal "domingo").
    allowance_cents = Column(Integer, nullable=False, default=0, server_default="0")
    payday_weekday = Column(SmallInteger, nullable=False, default=6, server_default="6")
    # How the weekly allowance is earned:
    #   "flat"              → pay allowance_cents every payday (legacy behaviour)
    #   "chore_proportional"→ allowance_cents is the weekly CAP; pay it scaled by
    #                         the share of assigned chore points the kid completed
    #                         AND got approved that week (100% = the full cap).
    allowance_mode = Column(
        String(20), nullable=False, default="flat", server_default="flat"
    )
    # Monday of the last week whose chore paycheck the parent released — makes
    # release_chore_paycheck idempotent per (kid, week). NULL = never released.
    last_chore_paycheck_week = Column(Date, nullable=True)
    # Monday of the last week we nudged the parent to release this kid's chore
    # paycheck — makes the payday reminder fire once per (kid, week), not hourly.
    last_paycheck_reminder_week = Column(Date, nullable=True)

    # % auto-split of every cash credit (gig payouts + allowance). Must sum 100.
    split_spend_pct = Column(SmallInteger, nullable=False, default=100, server_default="100")
    split_save_pct = Column(SmallInteger, nullable=False, default=0, server_default="0")
    split_share_pct = Column(SmallInteger, nullable=False, default=0, server_default="0")

    # Parent-paid weekly interest on the Save jar, basis points (100 = 1%/wk).
    interest_rate_bps = Column(Integer, nullable=False, default=0, server_default="0")

    # Parent match on kid-initiated Save deposits, applied at payday.
    match_pct = Column(SmallInteger, nullable=False, default=0, server_default="0")  # 50 = 50%
    match_cap_cents = Column(Integer, nullable=False, default=0, server_default="0")  # 0 = uncapped

    save_withdrawal_requires_approval = Column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Idempotency guard for the payday sweep + the parent-match lookback window.
    last_payday_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "split_spend_pct + split_save_pct + split_share_pct = 100",
            name="ck_kid_bank_split_sum",
        ),
        CheckConstraint(
            "spend_cents >= 0 AND save_cents >= 0 AND share_cents >= 0 "
            "AND allowance_cents >= 0 "
            "AND payday_weekday BETWEEN 0 AND 6 "
            "AND split_spend_pct BETWEEN 0 AND 100 "
            "AND split_save_pct BETWEEN 0 AND 100 "
            "AND split_share_pct BETWEEN 0 AND 100 "
            "AND interest_rate_bps BETWEEN 0 AND 10000 "
            "AND match_pct BETWEEN 0 AND 200 "
            "AND match_cap_cents >= 0",
            name="ck_kid_bank_ranges",
        ),
        Index("ix_kid_bank_accounts_family_id", "family_id"),
    )

    def __repr__(self):
        return (
            f"<KidBankAccount(user_id={self.user_id}, spend={self.spend_cents}, "
            f"save={self.save_cents}, share={self.share_cents})>"
        )
