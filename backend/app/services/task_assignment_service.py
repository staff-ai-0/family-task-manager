"""
TaskAssignment Service

Business logic for task assignments, weekly shuffle, completion, and bonus gating.
"""

import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, delete as sql_delete
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, date, timedelta, timezone
from uuid import UUID

from app.models.task_template import TaskTemplate, AssignmentType
from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
from app.models.user import User, APPROVAL_APPROVED
from app.models.point_transaction import PointTransaction, TransactionType
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.core.time_utils import utc_today
from app.services.base_service import (
    BaseFamilyService,
    get_user_by_id,
)


class TaskAssignmentService(BaseFamilyService[TaskAssignment]):
    """Service for task assignment operations including shuffle and gating"""

    model = TaskAssignment

    @staticmethod
    async def _user_local_today(db: AsyncSession, user_id: UUID) -> date:
        """Return today's date in the user's family timezone."""
        from zoneinfo import ZoneInfo
        from app.models.family import Family
        from app.services.base_service import get_user_by_id
        user = await get_user_by_id(db, user_id)
        tz_name = "UTC"
        if user.family_id is not None:
            family = await db.get(Family, user.family_id)
            if family and family.timezone:
                tz_name = family.timezone
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()

    @staticmethod
    def _participating_member_clause():
        """SQL filter for members who take part in the chore pipeline.

        Shared by every member selection in this service (shuffle inputs,
        notification sweeps). A member participates only when the account is
        BOTH active AND parent-approved: join-code self-signups are created
        with is_active=True but approval_status='pending' (they cannot log
        in until a parent approves), so filtering on is_active alone would
        hand weekly chores, morning reminders, and automatic late penalties
        to an account that cannot even see them.
        """
        return and_(
            User.is_active == True,  # noqa: E712
            User.approval_status == APPROVAL_APPROVED,
        )

    # ─── Shuffle Algorithm ───────────────────────────────────────────

    @staticmethod
    def _get_monday(d: date) -> date:
        """Get the Monday of the week containing the given date"""
        return d - timedelta(days=d.weekday())

    @staticmethod
    def _expand_dates(
        week_monday: date,
        interval_days: int,
        days_of_week: Optional[List[int]] = None,
    ) -> List[date]:
        """
        Expand a template into specific dates for the week.

        days_of_week (Mon=0..Sun=6), when set, wins: exactly those weekdays.
        Otherwise the interval pattern:
        interval_days=1 -> [Mon, Tue, Wed, Thu, Fri, Sat, Sun]
        interval_days=7 -> [Any single day] (Handled by shuffle_tasks now)
        Others -> Fixed pattern starting Mon
        """
        if days_of_week:
            return [
                week_monday + timedelta(days=d)
                for d in sorted({int(d) for d in days_of_week if 0 <= int(d) <= 6})
            ]
        dates = []
        current = week_monday
        week_end = week_monday + timedelta(days=6)  # Sunday

        # Standard rigid expansion
        while current <= week_end:
            dates.append(current)
            current += timedelta(days=interval_days)
        return dates

    @staticmethod
    def _resolve_week_monday(
        week_of: Optional[date], today: Optional[date] = None
    ) -> date:
        """Pick the target week's Monday. Sundays bump to next week.

        ``today`` is the family-local date (falls back to server date) — using
        the server-UTC date made a Saturday-night shuffle in Mexico target the
        NEXT week (it was already Sunday in UTC).
        """
        if week_of is None:
            today = today or utc_today()
            if today.weekday() == 6:  # Sunday → next week
                return today + timedelta(days=1)
            return TaskAssignmentService._get_monday(today)
        return TaskAssignmentService._get_monday(week_of)

    @staticmethod
    async def _load_shuffle_inputs(
        db: AsyncSession, family_id: UUID
    ) -> tuple[list[TaskTemplate], list[TaskTemplate], list[User]]:
        """Fetch regular templates, bonus templates, and participating members
        (active AND parent-approved — see _participating_member_clause).

        Templates with recurrence_mode='since_completion' are excluded — they
        spawn via spawn_interval_assignments (N days after last completion),
        not via the weekly expansion.
        """
        weekly_only = func.coalesce(
            TaskTemplate.recurrence_mode, "weekly"
        ) != "since_completion"

        regular_query = select(TaskTemplate).where(
            and_(
                TaskTemplate.family_id == family_id,
                TaskTemplate.is_active == True,
                TaskTemplate.is_bonus == False,
                weekly_only,
            )
        )
        regular_templates = list((await db.execute(regular_query)).scalars().all())

        bonus_query = select(TaskTemplate).where(
            and_(
                TaskTemplate.family_id == family_id,
                TaskTemplate.is_active == True,
                TaskTemplate.is_bonus == True,
                weekly_only,
            )
        )
        bonus_templates = list((await db.execute(bonus_query)).scalars().all())

        members_query = select(User).where(
            and_(
                User.family_id == family_id,
                TaskAssignmentService._participating_member_clause(),
            )
        )
        members = list((await db.execute(members_query)).scalars().all())

        return regular_templates, bonus_templates, members

    @staticmethod
    async def _compute_member_carry(
        db: AsyncSession,
        family_id: UUID,
        week_monday: date,
        member_ids: list[UUID],
        lookback_weeks: int = 2,
    ) -> dict[UUID, int]:
        """
        Cross-week fairness: sum of template points assigned to each member in the
        prior `lookback_weeks`. Members with high carry are picked LAST.
        Excludes CANCELLED rows.
        """
        if lookback_weeks <= 0 or not member_ids:
            return {mid: 0 for mid in member_ids}

        start = week_monday - timedelta(weeks=lookback_weeks)
        query = (
            select(
                TaskAssignment.assigned_to,
                func.coalesce(func.sum(TaskTemplate.points), 0).label("pts"),
            )
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.week_of >= start,
                    TaskAssignment.week_of < week_monday,
                    TaskAssignment.status != AssignmentStatus.CANCELLED,
                )
            )
            .group_by(TaskAssignment.assigned_to)
        )
        rows = (await db.execute(query)).all()
        carry = {mid: 0 for mid in member_ids}
        for user_id, pts in rows:
            if user_id in carry:
                carry[user_id] = int(pts or 0)
        return carry

    @staticmethod
    def _occurrences_per_week(
        interval_days: int, days_of_week: Optional[List[int]] = None
    ) -> int:
        """Number of dates _expand_dates yields for a week: len(days_of_week)
        when set, else by interval: 1→7, 2→4, 3→3, 4→2, 5→2, 6→2, 7→1."""
        anchor = date(2026, 1, 5)  # any Monday
        return len(TaskAssignmentService._expand_dates(
            anchor, max(1, interval_days), days_of_week
        ))

    @staticmethod
    def _rotation_start_for_week(template: TaskTemplate, week_monday: date) -> int:
        """Starting rotation offset for a ROTATE template in a given week.

        Persisted state: (rotation_week_of, rotation_cursor) = the week last
        shuffled and the NEXT start offset after it (start actually used +
        occurrences actually generated, both captured at shuffle time — see
        shuffle_tasks). Storing the post-week cursor means continuity never
        re-derives the past week's occurrence count from the template's
        CURRENT interval_days, so a parent changing the frequency between
        weeks (e.g. daily → weekly) cannot skip or repeat a kid. Semantics:
        - never shuffled → 0;
        - same week again → cursor minus THIS week's occurrences (backs out
          to the same start, so a re-shuffle is deterministic while the
          interval is unchanged; clamped at 0 if the interval shrank);
        - any other week → cursor as stored (rotation continues where the
          last shuffled week left off).
        The value is an absolute counter; callers mod by len(eligible).
        """
        if template.rotation_week_of is None:
            return 0
        if template.rotation_week_of == week_monday:
            occurrences = TaskAssignmentService._occurrences_per_week(
                template.interval_days or 1,
                getattr(template, "days_of_week", None),
            )
            return max(0, int(template.rotation_cursor or 0) - occurrences)
        return int(template.rotation_cursor or 0)

    @staticmethod
    def _rotation_eligible(
        template: TaskTemplate, members: list[User]
    ) -> list[User]:
        """Members eligible for a ROTATE template, in assigned_user_ids order
        (parent-defined, stable) — NOT the shuffled member order, so the
        round-robin sequence is deterministic across shuffles and weeks."""
        by_id = {str(m.id): m for m in members}
        return [
            by_id[uid]
            for uid in (template.assigned_user_ids or [])
            if uid in by_id
        ]

    @staticmethod
    def _compute_assignments(
        rng: random.Random,
        family_id: UUID,
        week_monday: date,
        regular_templates: list[TaskTemplate],
        bonus_templates: list[TaskTemplate],
        members: list[User],
        member_carry: Optional[dict[UUID, int]] = None,
        rotation_starts: Optional[dict[UUID, int]] = None,
        today: Optional[date] = None,
        rest_days: Optional[list[int]] = None,
    ) -> tuple[list[TaskAssignment], dict[UUID, int], list[dict]]:
        """
        Pure builder — produces TaskAssignment instances WITHOUT db.add/commit.
        Caller decides whether to persist.

        ``today`` (family-local) makes a MID-WEEK build honest: occurrences on
        already-past days are never materialized NOR credited to totals —
        previously the preview header counted phantom past-day chores while
        the listed plan didn't (prod: "Ariana 90 pts" vs 2 listed chores).
        Rotation POSITIONS still consume the full-week expansion so the
        persisted cursor stays deterministic across same-week re-shuffles.

        Returns (assignments, totals_per_member, skipped) where totals exclude
        carry and skipped lists templates that could not be expanded
        ({template_id, title, reason}) — silent skips are how 8 of 9 prod
        templates once generated nothing while the API reported success.
        """
        if not members:
            raise ValidationException("No active family members found")

        members = list(members)
        rng.shuffle(members)  # Tie-break ordering for ties — deterministic via seeded rng

        week_dates = [week_monday + timedelta(days=i) for i in range(7)]
        date_strs = [d.isoformat() for d in week_dates]

        member_load = {m.id: {d_str: 0 for d_str in date_strs} for m in members}
        carry = member_carry or {m.id: 0 for m in members}
        # Member total (current week) — used for cross-day fairness comparisons
        member_total = {m.id: 0 for m in members}
        totals: dict[UUID, int] = {m.id: 0 for m in members}

        # Process MEMBER-FORCED chores (FIXED, and ROTATE pinned to a member
        # list) before AUTO chores. Forced chores have no choice of assignee, so
        # crediting them first lets the AUTO load-balancer see each member's true
        # fixed load and compensate — otherwise a points-desc order interleaves
        # AUTO picks before later forced chores land, and the balancer starves
        # whichever member those forced chores would have offset (prod: two
        # equally-eligible teens drifted to 180 vs 90 because AUTO chores were
        # assigned before the other teen's pinned load was known). Within each
        # group, higher points first. Forced order among themselves is moot
        # (assignee is fixed); AUTO keeps points-desc for best-slot placement.
        def _forced_first(t):
            forced = t.assignment_type == AssignmentType.FIXED or (
                t.assignment_type == AssignmentType.ROTATE
                and bool(TaskAssignmentService._rotation_eligible(t, members))
            )
            return (0 if forced else 1, -t.points)
        regular_templates = sorted(regular_templates, key=_forced_first)
        rotation_starts = rotation_starts or {}
        assignments: list[TaskAssignment] = []
        skipped: list[dict] = []
        # Deterministic tiebreak rank from the seeded shuffle above.
        member_rank = {m.id: i for i, m in enumerate(members)}
        # Family rest days (0=Mon … 6=Sun) never receive assignments.
        rest = {int(x) for x in (rest_days or []) if 0 <= int(x) <= 6}
        week_end = week_monday + timedelta(days=6)

        # Stagger anchor per every-N-day chore (2..6) so several same-interval
        # chores don't all pile onto the same weekdays (every-3-day chores all
        # anchor Mon/Thu otherwise, so a member doing three of them stacks them
        # on one day). Offset = rank-within-interval-group % interval → Mon/Thu,
        # Tue/Fri, Wed/Sat, … The shift is applied AFTER expansion and dates
        # that fall past the week are dropped (see _material), so the occurrence
        # COUNT — and thus the rotation cursor — is unchanged.
        # Only positional-rotation chores are staggered (they carry a fixed
        # member list, so their occurrences land on set weekdays and stack when
        # several share an interval). Listless/AUTO chores already spread via the
        # load balancer, and staggering them would shift mid-week occurrences off
        # remaining days — so they are left alone.
        from collections import defaultdict as _defaultdict
        _iv_groups: dict[int, list] = _defaultdict(list)
        for _t in regular_templates:
            if (2 <= _t.interval_days <= 6
                    and not getattr(_t, "days_of_week", None)
                    and _t.assignment_type == AssignmentType.ROTATE
                    and bool(TaskAssignmentService._rotation_eligible(_t, members))):
                _iv_groups[_t.interval_days].append(_t)
        stagger: dict = {}
        for _iv, _ts in _iv_groups.items():
            for _i, _t in enumerate(sorted(_ts, key=lambda x: str(x.id))):
                stagger[_t.id] = _i % _iv

        def _stag(dates: list[date], template_id) -> list[date]:
            off = stagger.get(template_id, 0)
            return [d + timedelta(days=off) for d in dates] if off else dates

        def _material(dates: list[date]) -> list[date]:
            """Actionable days: within this week, today onward, not a rest day."""
            out = [d for d in dates if week_monday <= d <= week_end]
            if not (today is None or today <= week_monday):
                out = [d for d in out if d >= today]
            if rest:
                out = [d for d in out if d.weekday() not in rest]
            return out

        def _spread_day(user_id: UUID, candidate_days: list[date]) -> date:
            """The assignee's least-loaded (by points) candidate day, so several
            day-flexible chores for one member fan out across the week instead
            of stacking on Monday. Seeded shuffle makes ties deterministic."""
            days = list(candidate_days)
            rng.shuffle(days)
            return min(days, key=lambda d: member_load[user_id][d.isoformat()])

        def _new_assignment(template_id: UUID, user_id: UUID, d: date) -> TaskAssignment:
            return TaskAssignment(
                template_id=template_id,
                assigned_to=user_id,
                family_id=family_id,
                status=AssignmentStatus.PENDING,
                assigned_date=d,
                week_of=week_monday,
            )

        def _credit(user_id: UUID, d: date, points: int) -> None:
            member_load[user_id][d.isoformat()] += points
            member_total[user_id] += points
            totals[user_id] += points

        def _bias(user_id: UUID) -> int:
            return member_total[user_id] + carry.get(user_id, 0)

        for template in regular_templates:
            eligible_members = members
            positional_rotation = False

            # Role filter — applies to AUTO and to the ROTATE null-list
            # fallback. An EXPLICIT member list (FIXED/ROTATE) is
            # authoritative and is resolved below regardless of roles: the
            # parent picked those people by name.
            allowed = template.allowed_roles or None
            if allowed:
                allowed_lower = {r.lower() for r in allowed}
                eligible_members = [
                    m for m in eligible_members
                    if (m.role.value if hasattr(m.role, "value") else str(m.role)).lower()
                    in allowed_lower
                ]

            if template.assignment_type == AssignmentType.FIXED:
                explicit = [
                    m for m in members
                    if str(m.id) in (template.assigned_user_ids or [])
                ]
                if not explicit:
                    # No sane fallback for FIXED (whom would it pin?) —
                    # report instead of silently generating nothing.
                    skipped.append({
                        "template_id": template.id,
                        "title": template.title,
                        "reason": "fixed template has no valid members",
                    })
                    continue
                eligible_members = explicit
            elif template.assignment_type == AssignmentType.ROTATE:
                # assigned_user_ids order (stable), not shuffled member order
                explicit = TaskAssignmentService._rotation_eligible(
                    template, members
                )
                if explicit:
                    eligible_members = explicit
                    positional_rotation = True
                else:
                    # Null/empty/stale member list → "take turns" over ALL
                    # participating members (role-filtered), via the AUTO
                    # load balancer below rather than blind positional
                    # rotation: positional starts collide across templates
                    # (however staggered) and can park the SAME member's
                    # turn on a dropped past day in every chore at once
                    # (prod: Ariana got 2 chores while Mayra had 7). The
                    # balancer takes turns AND compensates across templates
                    # and weeks (carry). This also fixes the original
                    # 8-of-9-templates-dead silent-skip bug.
                    if not eligible_members:
                        skipped.append({
                            "template_id": template.id,
                            "title": template.title,
                            "reason": "no members match allowed_roles",
                        })
                        continue
            elif not eligible_members:
                # AUTO with a role filter that excludes everyone.
                skipped.append({
                    "template_id": template.id,
                    "title": template.title,
                    "reason": "no members match allowed_roles",
                })
                continue

            # Occurrence dates for this template. A weekly (interval 7, no
            # days_of_week) template yields ONE occurrence — never one per day.
            # The old `task_dates = week_dates` shortcut here only ever made
            # sense for the AUTO-weekly slot picker below, which reads
            # week_dates DIRECTLY. FIXED (and any path that iterates task_dates)
            # turned that 7-day list into 7 daily rows, so a once-a-week chore
            # pinned to one member showed up every single day (prod: a weekly
            # FIXED chore generated Mon–Sun for the assignee).
            task_dates = TaskAssignmentService._expand_dates(
                week_monday, template.interval_days,
                getattr(template, "days_of_week", None),
            )
            # A weekly template with no pinned weekday is "day-flexible": its
            # single occurrence can land on ANY day, so we place it on the
            # assignee's least-loaded day instead of always Monday.
            day_flexible = (
                template.interval_days == 7
                and not getattr(template, "days_of_week", None)
            )

            if template.assignment_type == AssignmentType.FIXED:
                fixed_user = eligible_members[0]
                if day_flexible:
                    cand = _material(week_dates)
                    if cand:
                        d = _spread_day(fixed_user.id, cand)
                        assignments.append(_new_assignment(template.id, fixed_user.id, d))
                        _credit(fixed_user.id, d, template.points)
                else:
                    for d in _material(task_dates):
                        assignments.append(_new_assignment(template.id, fixed_user.id, d))
                        _credit(fixed_user.id, d, template.points)

            elif positional_rotation:
                # Parent-picked list: positional round-robin in the parent's
                # order. ONE occurrence per recurrence date (weekly → exactly
                # one, not one per weekday) — duplicates here were the
                # Chorsee failure mode. Start offset comes from the persisted
                # cursor so the rotation continues across weeks and is
                # identical on a same-week re-shuffle.
                rotate_dates = _stag(TaskAssignmentService._expand_dates(
                    week_monday, template.interval_days,
                    getattr(template, "days_of_week", None),
                ), template.id)
                start = rotation_starts.get(template.id, 0)
                for i, d in enumerate(rotate_dates):
                    chosen = eligible_members[
                        (start + i) % len(eligible_members)
                    ]
                    if day_flexible:
                        cand = _material(week_dates)
                        if not cand:
                            continue  # position consumed, row not materialized
                        d = _spread_day(chosen.id, cand)
                    else:
                        if not (week_monday <= d <= week_end):
                            continue  # staggered past week end — position consumed
                        if today is not None and today > week_monday and d < today:
                            continue  # position consumed, row not materialized
                        if d.weekday() in rest:
                            continue  # rest day — position consumed, no row
                    assignments.append(_new_assignment(template.id, chosen.id, d))
                    _credit(chosen.id, d, template.points)

            else:  # AUTO
                if template.interval_days == 7 and not getattr(template, "days_of_week", None):
                    # Pick (member, day) slot with min (day-load + cross-week bias)
                    # — among REMAINING days only; picking a past day used to
                    # silently drop the chore for the whole week.
                    weekly_days = _material(week_dates)
                    if not weekly_days:
                        skipped.append({
                            "template_id": template.id,
                            "title": template.title,
                            "reason": "no remaining days this week",
                        })
                        continue
                    candidates = [
                        (member_load[m.id][d.isoformat()] + _bias(m.id), m, d)
                        for m in eligible_members
                        for d in weekly_days
                    ]
                    rng.shuffle(candidates)
                    _, best_member, best_date = min(candidates, key=lambda x: x[0])
                    assignments.append(
                        _new_assignment(template.id, best_member.id, best_date)
                    )
                    _credit(best_member.id, best_date, template.points)

                else:
                    # Repeating AUTO chores (daily / every N days). Assign each
                    # occurrence to the member with the least CURRENT load
                    # (bias, updated live per credit), capped so no one takes
                    # more than a fair share of THIS chore — that cap keeps the
                    # variety a plain greedy lost (a low-carry member became a
                    # "sink" and got the SAME chore every day: "assigns me sweep
                    # all days"). Day-load is the next tiebreak so a member's
                    # chores spread across their lighter days. A fixed
                    # (bias, rank) round-robin was the prior approach, but its
                    # rank tiebreak quietly favored the lowest-rank member and
                    # shorted the highest — prod drifted to 150 vs 70 pts across
                    # members over a full board.
                    import math as _math
                    from collections import Counter as _Counter
                    mats = _material(task_dates)
                    n_elig = len(eligible_members)
                    cap = _math.ceil(len(mats) / n_elig) if n_elig else 0
                    used: _Counter = _Counter()
                    for d in mats:
                        pool = [
                            m for m in eligible_members if used[m.id] < cap
                        ] or eligible_members
                        chosen = min(
                            pool,
                            key=lambda m: (
                                _bias(m.id),
                                member_load[m.id][d.isoformat()],
                                member_rank[m.id],
                            ),
                        )
                        used[chosen.id] += 1
                        assignments.append(
                            _new_assignment(template.id, chosen.id, d)
                        )
                        _credit(chosen.id, d, template.points)

        for template in bonus_templates:
            dates = _material(TaskAssignmentService._expand_dates(
                week_monday, template.interval_days,
                getattr(template, "days_of_week", None),
            ))

            # Filter eligible members by allowed_roles + assigned_user_ids.
            eligible = list(members)
            allowed = template.allowed_roles or None
            if allowed:
                allowed_lower = {r.lower() for r in allowed}
                eligible = [
                    m for m in eligible
                    if (m.role.value if hasattr(m.role, "value") else str(m.role)).lower()
                    in allowed_lower
                ]
            if template.assigned_user_ids:
                target_ids = set(template.assigned_user_ids)
                eligible = [m for m in eligible if str(m.id) in target_ids]
            if not eligible:
                skipped.append({
                    "template_id": template.id,
                    "title": template.title,
                    "reason": "no eligible members for this gig",
                })
                continue

            mode = getattr(template, "gig_mode", "claim") or "claim"

            if mode == "rotation":
                # One assignment per date, member cycled by week index so
                # week 1 → member 0, week 2 → member 1, etc.
                week_idx = week_monday.toordinal() // 7
                for i, d in enumerate(dates):
                    chosen = eligible[(week_idx + i) % len(eligible)]
                    assignments.append(_new_assignment(template.id, chosen.id, d))
            else:
                # claim / competition / collaboration: every eligible
                # member gets a row per date so they all see the gig.
                for d in dates:
                    for member in eligible:
                        assignments.append(_new_assignment(template.id, member.id, d))

        # ── Member-balance pass: move a shared chore off an over-loaded member
        # onto an under-loaded eligible one until point totals converge. ──
        # Forced-first + the AUTO balancer handles most of it, but heavy
        # positional pinning — or a mid-week shuffle whose remaining days split
        # odd (5 days → 3/2 between two pinned members) — can still leave two
        # equally-pinned members apart (prod: two teens 160 vs 120 mid-week).
        # (Carry — prior weeks + this week's completed work — already biased WHO
        # got what in the balancer above; this pass only evens the residual
        # same-week point totals.) Moving preserves each chore's dates and
        # per-day occurrence count; only assigned_to changes, never onto a
        # (day, chore) a member already has, and never off a FIXED single-owner
        # chore.
        def _recv_ids(t):
            if t.assignment_type == AssignmentType.FIXED:
                return set()
            base = members
            allowed = t.allowed_roles or None
            if allowed:
                al = {r.lower() for r in allowed}
                base = [
                    m for m in base
                    if (m.role.value if hasattr(m.role, "value") else str(m.role)).lower() in al
                ]
            if t.assignment_type == AssignmentType.ROTATE and (t.assigned_user_ids or []):
                pin = {str(x) for x in t.assigned_user_ids}
                return {m.id for m in base if str(m.id) in pin}
            return {m.id for m in base}

        reg_pts = {t.id: t.points for t in regular_templates}
        recv = {t.id: _recv_ids(t) for t in regular_templates}
        # This week's assigned points only — carry already biased WHO got what
        # via the AUTO/forced-first balancer above; re-applying it here would
        # double-count and shut a high-carry member out of the whole week. This
        # pass only evens the residual same-week imbalance (e.g. odd mid-week
        # day splits between two equally-pinned members).
        mtotal = {m.id: 0 for m in members}
        held: dict = {}
        for a in assignments:
            if a.template_id in reg_pts:
                mtotal[a.assigned_to] = mtotal.get(a.assigned_to, 0) + reg_pts[a.template_id]
                held.setdefault(a.assigned_to, set()).add((a.template_id, a.assigned_date))
        for _ in range(len(assignments) * len(members)):
            hi = max(mtotal, key=lambda u: mtotal[u])
            best = None  # (assignment, receiver, points)
            for a in assignments:
                if a.assigned_to != hi or a.template_id not in reg_pts:
                    continue
                p = reg_pts[a.template_id]
                # least-loaded ELIGIBLE receiver for THIS chore (not the global
                # min — an over-loaded member's excess may be pinned to a set
                # that excludes the lightest member) who doesn't already do it
                # that day.
                cands = [
                    o for o in recv.get(a.template_id, set())
                    if o != hi
                    and (a.template_id, a.assigned_date) not in held.get(o, set())
                ]
                if not cands:
                    continue
                o = min(cands, key=lambda u: mtotal[u])
                # move only if hi is ahead of o by MORE than the chore's points
                # (so the move shrinks their gap instead of overshooting)
                if mtotal[hi] - mtotal[o] > p:
                    best = (a, o, p)
                    break
            if best is None:
                break
            a, o, p = best
            held[hi].discard((a.template_id, a.assigned_date))
            held.setdefault(o, set()).add((a.template_id, a.assigned_date))
            a.assigned_to = o
            mtotal[hi] -= p
            mtotal[o] += p

        # ── Final pass: even each member's chores across their OWN days ──
        # Selection balances who does what and roughly when, but a member's
        # occurrences can still bunch on one weekday while leaving others empty
        # (prod: Ariana had Fri:4, Mon/Wed empty). Two schedule-preserving moves,
        # neither of which changes any chore's dates, a member's total count, or
        # the rotation cursor (positions are fixed; only assigned_to / a weekly
        # chore's free day change):
        #   (1) a weekly (single-occurrence, no pinned weekday) chore's day is
        #       ours to choose — shift it to the member's lightest open day;
        #   (2) SWAP a chore's occurrence on a member's heavy day with the SAME
        #       chore's occurrence on their light day held by another member —
        #       evens the over-loaded member without increasing the other's peak.
        # Daily/every-N-day cadence is untouched (a chore keeps its exact dates;
        # only which member does which of its days changes).
        week_material = _material(week_dates)
        if len(week_material) > 1:
            reg_ids = {t.id for t in regular_templates}
            reg = [a for a in assignments if a.template_id in reg_ids]
            weekly_ids = {
                t.id for t in regular_templates
                if not getattr(t, "days_of_week", None) and t.interval_days == 7
            }
            member_ids = {a.assigned_to for a in reg}

            def _day_load(uid):
                c = {d: 0 for d in week_material}
                for a in reg:
                    if a.assigned_to == uid and a.assigned_date in c:
                        c[a.assigned_date] += 1
                return c

            # (1) shift each weekly chore onto its member's lightest open day
            taken = {(a.template_id, a.assigned_date) for a in reg}
            for _ in range(len(reg)):
                moved = False
                for a in reg:
                    if a.template_id not in weekly_ids:
                        continue
                    load = _day_load(a.assigned_to)
                    light = min(week_material, key=lambda d: load[d])
                    if (load[a.assigned_date] - load[light] >= 2
                            and (a.template_id, light) not in taken):
                        taken.discard((a.template_id, a.assigned_date))
                        taken.add((a.template_id, light))
                        a.assigned_date = light
                        moved = True
                        break
                if not moved:
                    break

            # (2) swap same-chore occurrences between an over-loaded member's
            # heavy day and their light day (held by someone else), when it does
            # not raise the other member's peak.
            by_tpl_date = {}
            for a in reg:
                by_tpl_date.setdefault((a.template_id, a.assigned_date), a)
            for _ in range(len(reg) * len(week_material)):
                loads = {uid: _day_load(uid) for uid in member_ids}
                swapped = False
                for a_h in reg:
                    lm = loads[a_h.assigned_to]
                    if a_h.assigned_date not in lm:
                        continue
                    light = min(week_material, key=lambda d: lm[d])
                    if lm[a_h.assigned_date] - lm[light] < 2:
                        continue
                    a_l = by_tpl_date.get((a_h.template_id, light))
                    if a_l is None or a_l.assigned_to == a_h.assigned_to:
                        continue
                    lo = loads[a_l.assigned_to]
                    if lo[a_h.assigned_date] + 1 <= max(lo.values()):
                        a_h.assigned_to, a_l.assigned_to = (
                            a_l.assigned_to, a_h.assigned_to)
                        swapped = True
                        break
                if not swapped:
                    break

        # Recompute per-member totals from the FINAL assignees — the member-
        # balance pass moved chores between members after _credit ran, so the
        # totals accumulated during generation are stale (prod: preview header
        # showed 160 while the actual list summed to 120).
        pts_by_tpl = {t.id: t.points for t in regular_templates}
        totals = {m.id: 0 for m in members}
        for a in assignments:
            if a.template_id in pts_by_tpl:
                totals[a.assigned_to] = (
                    totals.get(a.assigned_to, 0) + pts_by_tpl[a.template_id]
                )

        return assignments, totals, skipped

    @staticmethod
    async def shuffle_tasks(
        db: AsyncSession,
        family_id: UUID,
        week_of: Optional[date] = None,
        today: Optional[date] = None,
    ) -> List[TaskAssignment]:
        """Back-compat wrapper around shuffle_tasks_detailed — see there."""
        assignments, _skipped = await TaskAssignmentService.shuffle_tasks_detailed(
            db, family_id, week_of=week_of, today=today
        )
        return assignments

    @staticmethod
    async def shuffle_tasks_detailed(
        db: AsyncSession,
        family_id: UUID,
        week_of: Optional[date] = None,
        today: Optional[date] = None,
    ) -> tuple[List[TaskAssignment], list[dict]]:
        """
        Generate weekly task assignments by shuffling templates across family members.

        Deterministic per (family_id, week_monday): same input → same output.
        Idempotent for PENDING (re-shuffle replaces only PENDING rows).

        ``today`` (family-local date; resolved from the family timezone when
        None) drives three guards:
        - a week that already fully ended is rejected (it would only mint
          instantly-overdue rows + auto late penalties);
        - a mid-week shuffle never creates rows for days already past;
        - occurrences whose (template, date) — or (template, date, member)
          for gigs — already exists as a surviving non-PENDING row are NOT
          regenerated (a completed chore must not get a pending twin).

        Returns (assignments, skipped_templates).
        """
        if today is None:
            today = await TaskAssignmentService._family_local_today(db, family_id)
        week_monday = TaskAssignmentService._resolve_week_monday(week_of, today)

        if week_monday + timedelta(days=6) < today:
            raise ValidationException(
                "Cannot shuffle a week that has already ended"
            )

        regular_templates, bonus_templates, members = (
            await TaskAssignmentService._load_shuffle_inputs(db, family_id)
        )

        carry = await TaskAssignmentService._compute_member_carry(
            db, family_id, week_monday, [m.id for m in members]
        )
        # Credit THIS week's already-COMPLETED work into carry so a member who
        # did chores earlier in the week (e.g. Monday) is counted and gets less
        # of the remaining days on a mid-week re-shuffle — "take yesterday's
        # completed tasks into account".
        done_q = (
            select(
                TaskAssignment.assigned_to,
                func.coalesce(func.sum(TaskTemplate.points), 0),
            )
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.week_of == week_monday,
                    TaskAssignment.status == AssignmentStatus.COMPLETED,
                )
            )
            .group_by(TaskAssignment.assigned_to)
        )
        for uid, pts in (await db.execute(done_q)).all():
            if uid in carry:
                carry[uid] = carry.get(uid, 0) + int(pts or 0)

        rng = random.Random(f"{family_id}:{week_monday.isoformat()}")

        # Persisted rotation cursors: same week → same start (idempotent
        # re-shuffle); a new week continues after the stored week's end.
        rotation_starts = {
            t.id: TaskAssignmentService._rotation_start_for_week(t, week_monday)
            for t in regular_templates
            if t.assignment_type == AssignmentType.ROTATE
            and (t.assigned_user_ids or [])
        }

        # Delete existing PENDING rows for this week (preserves completed/
        # overdue/cancelled). Interval-mode ('since_completion') templates are
        # NOT re-expanded by the shuffle (they spawn via
        # spawn_interval_assignments), so their open rows must survive a
        # (re-)shuffle — deleting them here silently vanished the chore until
        # the next hourly sweep and double-advanced the rotation cursor.
        interval_template_ids = select(TaskTemplate.id).where(
            and_(
                TaskTemplate.family_id == family_id,
                func.coalesce(TaskTemplate.recurrence_mode, "weekly")
                == "since_completion",
            )
        )
        delete_stmt = sql_delete(TaskAssignment).where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.week_of == week_monday,
                TaskAssignment.status == AssignmentStatus.PENDING,
                TaskAssignment.template_id.not_in(interval_template_ids),
            )
        )
        await db.execute(delete_stmt)

        rest_days = await TaskAssignmentService._family_rest_days(db, family_id)
        assignments, _totals, skipped = TaskAssignmentService._compute_assignments(
            rng,
            family_id,
            week_monday,
            regular_templates,
            bonus_templates,
            members,
            member_carry=carry,
            rotation_starts=rotation_starts,
            today=today,
            rest_days=rest_days,
        )

        # Guard — survivors: rows that outlived the PENDING delete
        # (completed / claimed / overdue / cancelled) already occupy their
        # occurrence slot. Regenerating them duplicated completed chores and
        # re-opened parent-cancelled ones. Regular templates own one slot per
        # (template, date); gig rows are per-member.
        survivor_rows = (await db.execute(
            select(
                TaskAssignment.template_id,
                TaskAssignment.assigned_date,
                TaskAssignment.assigned_to,
            ).where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.week_of == week_monday,
                )
            )
        )).all()
        if survivor_rows:
            is_bonus_by_id = {
                t.id: t.is_bonus for t in (regular_templates + bonus_templates)
            }
            taken_regular = {
                (tid, d) for tid, d, _uid in survivor_rows
                if not is_bonus_by_id.get(tid, False)
            }
            taken_bonus = {(tid, d, uid) for tid, d, uid in survivor_rows}
            assignments = [
                a for a in assignments
                if (
                    (a.template_id, a.assigned_date, a.assigned_to)
                    not in taken_bonus
                    if is_bonus_by_id.get(a.template_id, False)
                    else (a.template_id, a.assigned_date) not in taken_regular
                )
            ]

        # Real intra-day deadline (end of the local day) so the API's
        # is_overdue field means something — due_date was previously never
        # written anywhere.
        tz = await TaskAssignmentService._family_tz(db, family_id)
        from datetime import time as dt_time
        for a in assignments:
            a.due_date = datetime.combine(
                a.assigned_date, dt_time(23, 59, 59), tzinfo=tz
            ).astimezone(timezone.utc)

        # Persist the rotation state actually used for this week so the next
        # shuffle continues the round-robin instead of restarting at 0.
        # rotation_cursor stores the NEXT start (start used + occurrences
        # generated NOW, with the interval as it was at shuffle time), so a
        # later interval change can't corrupt the continuation offset.
        # Templates the shuffle SKIPPED must not advance — that drifted the
        # persisted cursor on dead templates.
        skipped_ids = {s["template_id"] for s in skipped}
        for t in regular_templates:
            if t.id in rotation_starts and t.id not in skipped_ids:
                t.rotation_week_of = week_monday
                t.rotation_cursor = rotation_starts[
                    t.id
                ] + TaskAssignmentService._occurrences_per_week(
                    t.interval_days or 1,
                    getattr(t, "days_of_week", None),
                )

        for a in assignments:
            db.add(a)

        await db.commit()
        # Single re-select (with template eagerly loaded) instead of one
        # round-trip per row — a full-family shuffle used to issue N refreshes.
        if assignments:
            ids = [a.id for a in assignments]
            assignments = list((await db.execute(
                select(TaskAssignment)
                .options(selectinload(TaskAssignment.template))
                .where(TaskAssignment.id.in_(ids))
                .order_by(TaskAssignment.assigned_date, TaskAssignment.created_at)
            )).scalars().all())

        # TASK_ASSIGNED: one localized notification (+ push) per assignee,
        # aggregated so a weekly shuffle never spams a device per-row.
        # Best-effort — a notification failure must never break the shuffle.
        try:
            from collections import Counter
            from app.services.notification_service import NotificationService

            counts = Counter(a.assigned_to for a in assignments)
            for uid, cnt in counts.items():
                key = "task_assigned_one" if cnt == 1 else "task_assigned"
                await NotificationService.create_localized(
                    db,
                    family_id=family_id,
                    key=key,
                    user_id=uid,
                    params={"count": cnt},
                    link="/dashboard",
                )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "task-assigned notification fan-out failed"
            )

        return assignments, skipped

    @staticmethod
    async def auto_shuffle_all(db: AsyncSession) -> int:
        """Sweep across ALL families: generate the CURRENT week for families
        that already use the weekly shuffle but haven't generated it yet.

        Opt-in by evidence: only families with at least one historical
        assignment (any week before the current one) qualify — a family that
        never shuffled is never surprised by auto-generated chores. Idempotent
        per week: families with ANY assignment row in the current week are
        skipped, so this can run hourly (and self-heals a Monday the backend
        spent down). Returns number of assignments created.

        Intended for the background scheduler (leader-only).
        """
        import logging
        logger = logging.getLogger(__name__)

        # Families with at least one active weekly-mode template.
        weekly_only = func.coalesce(
            TaskTemplate.recurrence_mode, "weekly"
        ) != "since_completion"
        family_ids = [
            fid for (fid,) in (await db.execute(
                select(TaskTemplate.family_id).where(
                    and_(TaskTemplate.is_active == True, weekly_only)  # noqa: E712
                ).distinct()
            )).all()
        ]

        created_total = 0
        for fid in family_ids:
            try:
                today = await TaskAssignmentService._family_local_today(db, fid)
                week_monday = TaskAssignmentService._resolve_week_monday(
                    None, today
                )
                counts = (await db.execute(
                    select(
                        func.count().filter(
                            TaskAssignment.week_of == week_monday
                        ),
                        func.count().filter(
                            TaskAssignment.week_of < week_monday
                        ),
                    ).select_from(TaskAssignment).where(
                        TaskAssignment.family_id == fid
                    )
                )).one()
                current_week_rows, historical_rows = int(counts[0]), int(counts[1])
                if current_week_rows > 0:  # already generated — idempotent
                    continue
                if historical_rows == 0:  # never used the shuffle — opt-out
                    continue
                assignments, _skipped = (
                    await TaskAssignmentService.shuffle_tasks_detailed(
                        db, fid, week_of=week_monday, today=today
                    )
                )
                created_total += len(assignments)
                if assignments:
                    logger.info(
                        "auto-shuffle generated %d assignment(s) for family %s",
                        len(assignments), fid,
                    )
            except Exception:
                logger.exception("auto-shuffle failed for family %s", fid)
        return created_total

    @staticmethod
    async def preview_shuffle(
        db: AsyncSession,
        family_id: UUID,
        week_of: Optional[date] = None,
        today: Optional[date] = None,
    ) -> dict:
        """
        Dry-run shuffle — no DB writes. Returns the proposed assignment plan plus
        per-member point totals (current week) and cross-week carry used for bias.
        Mirrors shuffle_tasks_detailed's date guards so what you preview is what
        a real shuffle would create.
        """
        if today is None:
            today = await TaskAssignmentService._family_local_today(db, family_id)
        week_monday = TaskAssignmentService._resolve_week_monday(week_of, today)

        regular_templates, bonus_templates, members = (
            await TaskAssignmentService._load_shuffle_inputs(db, family_id)
        )
        carry = await TaskAssignmentService._compute_member_carry(
            db, family_id, week_monday, [m.id for m in members]
        )
        # Credit THIS week's already-COMPLETED work into carry so a member who
        # did chores earlier in the week (e.g. Monday) is counted and gets less
        # of the remaining days on a mid-week re-shuffle — "take yesterday's
        # completed tasks into account".
        done_q = (
            select(
                TaskAssignment.assigned_to,
                func.coalesce(func.sum(TaskTemplate.points), 0),
            )
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.week_of == week_monday,
                    TaskAssignment.status == AssignmentStatus.COMPLETED,
                )
            )
            .group_by(TaskAssignment.assigned_to)
        )
        for uid, pts in (await db.execute(done_q)).all():
            if uid in carry:
                carry[uid] = carry.get(uid, 0) + int(pts or 0)

        rng = random.Random(f"{family_id}:{week_monday.isoformat()}")
        # Same rotation starts as a real shuffle would use — but NOT persisted
        # (preview must be side-effect free).
        rotation_starts = {
            t.id: TaskAssignmentService._rotation_start_for_week(t, week_monday)
            for t in regular_templates
            if t.assignment_type == AssignmentType.ROTATE
            and (t.assigned_user_ids or [])
        }
        rest_days = await TaskAssignmentService._family_rest_days(db, family_id)
        assignments, totals, skipped = TaskAssignmentService._compute_assignments(
            rng,
            family_id,
            week_monday,
            regular_templates,
            bonus_templates,
            members,
            member_carry=carry,
            rotation_starts=rotation_starts,
            today=today,
            rest_days=rest_days,
        )

        # Build lightweight detail dicts (no DB IDs since not persisted)
        member_by_id = {m.id: m for m in members}
        template_by_id = {t.id: t for t in (regular_templates + bonus_templates)}
        items = []
        for a in assignments:
            tmpl = template_by_id.get(a.template_id)
            mem = member_by_id.get(a.assigned_to)
            items.append({
                "template_id": a.template_id,
                "template_title": tmpl.title if tmpl else "",
                "template_title_es": tmpl.title_es if tmpl else None,
                "template_points": tmpl.points if tmpl else 0,
                "template_is_bonus": tmpl.is_bonus if tmpl else False,
                "assigned_to": a.assigned_to,
                "assigned_user_name": mem.name if mem else "",
                "assigned_date": a.assigned_date,
                "week_of": a.week_of,
            })

        return {
            "week_of": week_monday,
            "totals_by_member": [
                {
                    "user_id": m.id,
                    "user_name": m.name,
                    "points_this_week": totals.get(m.id, 0),
                    "points_carry": carry.get(m.id, 0),
                }
                for m in members
            ],
            "assignments": items,
            "skipped_templates": skipped,
        }

    # ─── Assignment Queries ──────────────────────────────────────────

    @staticmethod
    async def get_assignment(
        db: AsyncSession, assignment_id: UUID, family_id: UUID,
        for_update: bool = False,
    ) -> TaskAssignment:
        """Get an assignment by ID with template eagerly loaded.

        Pass for_update=True to take a row lock (SELECT ... FOR UPDATE) so
        concurrent state transitions (approve / claim) serialize and cannot
        both pass a check-then-write guard. selectinload issues separate
        queries, so the lock applies only to the task_assignments row.
        """
        query = (
            select(TaskAssignment)
            .options(
                selectinload(TaskAssignment.template),
                selectinload(TaskAssignment.assigned_user),
            )
            .where(
                and_(
                    TaskAssignment.id == assignment_id,
                    TaskAssignment.family_id == family_id,
                )
            )
        )
        if for_update:
            query = query.with_for_update(of=TaskAssignment)
        result = await db.execute(query)
        assignment = result.scalar_one_or_none()
        if not assignment:
            raise NotFoundException("Assignment not found")
        return assignment

    @staticmethod
    async def list_assignments_for_week(
        db: AsyncSession,
        family_id: UUID,
        week_of: date,
        user_id: Optional[UUID] = None,
        status: Optional[AssignmentStatus] = None,
    ) -> List[TaskAssignment]:
        """List assignments for a given week"""
        week_monday = TaskAssignmentService._get_monday(week_of)

        query = (
            select(TaskAssignment)
            .options(
                selectinload(TaskAssignment.template),
                selectinload(TaskAssignment.assigned_user),
            )
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.week_of == week_monday,
                )
            )
        )

        if user_id:
            query = query.where(TaskAssignment.assigned_to == user_id)
        if status:
            query = query.where(TaskAssignment.status == status)

        query = query.order_by(
            TaskAssignment.assigned_date.asc(), TaskAssignment.created_at.asc()
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def list_assignments_for_date(
        db: AsyncSession,
        family_id: UUID,
        target_date: date,
        user_id: Optional[UUID] = None,
    ) -> List[TaskAssignment]:
        """List assignments for a specific date"""
        query = (
            select(TaskAssignment)
            .options(
                selectinload(TaskAssignment.template),
                selectinload(TaskAssignment.assigned_user),
            )
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date == target_date,
                )
            )
        )

        if user_id:
            query = query.where(TaskAssignment.assigned_to == user_id)

        query = query.order_by(TaskAssignment.created_at.asc())
        result = await db.execute(query)
        return list(result.scalars().all())

    # ─── Completion + Gating ─────────────────────────────────────────

    @staticmethod
    async def has_open_mandatory_through(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        through_date: date,
    ) -> bool:
        """
        True if any mandatory (non-bonus) assignment with assigned_date
        on or before ``through_date`` is still open (PENDING or OVERDUE).

        Carry-over semantics: an unfinished mandatory from yesterday
        blocks today's gigs. CANCELLED counts as resolved (parent waived).
        Future-dated mandatory rows are intentionally ignored.
        """
        q = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.assigned_to == user_id,
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date <= through_date,
                    TaskTemplate.is_bonus.is_(False),
                    TaskAssignment.status.in_(
                        [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
                    ),
                )
            )
        )
        return (await db.execute(q)).scalar_one() > 0

    @staticmethod
    async def list_open_mandatory_before(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        before_date: date,
    ) -> List[TaskAssignment]:
        """Open (PENDING/OVERDUE) mandatory assignments dated strictly BEFORE
        ``before_date`` — i.e. the prior-day blockers that the sweep flipped to
        OVERDUE and that vanish from today's list, yet keep bonus/gigs locked.
        Returned so the dashboard can surface them ("Atrasadas") and let the kid
        finish them (can_complete already allows OVERDUE).
        """
        query = (
            select(TaskAssignment)
            .options(
                selectinload(TaskAssignment.template),
                selectinload(TaskAssignment.assigned_user),
            )
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.assigned_to == user_id,
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date < before_date,
                    TaskTemplate.is_bonus.is_(False),
                    TaskAssignment.status.in_(
                        [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
                    ),
                )
            )
            .order_by(TaskAssignment.assigned_date.asc())
        )
        return list((await db.execute(query)).scalars().all())

    @staticmethod
    async def complete_assignment(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
        proof_text: Optional[str] = None,
        proof_image_url: Optional[str] = None,
    ) -> TaskAssignment:
        """
        Mark an assignment as completed.

        Mandatory (is_bonus=false): completes silently, awards no points.
        Gig (is_bonus=true): requires all today's mandatory done first, requires
        proof_text, and enters PENDING approval state. Points are credited only
        when a parent approves via approve_gig().
        """
        # Row-lock the assignment: the mandatory path now awards points, so a
        # concurrent double-submit (kid double-tapping "complete") must not pass
        # the can_complete check twice and double-award.
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id, for_update=True
        )

        if not assignment.can_complete:
            raise ValidationException(
                f"Assignment cannot be completed. Current status: {assignment.status.value}"
            )

        if assignment.assigned_to != user_id:
            raise ForbiddenException(
                "Only the assigned user can complete this assignment"
            )

        # Future-dated occurrences cannot be completed early — otherwise a kid
        # can bank the entire week's points Monday morning without the chores
        # actually happening on their days.
        local_today = await TaskAssignmentService._family_local_today(
            db, family_id
        )
        if assignment.assigned_date > local_today:
            raise ValidationException(
                "Esta tarea es para un día futuro — complétala ese día / "
                "This task is scheduled for a future day — complete it then"
            )

        template = assignment.template
        auto_approved = False

        # Competition gigs are first-CLAIM-wins: completing straight from
        # PENDING would bypass the claim race and let several kids get paid
        # for the same gig.
        if (
            template.is_bonus
            and (template.gig_mode or "claim") == "competition"
            and assignment.status == AssignmentStatus.PENDING
        ):
            raise ValidationException(
                "Reclama esta tarea primero — el primero en reclamar gana / "
                "Claim this gig first — first to claim wins"
            )

        if template.is_bonus:
            # Gig path
            has_open_mandatory = await TaskAssignmentService.has_open_mandatory_through(
                db, user_id, family_id, assignment.assigned_date
            )
            if has_open_mandatory:
                raise ForbiddenException(
                    "Finish any open mandatory tasks (today + overdue) before claiming a gig"
                )

            if not proof_text or not proof_text.strip():
                raise ValidationException("Gigs require proof text describing what you did")

            if template.requires_proof and not proof_image_url:
                raise ValidationException(
                    "Esta tarea requiere una foto del trabajo terminado / "
                    "This task requires a photo of the finished work"
                )

            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            assignment.proof_text = proof_text.strip()
            if proof_image_url:
                assignment.proof_image_url = proof_image_url

            # Auto-approval has two independent paths:
            #   1. Trust streak — user has earned N consecutive approvals.
            #   2. AI photo validation — vision model agrees the photo
            #      shows the task done, above settings threshold.
            # If either path approves, points credit immediately.
            #
            # Path 2 processes a KID-taken photo, so it requires the family's
            # explicit AI-processing opt-in (families.ai_processing_consent)
            # AND a paid plan (ai_features — AI is paid-only). Without either
            # there is NO AI call — the gig simply lands in the existing
            # manual parent-approval queue (HITL path).
            from app.core.config import settings
            from app.core.premium import family_tier_allows
            from app.services.family_service import FamilyService
            from app.services.points_service import PointsService
            from app.services.task_proof_validator import validate_proof_photo
            child = await get_user_by_id(db, user_id)
            threshold = max(1, settings.GIG_AUTO_APPROVE_STREAK)

            auto_approved = False
            approval_reason = ""

            if child.gig_trust_streak >= threshold:
                auto_approved = True
                approval_reason = "Auto-approved via trust streak"
            elif (
                assignment.proof_image_url
                and await FamilyService.has_ai_processing_consent(db, family_id)
                and await family_tier_allows(db, family_id, "ai_features")
            ):
                validation = await validate_proof_photo(
                    assignment.proof_image_url,
                    template.title,
                    template.description,
                )
                if validation is not None:
                    assignment.ai_validation_score = validation.score
                    assignment.ai_validation_notes = validation.explanation
                    if validation.score >= settings.GIG_AI_AUTO_APPROVE_THRESHOLD:
                        auto_approved = True
                        approval_reason = (
                            f"Auto-approved via AI photo check "
                            f"(score {validation.score:.2f}): {validation.explanation}"
                        )

            # Auto-approval consumes the SAME monthly gig cap as a parent
            # approval — without this check the trust-streak/AI path let
            # families blow straight past the plan limit. At the cap the gig
            # falls back to the manual parent queue (no error).
            if auto_approved:
                from app.core.premium import get_family_plan
                from app.services.usage_service import UsageService
                plan = await get_family_plan(db, child)
                cap = int(plan.limits.get("max_gigs_per_month", 3))
                incremented = await UsageService.try_increment_within_limit(
                    db, family_id, "gig_completion", cap, amount=1,
                )
                if incremented is None:
                    auto_approved = False

            if auto_approved:
                assignment.approval_status = ApprovalStatus.APPROVED
                assignment.approved_at = datetime.now(timezone.utc)
                assignment.approval_notes = approval_reason
                pts = await TaskAssignmentService._award_assignment(
                    db, assignment, template, user_id
                )
                child.gig_trust_streak += 1
                from app.services.notification_service import NotificationService
                from app.services.pet_service import PetService
                await NotificationService.create_localized_no_commit(
                    db,
                    family_id=family_id,
                    key="gig_approved_auto",
                    user_id=user_id,
                    params={
                        "pts": pts,
                        "title": template.title,
                        "reason": approval_reason,
                    },
                )
                await PetService.on_task_completed(db, user_id, is_bonus=True)
            else:
                assignment.approval_status = ApprovalStatus.PENDING
        elif template.requires_proof:
            # Mandatory chore WITH photo proof (W4.3): the kid must attach a
            # photo; the completion parks in the parent approval queue and
            # points credit only on approval (see approve_gig's mandatory
            # branch). Rejection re-opens the assignment.
            if not proof_image_url:
                raise ValidationException(
                    "Esta tarea requiere una foto del trabajo terminado / "
                    "This task requires a photo of the finished work"
                )
            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            assignment.proof_text = (proof_text or "").strip() or None
            assignment.proof_image_url = proof_image_url
            assignment.approval_status = ApprovalStatus.PENDING
        else:
            # Mandatory path — silent completion, awards privilege points
            # (no approval). Cash is reserved for gigs; chores credit points.
            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            from app.services.points_service import PointsService
            await PointsService.award_assignment_completion(
                db, user_id, assignment.id, template.effective_points
            )
            from app.services.pet_service import PetService
            await PetService.on_task_completed(db, user_id, is_bonus=False)

        await db.commit()
        await db.refresh(assignment)

        if auto_approved:
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            try:
                from app.services.reward_goal_service import RewardGoalService
                refreshed = await get_user_by_id(db, user_id)
                await RewardGoalService.check_nudge(
                    user_id=user_id,
                    family_id=family_id,
                    new_balance=refreshed.points,
                    db=db,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "check_nudge after task auto-approve failed", exc_info=True
                )

        if not template.is_bonus and assignment.approval_status != ApprovalStatus.PENDING:
            # Mandatory chores now grant privilege points, so a completion can
            # push a kid over a points-priced reward goal — nudge them.
            # (Skipped for proof-required chores awaiting approval — no points
            # moved yet; the nudge runs on approval instead.)
            try:
                from app.services.reward_goal_service import RewardGoalService
                refreshed = await get_user_by_id(db, user_id)
                await RewardGoalService.check_nudge(
                    user_id=user_id,
                    family_id=family_id,
                    new_balance=refreshed.points,
                    db=db,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "check_nudge after mandatory completion failed", exc_info=True
                )

        # Fire-and-forget notifications on submission for approval (gigs AND
        # proof-required chores). Failures are swallowed so the API response
        # is never blocked by an upstream issue. Skip for auto-approved gigs
        # — parents don't need a heads-up on something already credited.
        if assignment.approval_status == ApprovalStatus.PENDING:
            child = await get_user_by_id(db, user_id)
            try:
                from app.services.email_service import EmailService
                await EmailService.notify_parents_gig_pending(
                    db,
                    family_id=family_id,
                    child_name=child.name,
                    gig_title=template.title,
                    proof_text=assignment.proof_text or "",
                    proof_image_url=assignment.proof_image_url,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("notify_parents_gig_pending failed")
            try:
                from app.services.notification_service import NotificationService
                # Family-wide notification (parents see it on dashboard).
                # Broadcasts have no single recipient — Spanish-first copy.
                await NotificationService.create_localized(
                    db,
                    family_id=family_id,
                    key="gig_pending_review",
                    user_id=None,
                    params={"child": child.name, "title": template.title},
                    link="/parent/approvals",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("notification create failed")
            try:
                from app.services.push_service import PushService
                await PushService.fan_out_pending_gig(
                    db,
                    family_id=family_id,
                    child_name=child.name,
                    gig_title=template.title,
                    points=template.award_points_per_completer,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("fan_out_pending_gig push failed")

        # Auto-post a completion card into family chat (Campfire liveliness) —
        # but only when this completion actually credited points: a mandatory
        # chore that completed silently, or a gig auto-approved just now.
        # Proof-required chores + gigs still awaiting parent review post later,
        # on approval (see approve_gig). Best-effort — never blocks the response.
        _post_points = None
        if template.is_bonus:
            if auto_approved:
                _post_points = pts
        elif (
            not template.requires_proof
            and assignment.status == AssignmentStatus.COMPLETED
        ):
            _post_points = template.effective_points
        if _post_points is not None:
            try:
                from app.services.family_chat_service import FamilyChatService
                completer = await get_user_by_id(db, user_id)
                await FamilyChatService.post_completion(
                    db,
                    family_id,
                    user_name=completer.name,
                    title=template.title,
                    points=int(_post_points),
                    is_bonus=bool(template.is_bonus),
                    image_url=assignment.proof_image_url,
                    sender_id=user_id,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "auto-post completion to chat failed", exc_info=True
                )

        return assignment

    @staticmethod
    async def _award_assignment(
        db: AsyncSession, assignment, template, user_id, award_pct: int = 100
    ) -> int:
        """Credit a bonus-task completer and return the points credited to THEM.

        Bonus tasks (is_bonus=True) award privilege POINTS, like mandatory
        chores — they are optional extra-credit tasks, not paid gigs. (Cash is
        earned only on the /gigs board; see GigClaimService.) Non-collaboration
        bonus tasks award the full effective_points; collaboration re-splits the
        instance pot among ALL currently-approved completers (see
        _settle_collaboration), so the total awarded always equals the pot. The
        caller must NOT also award separately — this method performs the credit.
        """
        from app.services.points_service import PointsService

        if (template.gig_mode or "claim") != "collaboration":
            # Integer half-up partial-credit scaling (grade from parent review).
            pts = (template.award_points_per_completer * award_pct + 50) // 100
            await PointsService.award_gig_points(db, user_id, assignment.id, pts)
            return pts
        # Collaboration: _resolve_grade guarantees award_pct == 100 here.
        return await TaskAssignmentService._settle_collaboration(db, assignment, template)

    @staticmethod
    async def _settle_collaboration(db: AsyncSession, assignment, template) -> int:
        """Re-split the collaboration pot among all currently-approved
        completers of THIS instance and reconcile each completer's net award.

        The pot (effective_points) is divided by the ACTUAL number of approved
        completers — not collaboration_min_count — so the total awarded always
        equals the pot no matter how many complete. As each new completer is
        approved the split tightens, so earlier completers' shares shrink; the
        difference is reconciled with a correcting (possibly negative)
        transaction. Conserves the pot exactly for any number of completers,
        and is scoped by (template_id, assigned_date) so a daily collaboration
        gig settles each date independently.

        The caller has already marked this assignment APPROVED, so it is part
        of the settled set. Returns the points THIS completer ends up with.
        """
        from app.services.points_service import PointsService

        # Lock the whole instance sibling set (all statuses, deterministic id
        # order — no deadlock) so concurrent approvals settle one at a time and
        # never split by a stale count. Held until the caller commits.
        await db.execute(
            select(TaskAssignment.id)
            .where(
                and_(
                    TaskAssignment.template_id == template.id,
                    TaskAssignment.assigned_date == assignment.assigned_date,
                )
            )
            .order_by(TaskAssignment.id)
            .with_for_update()
        )

        completers = (
            await db.execute(
                select(TaskAssignment)
                .where(
                    and_(
                        TaskAssignment.template_id == template.id,
                        TaskAssignment.assigned_date == assignment.assigned_date,
                        TaskAssignment.approval_status == ApprovalStatus.APPROVED,
                    )
                )
                .order_by(
                    TaskAssignment.approved_at.asc().nullslast(),
                    TaskAssignment.id.asc(),
                )
            )
        ).scalars().all()

        shares = TaskTemplate.distribute_points(
            template.effective_points, len(completers) or 1
        )

        this_share = 0
        for share, completer in zip(shares, completers):
            # Net points already credited to this completer for this instance.
            current = (
                await db.execute(
                    select(func.coalesce(func.sum(PointTransaction.points), 0))
                    .where(
                        and_(
                            PointTransaction.assignment_id == completer.id,
                            PointTransaction.type == TransactionType.GIG_APPROVED,
                        )
                    )
                )
            ).scalar() or 0
            delta = int(share) - int(current)
            if delta != 0:
                await PointsService.award_gig_points(
                    db,
                    completer.assigned_to,
                    completer.id,
                    delta,
                    description=(
                        f"Collaboration gig split among {len(completers)} "
                        f"— your share: {share} pts"
                    ),
                )
            if completer.id == assignment.id:
                this_share = int(share)
        return this_share

    # ─── Gig claim (reserve before doing) ────────────────────────────

    @staticmethod
    async def claim_gig(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
    ) -> TaskAssignment:
        """
        Reserve a gig before working on it. Transitions PENDING → CLAIMED.

        Only the assignee can claim. Mandatory rows reject (no claim
        semantic). Gating still applies — must finish open mandatory
        first.
        """
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )

        if not assignment.template.is_bonus:
            raise ValidationException("Only gigs can be claimed")

        if assignment.assigned_to != user_id:
            raise ForbiddenException("Only the assigned user can claim this gig")

        tmpl = assignment.template

        # Competition mode is "first claim wins". Serialize every claim for
        # this template+week by locking the whole sibling set in one
        # deterministic (id-ordered) SELECT ... FOR UPDATE — a single ordered
        # lock acquisition, so concurrent claimers queue instead of
        # deadlocking. populate_existing refreshes our own already-loaded row
        # from the locked read, so a claimer that lost the race sees its row
        # cancelled (and/or a sibling already CLAIMED) and is rejected,
        # guaranteeing exactly one winner.
        if tmpl.is_bonus and tmpl.gig_mode == "competition":
            siblings = (
                await db.execute(
                    select(TaskAssignment)
                    .where(
                        and_(
                            TaskAssignment.family_id == family_id,
                            TaskAssignment.template_id == tmpl.id,
                            TaskAssignment.week_of == assignment.week_of,
                        )
                    )
                    .order_by(TaskAssignment.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars().all()
            assignment = next(
                (s for s in siblings if s.id == assignment.id), assignment
            )
            if any(
                s.id != assignment.id
                and s.status in (AssignmentStatus.CLAIMED, AssignmentStatus.COMPLETED)
                for s in siblings
            ):
                raise ValidationException("Esta gig ya fue reclamada por alguien más")

        if not assignment.can_claim:
            raise ValidationException(
                f"Gig cannot be claimed in status {assignment.status.value}"
            )

        if await TaskAssignmentService.has_open_mandatory_through(
            db, user_id, family_id, assignment.assigned_date
        ):
            raise ForbiddenException(
                "Finish any open mandatory tasks (today + overdue) before claiming a gig"
            )

        assignment.status = AssignmentStatus.CLAIMED
        assignment.claimed_at = datetime.now(timezone.utc)

        # Competition mode: cancel the sibling assignments (already locked
        # above) for the same template+week so other kids see it disappear.
        if tmpl.is_bonus and tmpl.gig_mode == "competition":
            from sqlalchemy import update as sql_update
            stmt = (
                sql_update(TaskAssignment)
                .where(
                    and_(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.template_id == tmpl.id,
                        TaskAssignment.week_of == assignment.week_of,
                        TaskAssignment.id != assignment.id,
                        TaskAssignment.status == AssignmentStatus.PENDING,
                    )
                )
                .values(status=AssignmentStatus.CANCELLED)
            )
            await db.execute(stmt)

        await db.commit()
        await db.refresh(assignment)
        return assignment

    @staticmethod
    async def unclaim_gig(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
    ) -> TaskAssignment:
        """Release a claim and return the gig to PENDING."""
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )
        if assignment.assigned_to != user_id:
            raise ForbiddenException("Only the assignee can release a claim")
        if assignment.status != AssignmentStatus.CLAIMED:
            raise ValidationException(
                f"Only CLAIMED gigs can be unclaimed (current: {assignment.status.value})"
            )
        assignment.status = AssignmentStatus.PENDING
        assignment.claimed_at = None
        await db.commit()
        await db.refresh(assignment)
        return assignment

    # ─── Gig approval (parent-only) ──────────────────────────────────

    @staticmethod
    def _resolve_grade(
        approve: bool,
        grade: Optional[str],
        partial_credit_pct: Optional[int],
        template,
    ) -> tuple[Optional[str], Optional[int], int]:
        """Validate the (approve, grade, pct) triple.

        Returns (grade, stored_pct, award_pct). award_pct is what point awards
        are scaled by (100 for full/legacy, 0 for missed/reject). Legacy calls
        (grade=None) keep today's exact behavior: full credit on approve,
        NULL grade on reject.
        """
        if grade is None:
            return ("full" if approve else None, None, 100 if approve else 0)
        if grade not in ("full", "partial", "missed"):
            raise ValidationException(f"Unknown grade: {grade}")
        if approve and grade == "missed":
            raise ValidationException("missed grade requires approve=false")
        if not approve and grade != "missed":
            raise ValidationException(f"{grade} grade requires approve=true")
        if grade == "partial":
            if (template.gig_mode or "claim") == "collaboration":
                raise ValidationException(
                    "partial credit is not supported on collaboration gigs "
                    "(the pot re-split conserves total points)"
                )
            pct = 50 if partial_credit_pct is None else partial_credit_pct
            if not (1 <= pct <= 99):
                raise ValidationException("partial credit must be 1-99 percent")
            return ("partial", pct, pct)
        if grade == "full":
            return ("full", None, 100)
        return ("missed", None, 0)

    @staticmethod
    async def approve_gig(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        parent_id: UUID,
        approve: bool,
        notes: Optional[str] = None,
        grade: Optional[str] = None,
        partial_credit_pct: Optional[int] = None,
    ) -> TaskAssignment:
        from app.models.user import UserRole
        from app.services.points_service import PointsService
        from app.core.premium import get_family_plan
        from app.services.usage_service import UsageService

        parent = await get_user_by_id(db, parent_id)
        if parent.family_id != family_id or parent.role != UserRole.PARENT:
            raise ForbiddenException("Only parents in this family can approve gigs")

        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id, for_update=True
        )

        if assignment.approval_status != ApprovalStatus.PENDING:
            raise ValidationException(
                f"Gig already decided (status: {assignment.approval_status.value})"
            )

        grade, stored_pct, award_pct = TaskAssignmentService._resolve_grade(
            approve, grade, partial_credit_pct, assignment.template
        )
        assignment.completion_grade = grade
        assignment.partial_credit_pct = stored_pct
        assignment.approved_by = parent_id
        assignment.approved_at = datetime.now(timezone.utc)
        assignment.approval_notes = notes

        # Mandatory chores with requires_proof also flow through this queue —
        # they award privilege points on approval (no gig cap, no trust
        # streak, TASK_COMPLETED transaction), unlike bonus-task gigs.
        is_bonus = bool(assignment.template.is_bonus)

        if approve:
            if is_bonus:
                # Enforce per-family monthly gig approval cap. Atomic increment
                # prevents two concurrent approvals from slipping past the limit.
                plan = await get_family_plan(db, parent)
                limit = int(plan.limits.get("max_gigs_per_month", 3))
                new_count = await UsageService.try_increment_within_limit(
                    db, family_id, "gig_completion", limit, amount=1,
                )
                if new_count is None:
                    raise ValidationException(
                        f"Family has hit the monthly gig approval cap ({limit}). "
                        "Upgrade to raise the cap."
                    )
            assignment.approval_status = ApprovalStatus.APPROVED
            child = await get_user_by_id(db, assignment.assigned_to)
            if is_bonus:
                pts = await TaskAssignmentService._award_assignment(
                    db, assignment, assignment.template, assignment.assigned_to,
                    award_pct=award_pct,
                )
                # Increment trust streak so the child graduates to
                # auto-approval after enough consecutive approvals.
                child.gig_trust_streak += 1
            else:
                # Integer half-up so partial credit never silently floors away
                # a point (25 pts × 50% → 13, not 12).
                pts = (assignment.template.effective_points * award_pct + 50) // 100
                await PointsService.award_assignment_completion(
                    db, assignment.assigned_to, assignment.id, pts
                )
            from app.services.notification_service import NotificationService
            from app.services.pet_service import PetService
            await PetService.on_task_completed(
                db, assignment.assigned_to, is_bonus=is_bonus
            )
            await db.commit()
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            child_lang = getattr(child, "preferred_lang", None) or "es"
            try:
                from app.services.push_service import PushService as _PushService
                _p_title, _p_body = NotificationService.render(
                    "task_approved_push",
                    child_lang,
                    {"title": assignment.template.title, "pts": pts},
                )
                await _PushService.send_to_user(db, assignment.assigned_to, {
                    "title": _p_title,
                    "body": _p_body,
                    "url": "/dashboard",
                    "tag": "task-approved",
                })
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "push task-approved failed", exc_info=True
                )
            # NotificationService.create commits + fans out push.
            await NotificationService.create_localized(
                db,
                family_id=family_id,
                key="gig_approved",
                user_id=assignment.assigned_to,
                params={"pts": pts, "title": assignment.template.title},
                link="/dashboard",
                lang=child_lang,
            )
        else:
            assignment.approval_status = ApprovalStatus.REJECTED
            child = await get_user_by_id(db, assignment.assigned_to)
            if is_bonus:
                # Reset trust streak — a rejection signals the child still
                # needs review on subsequent gigs.
                child.gig_trust_streak = 0
            else:
                # Proof-required chore rejected: re-open it so the kid must
                # redo the work (and it blocks gigs again until done).
                assignment.status = AssignmentStatus.PENDING
                assignment.completed_at = None
            from app.services.notification_service import NotificationService
            await db.commit()
            await NotificationService.create_localized(
                db,
                family_id=family_id,
                key="gig_rejected",
                user_id=assignment.assigned_to,
                params={"title": assignment.template.title, "notes": notes or ""},
                link="/dashboard",
                lang=getattr(child, "preferred_lang", None) or "es",
            )

        await db.commit()
        await db.refresh(assignment)

        # Auto-post the approved completion into family chat (with the proof
        # photo when present) so parent approvals light up the shared thread.
        # Only on approve — rejections don't celebrate. Best-effort; never
        # blocks the approval response.
        if approve:
            try:
                from app.services.family_chat_service import FamilyChatService
                await FamilyChatService.post_completion(
                    db,
                    family_id,
                    user_name=child.name,
                    title=assignment.template.title,
                    points=int(pts),
                    is_bonus=is_bonus,
                    image_url=assignment.proof_image_url,
                    sender_id=assignment.assigned_to,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "auto-post approved completion to chat failed", exc_info=True
                )

        return assignment

    @staticmethod
    async def list_for_user_today_with_locks(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
    ) -> list[dict]:
        """Return today's assignments for a user with is_locked + approval fields."""
        today = await TaskAssignmentService._user_local_today(db, user_id)
        has_open = await TaskAssignmentService.has_open_mandatory_through(
            db, user_id, family_id, today
        )
        q = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_date == today,
            )
            .order_by(TaskAssignment.assigned_date)
        )
        rows = (await db.execute(q)).scalars().all()
        out = []
        for r in rows:
            is_bonus = r.template.is_bonus
            out.append({
                "id": r.id,
                "template_id": r.template_id,
                "title": r.template.title,
                "title_es": r.template.title_es,
                # What the kid will actually earn (effort multiplier applied)
                # — showing raw base points made the award look "wrong".
                "points": r.template.effective_points,
                "is_bonus": is_bonus,
                "status": r.status.value,
                "approval_status": r.approval_status.value if r.approval_status else "none",
                "proof_text": r.proof_text,
                "is_locked": is_bonus and has_open and r.status != AssignmentStatus.COMPLETED,
                "assigned_date": r.assigned_date,
                "completed_at": r.completed_at,
                "completion_grade": r.completion_grade,
                "partial_credit_pct": r.partial_credit_pct,
                "approval_notes": r.approval_notes,
            })
        return out

    @staticmethod
    async def list_pending_approvals(
        db: AsyncSession,
        family_id: UUID,
    ) -> list[TaskAssignment]:
        from sqlalchemy.orm import selectinload
        q = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.approval_status == ApprovalStatus.PENDING,
            )
            .order_by(TaskAssignment.completed_at.asc())
        )
        result = await db.execute(q)
        return list(result.scalars().all())

    # ─── Parent Edit (reassign / reschedule / cancel) ────────────────

    @staticmethod
    async def patch_assignment(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        assigned_to: Optional[UUID] = None,
        assigned_date: Optional[date] = None,
        status: Optional[AssignmentStatus] = None,
    ) -> TaskAssignment:
        """
        Parent-only edit on an individual assignment.

        - assigned_to: must belong to same family.
        - assigned_date: any date; week_of recomputed to its Monday.
        - status: only PENDING (revive) or CANCELLED allowed. COMPLETED must go
          through complete_assignment() so points are awarded correctly.
        """
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id, for_update=True
        )

        if status is not None and status not in (
            AssignmentStatus.PENDING,
            AssignmentStatus.CANCELLED,
        ):
            raise ValidationException(
                "PATCH only allows status=pending or status=cancelled. Use /complete to mark completed."
            )

        if assigned_to is not None:
            new_user = await get_user_by_id(db, assigned_to)
            if new_user.family_id != family_id:
                raise ForbiddenException(
                    "Cannot assign to a user outside this family"
                )
            assignment.assigned_to = assigned_to

        if assigned_date is not None:
            assignment.assigned_date = assigned_date
            assignment.week_of = TaskAssignmentService._get_monday(assigned_date)

        if status is not None:
            template = assignment.template
            reopening_completed = (
                assignment.status == AssignmentStatus.COMPLETED
                and status in (AssignmentStatus.PENDING, AssignmentStatus.CANCELLED)
            )
            if reopening_completed and template is not None:
                if template.is_bonus and assignment.approval_status == ApprovalStatus.APPROVED:
                    # Approved gigs credited points AND advanced the trust
                    # streak — unwinding all of that via a blind PATCH is a
                    # bookkeeping trap. Route parents to the decide flow.
                    raise ValidationException(
                        "This gig was already approved and paid out — it "
                        "cannot be re-opened or cancelled from here."
                    )
                if not template.is_bonus and assignment.approval_status in (
                    ApprovalStatus.NONE, ApprovalStatus.APPROVED
                ):
                    # Mandatory chores credited effective_points at completion
                    # (or approval). Reviving/cancelling must claw those back,
                    # otherwise revive + re-complete double-credits.
                    from app.services.points_service import PointsService
                    await PointsService.award_assignment_completion(
                        db,
                        assignment.assigned_to,
                        assignment.id,
                        -template.effective_points,
                    )
            assignment.status = status
            if status == AssignmentStatus.PENDING:
                assignment.completed_at = None
            if reopening_completed and template is not None and not template.is_bonus:
                # Proof-required chores re-enter the queue on the next
                # completion; clear the stale decision trail. The grade must
                # go too — a leftover 'partial' would silently haircut the
                # payday math (_chore_units) after the redo completes without
                # a fresh review (non-proof chores complete at approval NONE).
                assignment.approval_status = ApprovalStatus.NONE
                assignment.approved_by = None
                assignment.approved_at = None
                assignment.approval_notes = None
                assignment.completion_grade = None
                assignment.partial_credit_pct = None

        await db.commit()
        # Re-fetch with template + user eagerly loaded
        return await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )

    # ─── Daily Progress ──────────────────────────────────────────────

    @staticmethod
    async def get_daily_progress(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        target_date: Optional[date] = None,
    ) -> dict:
        """
        Get daily progress summary for a user.
        Returns required/bonus counts and whether bonus is unlocked.
        "today" is computed in the user's family timezone when target_date is None.
        """
        check_date = target_date or await TaskAssignmentService._user_local_today(db, user_id)

        assignments = await TaskAssignmentService.list_assignments_for_date(
            db, family_id, check_date, user_id
        )

        required_assignments = [a for a in assignments if not a.template.is_bonus]
        bonus_assignments = [a for a in assignments if a.template.is_bonus]

        required_completed = sum(
            1 for a in required_assignments if a.status == AssignmentStatus.COMPLETED
        )
        bonus_completed = sum(
            1 for a in bonus_assignments if a.status == AssignmentStatus.COMPLETED
        )

        # Carry-over: also block bonus when any prior-day mandatory is
        # still PENDING/OVERDUE. Fetch those blockers so the dashboard can
        # render them and name what's blocking bonus, instead of showing the
        # generic "complete all required" message next to "N/N done".
        overdue_assignments = await TaskAssignmentService.list_open_mandatory_before(
            db, user_id, family_id, check_date
        )
        # Same-day open mandatory are already in `assignments`; combined with the
        # prior-day blockers this is the full unlock gate.
        same_day_open = any(
            a.status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)
            for a in required_assignments
        )
        has_open_mandatory = bool(overdue_assignments) or same_day_open
        bonus_unlocked = not has_open_mandatory

        return {
            "date": check_date,
            "required_total": len(required_assignments),
            "required_completed": required_completed,
            "bonus_unlocked": bonus_unlocked,
            "bonus_total": len(bonus_assignments),
            "bonus_completed": bonus_completed,
            "assignments": assignments,
            "overdue_assignments": overdue_assignments,
        }

    # ─── Overdue Check ───────────────────────────────────────────────

    @staticmethod
    async def _family_tz(db: AsyncSession, family_id: UUID):
        """The family's ZoneInfo (fallback UTC)."""
        from zoneinfo import ZoneInfo
        from app.models.family import Family
        family = await db.get(Family, family_id)
        tz_name = (family.timezone if family and family.timezone else None) or "UTC"
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo("UTC")

    @staticmethod
    async def _family_local_today(db: AsyncSession, family_id: UUID) -> date:
        """Today's date in the family's timezone (fallback UTC)."""
        tz = await TaskAssignmentService._family_tz(db, family_id)
        return datetime.now(tz).date()

    @staticmethod
    async def _family_rest_days(db: AsyncSession, family_id: UUID) -> list[int]:
        """Weekdays (0=Mon … 6=Sun) the family assigns no tasks on (rest days)."""
        from app.models.family import Family
        family = await db.get(Family, family_id)
        raw = getattr(family, "rest_days", None) or []
        return [int(x) for x in raw if isinstance(x, int) or str(x).isdigit()]

    @staticmethod
    async def check_overdue_assignments(
        db: AsyncSession, family_id: UUID
    ) -> List[TaskAssignment]:
        """Check for overdue assignments and update their status (family-tz aware)."""
        today = await TaskAssignmentService._family_local_today(db, family_id)

        query = select(TaskAssignment).where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.status == AssignmentStatus.PENDING,
                TaskAssignment.assigned_date < today,
            )
        )

        assignments = list((await db.execute(query)).scalars().all())

        for assignment in assignments:
            assignment.status = AssignmentStatus.OVERDUE

        if assignments:
            await db.commit()

        return assignments

    @staticmethod
    async def mark_overdue_all(db: AsyncSession) -> int:
        """
        Sweep across ALL families: flip PENDING rows with assigned_date < today
        to OVERDUE, where "today" is each family's local date. Intended for the
        background scheduler.

        Batches families by their local "today" date so the number of DB queries
        is O(unique timezones) instead of O(families).

        When a flipped assignment's template has ``auto_late_penalty`` set, a
        Consequence row is instantiated for the assigned user (idempotent
        because status only transitions PENDING → OVERDUE once).
        """
        from zoneinfo import ZoneInfo
        from collections import defaultdict
        from app.models.family import Family
        from app.models.consequence import (
            Consequence,
            ConsequenceSeverity,
            RestrictionType,
        )
        from app.services.notification_service import NotificationService

        # Single query: all family IDs + timezones (no per-family round-trip)
        family_rows = (
            await db.execute(
                select(Family.id, Family.timezone).where(Family.deleted_at.is_(None))
            )
        ).all()

        now_utc = datetime.now(timezone.utc)

        # Group family IDs by their local "today" — computed in Python, no DB
        date_to_families: dict = defaultdict(list)
        for fid, tz_name in family_rows:
            try:
                tz = ZoneInfo(tz_name or "UTC")
            except Exception:
                tz = ZoneInfo("UTC")
            today = datetime.now(tz).date()
            date_to_families[today].append(fid)

        total = 0
        for today, family_ids in date_to_families.items():
            # One query per unique date bucket instead of per family
            stale_q = (
                select(TaskAssignment, User.is_active, User.approval_status)
                .join(User, User.id == TaskAssignment.assigned_to)
                .options(selectinload(TaskAssignment.template))
                .where(
                    and_(
                        TaskAssignment.family_id.in_(family_ids),
                        TaskAssignment.status == AssignmentStatus.PENDING,
                        TaskAssignment.assigned_date < today,
                    )
                )
            )
            stale = (await db.execute(stale_q)).all()
            for a, assignee_active, assignee_approval in stale:
                # The status flip is plain bookkeeping and stays universal
                # (keeps the sweep idempotent and avoids zombie PENDING
                # rows), but the punitive side effects below only apply to
                # participating members: an account that cannot log in —
                # deactivated, or a join-code signup still pending parental
                # approval — must never receive an automatic Consequence or
                # a late-penalty notification.
                a.status = AssignmentStatus.OVERDUE
                a.updated_at = now_utc
                if not (
                    assignee_active and assignee_approval == APPROVAL_APPROVED
                ):
                    continue
                tmpl = a.template
                if tmpl is None or not tmpl.auto_late_penalty:
                    continue
                if not tmpl.late_restriction_type:
                    continue
                try:
                    restriction = RestrictionType(tmpl.late_restriction_type)
                except ValueError:
                    continue
                severity_raw = tmpl.late_severity or "low"
                try:
                    severity = ConsequenceSeverity(severity_raw)
                except ValueError:
                    severity = ConsequenceSeverity.LOW
                duration = max(1, min(30, int(tmpl.late_duration_days or 1)))
                end_dt = now_utc + timedelta(days=duration)
                title = f"Late: {tmpl.title}"[:200]
                penalty = Consequence(
                    title=title,
                    description=(
                        f"Auto-applied because task '{tmpl.title}' "
                        f"({a.assigned_date.isoformat()}) was not completed on time."
                    ),
                    severity=severity,
                    restriction_type=restriction,
                    duration_days=duration,
                    active=True,
                    resolved=False,
                    triggered_by_assignment_id=a.id,
                    applied_to_user=a.assigned_to,
                    family_id=a.family_id,
                    start_date=now_utc,
                    end_date=end_dt,
                )
                db.add(penalty)
                # Human, localized label for the restriction — not the raw enum
                # token ("screen_time") which leaked into the kid-facing body.
                # create_localized_no_commit resolves the kid's preferred_lang
                # (penalties are rare, so the per-assignment user load is fine)
                # and truncates the title to the column width (String(200)) —
                # an overflow would abort the single end-of-sweep commit and
                # roll back every family's flips.
                _RESTRICTION_LABELS = {
                    "screen_time": ("tiempo de pantalla", "screen time"),
                    "rewards": ("recompensas", "rewards"),
                    "extra_tasks": ("tareas extra", "extra tasks"),
                    "allowance": ("mesada", "allowance"),
                    "activities": ("actividades", "activities"),
                    "custom": ("una restricción", "a restriction"),
                }
                _r_es, _r_en = _RESTRICTION_LABELS.get(
                    restriction.value, (restriction.value, restriction.value)
                )
                await NotificationService.create_localized_no_commit(
                    db,
                    family_id=a.family_id,
                    key="late_penalty",
                    user_id=a.assigned_to,
                    params={
                        "title": tmpl.title,
                        "restriction": {"es": _r_es, "en": _r_en},
                        "days": duration,
                    },
                )
            total += len(stale)
        await db.commit()
        return total

    # ─── Interval recurrence ('every N days since last completion') ───

    @staticmethod
    async def spawn_interval_assignments_for_family(
        db: AsyncSession,
        family_id: UUID,
        today: Optional[date] = None,
    ) -> List[TaskAssignment]:
        """Spawn due assignments for recurrence_mode='since_completion'
        templates of one family (W4.2).

        Rules per template:
        - Never spawn while an OPEN row (PENDING/CLAIMED/OVERDUE) exists —
          an overdue interval chore stays on the board until done; no pile-up.
        - Anchor = the later of (last completion date, last spawned
          assigned_date). Next occurrence is due at anchor + N days. The
          assigned_date term prevents a cancel → instant-respawn loop.
        - First spawn (no rows at all) is due immediately.
        - Assignee: FIXED → first of assigned_user_ids; ROTATE → round-robin
          over assigned_user_ids via the persisted rotation_cursor; AUTO →
          round-robin over eligible members (role-filtered, sorted by id)
          via the same persisted cursor. Deterministic, no duplicates.

        Idempotent per day: calling it again spawns nothing new (the spawned
        row is open). Pass ``today`` to pin the date in tests.
        """
        from zoneinfo import ZoneInfo
        from app.models.family import Family

        family = await db.get(Family, family_id)
        if family is None:
            return []
        try:
            tz = ZoneInfo(family.timezone or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        if today is None:
            today = datetime.now(tz).date()

        templates = list((await db.execute(
            select(TaskTemplate).where(
                and_(
                    TaskTemplate.family_id == family_id,
                    TaskTemplate.is_active == True,  # noqa: E712
                    func.coalesce(TaskTemplate.recurrence_mode, "weekly")
                    == "since_completion",
                )
            )
        )).scalars().all())
        if not templates:
            return []

        members = list((await db.execute(
            select(User).where(
                and_(
                    User.family_id == family_id,
                    TaskAssignmentService._participating_member_clause(),
                )
            )
        )).scalars().all())
        if not members:
            return []

        created: list[TaskAssignment] = []
        for tmpl in templates:
            n_days = max(1, int(tmpl.recur_every_n_days or 1))

            # Open row → nothing to do for this template. A proof-required
            # completion still awaiting parent review (status=COMPLETED,
            # approval_status=PENDING) counts as OPEN: if the parent rejects
            # it, the row re-opens (status back to PENDING) — spawning the
            # next occurrence meanwhile would leave two open rows for the
            # same template.
            open_count = (await db.execute(
                select(func.count()).select_from(TaskAssignment).where(
                    and_(
                        TaskAssignment.template_id == tmpl.id,
                        or_(
                            TaskAssignment.status.in_([
                                AssignmentStatus.PENDING,
                                AssignmentStatus.CLAIMED,
                                AssignmentStatus.OVERDUE,
                            ]),
                            and_(
                                TaskAssignment.status
                                == AssignmentStatus.COMPLETED,
                                TaskAssignment.approval_status
                                == ApprovalStatus.PENDING,
                            ),
                        ),
                    )
                )
            )).scalar_one()
            if open_count:
                continue

            last_completed_at = (await db.execute(
                select(func.max(TaskAssignment.completed_at)).where(
                    and_(
                        TaskAssignment.template_id == tmpl.id,
                        TaskAssignment.status == AssignmentStatus.COMPLETED,
                    )
                )
            )).scalar()
            max_assigned = (await db.execute(
                select(func.max(TaskAssignment.assigned_date)).where(
                    TaskAssignment.template_id == tmpl.id
                )
            )).scalar()

            if max_assigned is None:
                due = True  # never spawned — first occurrence is due now
            else:
                anchor = max_assigned
                if last_completed_at is not None:
                    completed_local = (
                        last_completed_at.astimezone(tz).date()
                        if last_completed_at.tzinfo
                        else last_completed_at.date()
                    )
                    anchor = max(anchor, completed_local)
                due = today >= anchor + timedelta(days=n_days)
            if not due:
                continue

            # Resolve the assignee.
            eligible = list(members)
            allowed = tmpl.allowed_roles or None
            if allowed:
                allowed_lower = {r.lower() for r in allowed}
                eligible = [
                    m for m in eligible
                    if (m.role.value if hasattr(m.role, "value") else str(m.role)).lower()
                    in allowed_lower
                ]
            if tmpl.assignment_type in (AssignmentType.FIXED, AssignmentType.ROTATE):
                explicit = TaskAssignmentService._rotation_eligible(tmpl, members)
                if explicit:
                    eligible = explicit
                elif tmpl.assignment_type == AssignmentType.ROTATE:
                    # Null/stale member list → rotate over the role-filtered
                    # pool (same fallback as the weekly shuffle).
                    eligible = sorted(eligible, key=lambda m: str(m.id))
                else:
                    eligible = []  # FIXED without members has no fallback
            else:
                eligible = sorted(eligible, key=lambda m: str(m.id))
            if not eligible:
                continue

            if tmpl.assignment_type == AssignmentType.FIXED:
                chosen = eligible[0]
            else:
                # ROTATE and AUTO both round-robin on the persisted cursor —
                # deterministic and fair across spawns.
                cursor = int(tmpl.rotation_cursor or 0)
                chosen = eligible[cursor % len(eligible)]
                tmpl.rotation_cursor = cursor + 1

            from datetime import time as dt_time
            row = TaskAssignment(
                template_id=tmpl.id,
                assigned_to=chosen.id,
                family_id=family_id,
                status=AssignmentStatus.PENDING,
                assigned_date=today,
                due_date=datetime.combine(
                    today, dt_time(23, 59, 59), tzinfo=tz
                ).astimezone(timezone.utc),
                week_of=TaskAssignmentService._get_monday(today),
            )
            db.add(row)
            created.append(row)

            try:
                from app.services.notification_service import NotificationService
                await NotificationService.create_localized_no_commit(
                    db,
                    family_id=family_id,
                    key="task_assigned_one",
                    user_id=chosen.id,
                    params={"count": 1},
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "interval-spawn notification failed", exc_info=True
                )

        if created:
            await db.commit()
            for row in created:
                await db.refresh(row)
        return created

    @staticmethod
    async def spawn_interval_assignments(db: AsyncSession) -> int:
        """Sweep across ALL families: spawn due 'since_completion'
        assignments (family-local dates). Intended for the hourly background
        loop, right after the overdue sweep."""
        family_ids = [
            fid for (fid,) in (await db.execute(
                select(TaskTemplate.family_id).where(
                    and_(
                        TaskTemplate.is_active == True,  # noqa: E712
                        func.coalesce(TaskTemplate.recurrence_mode, "weekly")
                        == "since_completion",
                    )
                ).distinct()
            )).all()
        ]
        total = 0
        for fid in family_ids:
            try:
                total += len(
                    await TaskAssignmentService.spawn_interval_assignments_for_family(
                        db, fid
                    )
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "interval spawn failed for family %s", fid
                )
        return total

    @staticmethod
    async def send_morning_reminders(db: AsyncSession) -> int:
        """Sweep across ALL families: for every member with >=1 PENDING
        assignment due today (family-local date), send one localized
        'Tienes N tareas hoy' / 'You have N chores today' notification+push.

        Idempotent per local day: a member who already has a TASK_DUE
        notification created since their family's local midnight is skipped,
        so a process restart (or a duplicate scheduler tick) never
        double-sends. Intended for the 07:30 America/Mexico_City cron job.

        Returns the number of reminders sent.
        """
        from zoneinfo import ZoneInfo
        from collections import defaultdict
        from app.models.family import Family
        from app.models.notification import Notification, NotificationType as NT
        from app.services.notification_service import NotificationService
        from datetime import time as dt_time

        family_rows = (
            await db.execute(
                select(Family.id, Family.timezone).where(Family.deleted_at.is_(None))
            )
        ).all()

        # Group families by their local "today" (one query per date bucket).
        date_to_families: dict = defaultdict(list)
        tz_by_family: dict = {}
        for fid, tz_name in family_rows:
            try:
                tz = ZoneInfo(tz_name or "UTC")
            except Exception:
                tz = ZoneInfo("UTC")
            tz_by_family[fid] = tz
            date_to_families[datetime.now(tz).date()].append(fid)

        sent = 0
        for today, family_ids in date_to_families.items():
            rows = (
                await db.execute(
                    select(
                        TaskAssignment.assigned_to,
                        TaskAssignment.family_id,
                        func.count(),
                    )
                    # Only participating members (active + parent-approved)
                    # get reminders — a pending join-code signup cannot log
                    # in, so pushing "you have N chores" at it is noise at
                    # best and a data leak at worst.
                    .join(User, User.id == TaskAssignment.assigned_to)
                    .where(
                        and_(
                            TaskAssignment.family_id.in_(family_ids),
                            TaskAssignment.status == AssignmentStatus.PENDING,
                            TaskAssignment.assigned_date == today,
                            TaskAssignmentService._participating_member_clause(),
                        )
                    )
                    .group_by(TaskAssignment.assigned_to, TaskAssignment.family_id)
                )
            ).all()

            for user_id, fam_id, cnt in rows:
                if not cnt:
                    continue
                # Idempotency guard: already reminded since local midnight?
                local_midnight = datetime.combine(
                    today, dt_time.min, tzinfo=tz_by_family.get(fam_id, timezone.utc)
                )
                already = (
                    await db.execute(
                        select(func.count())
                        .select_from(Notification)
                        .where(
                            and_(
                                Notification.user_id == user_id,
                                Notification.type == NT.TASK_DUE,
                                Notification.created_at >= local_midnight,
                            )
                        )
                    )
                ).scalar()
                if already:
                    continue
                try:
                    key = "task_due_today_one" if cnt == 1 else "task_due_today"
                    await NotificationService.create_localized(
                        db,
                        family_id=fam_id,
                        key=key,
                        user_id=user_id,
                        params={"count": int(cnt)},
                        link="/dashboard",
                    )
                    sent += 1
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception(
                        "morning reminder failed for user %s", user_id
                    )
        return sent
