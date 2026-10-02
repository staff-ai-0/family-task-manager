"""Jarvis teen check-in: who is offered help, about which chore, how often —
and storing the one-tap answer.

Pure rules first (no DB), then the family-scoped queries. The offer is always
derived on the server, so a client can only answer the chore it was actually
offered. No LLM call here: the answer is a tap, the help is a ready-made tip.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.premium import family_tier_allows
from app.models.family import Family
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.models.user import User, UserRole
from app.services.progress_service import ProgressService

REASONS = ("too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other")
# Free text is kept only where a tag says too little.
NOTE_REASONS = frozenset({"app_problem", "other"})
NOTE_MAX = 200
CANDIDATE_DAYS = 14   # a chore older than this is not worth asking about
MAX_PER_WEEK = 3      # Monday–Sunday, answers and dismissals alike
PAUSE_DAYS = 7        # "Not now" blocks offers for that day plus six


@dataclass(frozen=True)
class Candidate:
    assignment_id: UUID
    assigned_date: date
    trigger: str            # "late" | "sent_back"
    title: str
    title_es: Optional[str]
    points: int


def trigger_for(status, approval, assigned_date: date, today: date) -> Optional[str]:
    """Why this chore is worth a check-in, or None.

    sent_back — a parent rejected it and the app re-opened it for a redo
    (open + REJECTED), whatever its date. The hourly overdue sweep flips a
    re-opened chore dated before today from PENDING to OVERDUE and leaves
    approval_status alone, so both statuses count. late — still open, dated
    before today, and not sent back."""
    still_open = status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)
    if still_open and approval == ApprovalStatus.REJECTED:
        return "sent_back"
    if still_open and assigned_date < today:
        return "late"
    return None


def pick_candidate(cands: list[Candidate]) -> Optional[Candidate]:
    """One chore per offer: a sent-back one first, else a late one; the most
    recently dated within the kind (the freshest in the teen's memory)."""
    sent_back = [c for c in cands if c.trigger == "sent_back"]
    pool = sent_back or [c for c in cands if c.trigger == "late"]
    if not pool:
        return None
    return max(pool, key=lambda c: (c.assigned_date, str(c.assignment_id)))


def may_offer(today: date, past: list[tuple[date, str]]) -> bool:
    """`past` — (family-local date, outcome) of the teen's earlier check-ins.
    One a day, MAX_PER_WEEK a week, and a dismissal pauses PAUSE_DAYS days."""
    week_start = today - timedelta(days=today.weekday())
    if any(day == today for day, _ in past):
        return False
    if sum(1 for day, _ in past if week_start <= day <= today) >= MAX_PER_WEEK:
        return False
    if any(outcome == "dismissed" and 0 <= (today - day).days < PAUSE_DAYS for day, outcome in past):
        return False
    return True


def normalize_note(reason: Optional[str], note: Optional[str]) -> Optional[str]:
    """One clean line, or None when blank. Raises ValueError for a note on a
    reason that takes none, or one longer than NOTE_MAX — never silently
    dropped: the teen was told where their words go. Line breaks become
    spaces and control characters are removed (PostgreSQL refuses a NUL in
    text, which would otherwise surface as a 500)."""
    text = " ".join("".join(ch for ch in (note or "") if ch.isprintable() or ch.isspace()).split())
    if not text:
        return None
    if reason not in NOTE_REASONS:
        raise ValueError("a note is only kept for 'app_problem' and 'other'")
    if len(text) > NOTE_MAX:
        raise ValueError(f"a note is at most {NOTE_MAX} characters")
    return text


def _lang(raw: Optional[str]) -> str:
    return "es" if (raw or "").lower().startswith("es") else "en"


# ── Queries (family-scoped) ──────────────────────────────────────────────
class TeenCheckinService:
    @staticmethod
    async def can_chat(db: AsyncSession, family_id: UUID) -> bool:
        """Does the family's plan include the Jarvis conversation?"""
        return bool(await family_tier_allows(db, family_id, "ai_features"))

    @staticmethod
    async def _past(
        db: AsyncSession, family_id: UUID, user_id: UUID, today: date, tz: ZoneInfo,
    ) -> list[tuple[date, str]]:
        since = datetime.combine(today - timedelta(days=CANDIDATE_DAYS), datetime.min.time(), tzinfo=tz)
        rows = (await db.execute(
            select(TeenCheckin.created_at, TeenCheckin.outcome).where(
                TeenCheckin.family_id == family_id,
                TeenCheckin.user_id == user_id,
                TeenCheckin.created_at >= since,
            )
        )).all()
        return [(created.astimezone(tz).date(), outcome) for created, outcome in rows]

    @staticmethod
    async def _candidates(db: AsyncSession, family_id: UUID, user_id: UUID, today: date) -> list[Candidate]:
        asked = select(TeenCheckin.assignment_id).where(
            TeenCheckin.family_id == family_id,
            TeenCheckin.user_id == user_id,
            TeenCheckin.assignment_id.is_not(None),
        )
        rows = (await db.execute(
            select(
                TaskAssignment.id, TaskAssignment.assigned_date, TaskAssignment.status,
                TaskAssignment.approval_status, TaskTemplate.title, TaskTemplate.title_es, TaskTemplate.points,
            )
            .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_to == user_id,
                TaskTemplate.is_bonus.is_(False),
                TaskAssignment.status.in_((AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)),
                TaskAssignment.assigned_date > today - timedelta(days=CANDIDATE_DAYS),
                TaskAssignment.assigned_date <= today,
                TaskAssignment.id.not_in(asked),
            )
        )).all()
        out: list[Candidate] = []
        for row in rows:
            trigger = trigger_for(row.status, row.approval_status, row.assigned_date, today)
            if trigger:
                out.append(Candidate(row.id, row.assigned_date, trigger, row.title, row.title_es, int(row.points or 0)))
        return out

    @staticmethod
    async def offer_for(db: AsyncSession, user: User) -> Optional[Candidate]:
        """The chore Jarvis would ask this user about right now, or None.
        Read-only. Teens only, in a family that switched check-ins on."""
        if user.role != UserRole.TEEN:
            return None
        enabled = (await db.execute(
            select(Family.teen_checkin_enabled).where(Family.id == user.family_id)
        )).scalar()
        if enabled is not True:            # NULL (undecided) and False are both off
            return None
        today, tz = await ProgressService.family_today(db, user.family_id)
        if not may_offer(today, await TeenCheckinService._past(db, user.family_id, user.id, today, tz)):
            return None
        return pick_candidate(await TeenCheckinService._candidates(db, user.family_id, user.id, today))

    @staticmethod
    async def record(
        db: AsyncSession, user: User, assignment_id: UUID, outcome: str,
        reason: Optional[str], note: Optional[str],
    ) -> bool:
        """Store the teen's answer (or "not now") for the chore they were
        offered. False — and nothing stored — when that chore is not the
        current offer. Saving the same chore twice is harmless: the first
        answer stands."""
        family_id, user_id = user.family_id, user.id
        already = (await db.execute(
            select(TeenCheckin.id).where(
                TeenCheckin.family_id == family_id,
                TeenCheckin.user_id == user_id,
                TeenCheckin.assignment_id == assignment_id,
            )
        )).first()
        if already is not None:
            return True
        offer = await TeenCheckinService.offer_for(db, user)
        if offer is None or offer.assignment_id != assignment_id:
            return False
        today, _tz = await ProgressService.family_today(db, family_id)
        answered = outcome == "answered"
        await db.execute(
            pg_insert(TeenCheckin)
            .values(
                family_id=family_id,
                user_id=user_id,
                assignment_id=assignment_id,
                trigger=offer.trigger,
                outcome="answered" if answered else "dismissed",
                reason=reason if answered else None,
                note=normalize_note(reason, note) if answered else None,
                days_late=max(0, (today - offer.assigned_date).days),
                points=offer.points,
                lang=_lang(user.preferred_lang),
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(constraint="uq_teen_checkins_family_user_assignment")
        )
        await db.commit()
        return True
