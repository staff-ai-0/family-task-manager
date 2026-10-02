"""Jarvis teen check-in: one row per offer a teen acted on.

When a teen has a late or sent-back chore, Jarvis offers a hand on their home.
The teen either answers with a one-tap reason or says "not now"; that is this
row. It is what the product owner counts across families (operator console),
so it deliberately carries NO chore title — titles are written by the family
and can contain names. A short note is kept only for the two open reasons.
"""
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class TeenCheckin(Base):
    __tablename__ = "teen_checkins"
    __table_args__ = (
        # A chore is asked about once, ever.
        UniqueConstraint("family_id", "user_id", "assignment_id", name="uq_teen_checkins_family_user_assignment"),
        CheckConstraint("trigger IN ('late','sent_back')", name="ck_teen_checkins_trigger"),
        CheckConstraint("outcome IN ('answered','dismissed')", name="ck_teen_checkins_outcome"),
        CheckConstraint(
            "reason IS NULL OR reason IN "
            "('too_hard','not_clear','no_time','not_fair','forgot','app_problem','other')",
            name="ck_teen_checkins_reason",
        ),
        CheckConstraint("(outcome = 'answered') = (reason IS NOT NULL)", name="ck_teen_checkins_reason_iff_answered"),
        CheckConstraint("note IS NULL OR reason IN ('app_problem','other')", name="ck_teen_checkins_note_reason"),
        CheckConstraint("note IS NULL OR char_length(note) <= 200", name="ck_teen_checkins_note_len"),
        CheckConstraint("days_late >= 0", name="ck_teen_checkins_days_late"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL: deleting the chore keeps the answer (the counts stay true).
    assignment_id = Column(
        UUID(as_uuid=True), ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True
    )
    trigger = Column(String(16), nullable=False)       # late | sent_back
    outcome = Column(String(16), nullable=False)       # answered | dismissed
    reason = Column(String(16), nullable=True)         # one of the seven keys; NULL when dismissed
    # TEXT, bounded by ck_teen_checkins_note_len: an over-long note is refused by
    # the constraint (one error type for every bad row), not by a column width.
    note = Column(Text, nullable=True)                 # only for app_problem / other
    days_late = Column(Integer, nullable=False)        # chore date → the day of the answer
    points = Column(Integer, nullable=False)           # the chore's points: a size signal, not an identity
    lang = Column(String(2), nullable=False)           # es | en — for reading notes
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)

    def __repr__(self):
        return f"<TeenCheckin(user_id={self.user_id}, outcome={self.outcome}, reason={self.reason})>"
