"""Parental analytics service (W5.2 — PUP Score).

PUP = "Parenting Under Pressure". Composite score 0..100 derived from:
  - completion-rate variance across family members
  - late-penalty rate
  - lowest-performer completion rate
  - clean-streak bonus when everyone is on track

Higher PUP = more friction. The UI uses this to nudge parents toward
re-balancing, scheduling lighter weeks, or talking with a kid.
"""

from datetime import datetime, timedelta, timezone
from statistics import pstdev
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consequence import Consequence
from app.models.family import Family
from app.models.gig import GigClaim, GigClaimStatus
from app.models.pup_snapshot import PupScoreSnapshot
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.task_template import TaskTemplate
from app.models.user import User
from app.core.time_utils import utc_today


class AnalyticsService:
    @staticmethod
    async def per_member_completion_rate(
        db: AsyncSession,
        family_id: UUID,
        *,
        lookback_weeks: int = 4,
    ) -> List[dict]:
        """Per-member mandatory completion rate over the lookback window."""
        today = utc_today()
        start = today - timedelta(weeks=lookback_weeks)
        start_dt = datetime.combine(start, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )

        members_q = select(User).where(
            and_(User.family_id == family_id, User.is_active.is_(True))
        )
        members = list((await db.execute(members_q)).scalars().all())

        out: List[dict] = []
        for m in members:
            base_q = (
                select(
                    func.count(TaskAssignment.id).label("total"),
                    func.count()
                    .filter(TaskAssignment.status == AssignmentStatus.COMPLETED)
                    .label("done"),
                    func.count()
                    .filter(TaskAssignment.status == AssignmentStatus.OVERDUE)
                    .label("late"),
                )
                .select_from(TaskAssignment)
                .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
                .where(
                    and_(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.assigned_to == m.id,
                        TaskAssignment.assigned_date >= start,
                        TaskAssignment.assigned_date <= today,
                        TaskTemplate.is_bonus.is_(False),
                    )
                )
            )
            row = (await db.execute(base_q)).one()
            total = int(row.total or 0)
            done = int(row.done or 0)
            late = int(row.late or 0)
            rate = (done / total * 100.0) if total > 0 else 0.0

            gig_q = (
                select(func.count())
                .select_from(TaskAssignment)
                .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
                .where(
                    and_(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.assigned_to == m.id,
                        TaskAssignment.assigned_date >= start,
                        TaskAssignment.assigned_date <= today,
                        TaskTemplate.is_bonus.is_(True),
                        TaskAssignment.status == AssignmentStatus.COMPLETED,
                    )
                )
            )
            gigs_done = int((await db.execute(gig_q)).scalar() or 0)

            # New gig board (gig_claims) — invisible to the legacy is_bonus path.
            board_q = (
                select(func.count())
                .select_from(GigClaim)
                .where(
                    and_(
                        GigClaim.family_id == family_id,
                        GigClaim.claimed_by == m.id,
                        GigClaim.status == GigClaimStatus.APPROVED,
                        GigClaim.approved_at >= start_dt,
                    )
                )
            )
            gigs_done += int((await db.execute(board_q)).scalar() or 0)

            out.append({
                "user_id": str(m.id),
                "name": m.name,
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "mandatory_total": total,
                "mandatory_done": done,
                "mandatory_late": late,
                "completion_rate": round(rate, 1),
                "gigs_completed": gigs_done,
            })
        return out

    @staticmethod
    async def late_penalty_count(
        db: AsyncSession, family_id: UUID, *, lookback_weeks: int = 4
    ) -> int:
        start = datetime.now(timezone.utc) - timedelta(weeks=lookback_weeks)
        q = (
            select(func.count())
            .select_from(Consequence)
            .where(
                and_(
                    Consequence.family_id == family_id,
                    Consequence.triggered_by_assignment_id.isnot(None),
                    Consequence.start_date >= start,
                )
            )
        )
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def pup_score(
        db: AsyncSession, family_id: UUID
    ) -> dict:
        members = await AnalyticsService.per_member_completion_rate(
            db, family_id, lookback_weeks=4
        )
        # Exclude parents from the load-fairness calculation.
        kids = [m for m in members if m["role"] != "parent"]
        late = await AnalyticsService.late_penalty_count(db, family_id)

        score = 50
        notes: List[str] = []

        if kids:
            rates = [k["completion_rate"] for k in kids]
            spread = pstdev(rates) if len(rates) > 1 else 0.0
            if spread > 25:
                score += 10
                notes.append(f"Uneven completion across kids (spread {spread:.0f}%).")
            min_rate = min(rates) if rates else 100
            if min_rate < 50:
                score += 15
                low = next(k for k in kids if k["completion_rate"] == min_rate)
                notes.append(
                    f"{low['name']} below 50% completion — talk to them this week."
                )
            elif all(r >= 90 for r in rates) and late == 0:
                score -= 15
                notes.append("Everyone on track — nice rhythm.")

        if late > 5:
            score += 10
            notes.append(f"{late} auto-penalties in the last 4 weeks.")
        elif late == 0 and kids:
            notes.append("Zero late penalties this month.")

        score = max(0, min(100, score))

        # Week-over-week delta from snapshot history (W11A insight).
        delta_text: Optional[str] = None
        try:
            from app.models.pup_snapshot import PupScoreSnapshot
            hist_q = (
                select(PupScoreSnapshot.score)
                .where(PupScoreSnapshot.family_id == family_id)
                .order_by(PupScoreSnapshot.snapshot_date.desc())
                .limit(8)
            )
            recent_scores = [int(r) for r in (await db.execute(hist_q)).scalars().all()]
            if len(recent_scores) >= 7:
                last_week_avg = sum(recent_scores[1:8]) / 7.0
                diff = score - last_week_avg
                if diff <= -8:
                    delta_text = f"Down {abs(diff):.0f} pts vs last week — improving."
                elif diff >= 8:
                    delta_text = f"Up {diff:.0f} pts vs last week — friction rising."
                else:
                    delta_text = "Roughly flat vs last week."
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "pup-score week-over-week delta computation failed", exc_info=True
            )
        if delta_text:
            notes.append(delta_text)

        return {
            "pup_score": score,
            "label": (
                "high"
                if score >= 70
                else "moderate"
                if score >= 40
                else "low"
            ),
            "notes": notes,
            "members": members,
            "late_penalty_count": late,
        }

    # ─── Snapshot history (W6.3) ─────────────────────────────────────

    @staticmethod
    async def write_snapshot(db: AsyncSession, family_id: UUID) -> dict:
        """Compute today's PUP and upsert as that family's daily snapshot."""
        result = await AnalyticsService.pup_score(db, family_id)
        today = utc_today()
        stmt = (
            pg_insert(PupScoreSnapshot)
            .values(
                family_id=family_id,
                score=result["pup_score"],
                label=result["label"],
                snapshot_date=today,
            )
            .on_conflict_do_update(
                index_elements=["family_id", "snapshot_date"],
                set_={
                    "score": result["pup_score"],
                    "label": result["label"],
                },
            )
        )
        await db.execute(stmt)
        await db.commit()
        return result

    @staticmethod
    async def write_all_snapshots(db: AsyncSession) -> int:
        """Iterate every family and upsert today's snapshot. For the cron."""
        rows = (await db.execute(
            select(Family.id).where(Family.deleted_at.is_(None))
        )).scalars().all()
        for fid in rows:
            try:
                await AnalyticsService.write_snapshot(db, fid)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "snapshot failed for family %s", fid
                )
        return len(rows)

    @staticmethod
    async def list_snapshots(
        db: AsyncSession, family_id: UUID, *, days: int = 30
    ) -> List[dict]:
        start = utc_today() - timedelta(days=days)
        q = (
            select(PupScoreSnapshot)
            .where(
                and_(
                    PupScoreSnapshot.family_id == family_id,
                    PupScoreSnapshot.snapshot_date >= start,
                )
            )
            .order_by(PupScoreSnapshot.snapshot_date.asc())
        )
        rows = list((await db.execute(q)).scalars().all())
        return [
            {
                "date": r.snapshot_date.isoformat(),
                "score": int(r.score),
                "label": r.label,
            }
            for r in rows
        ]
