"""Regression: a FIXED (pinned) template honors its interval_days.

Bug (prod 2026-07-13): a weekly FIXED chore pinned to one member generated a
row for EVERY day of the week (Mon–Sun) instead of one. Root cause was a
`task_dates = week_dates` shortcut for interval_days==7 that the FIXED branch
iterated directly. A parent who set "Barrer el 3er piso" (pinned to himself)
to weekly saw it 7×. The AUTO-weekly slot picker was unaffected (it reads
week_dates directly and picks one), so the fix only had to stop FIXED from
expanding a weekly template into 7 days.
"""

import random
import uuid
from datetime import date

from app.models.task_template import TaskTemplate, AssignmentType
from app.models.user import User, UserRole
from app.services.task_assignment_service import TaskAssignmentService


def _members(family, count: int) -> list[User]:
    out = []
    for i in range(count):
        u = User(
            email=f"u{i}@example.test",
            password_hash="x",
            name=f"User {i}",
            role=UserRole.PARENT,
            family_id=family.id,
            is_active=True,
        )
        u.id = uuid.uuid4()
        out.append(u)
    return out


def _fixed_tmpl(family, assignee, interval_days: int) -> TaskTemplate:
    t = TaskTemplate(
        title="Pinned chore",
        points=10,
        effort_level=1,
        interval_days=interval_days,
        is_bonus=False,
        assignment_type=AssignmentType.FIXED,
        assigned_user_ids=[str(assignee.id)],
        family_id=family.id,
    )
    t.id = uuid.uuid4()
    return t


def _run(family, members, tmpl, week_monday):
    rng = random.Random("seed")
    assignments, _totals, _skipped = TaskAssignmentService._compute_assignments(
        rng,
        family.id,
        week_monday,
        regular_templates=[tmpl],
        bonus_templates=[],
        members=members,
        today=week_monday,  # full week materialized
    )
    return assignments


class TestFixedWeeklyFrequency:
    def test_weekly_fixed_yields_one_row(self, test_family):
        members = _members(test_family, 3)
        tmpl = _fixed_tmpl(test_family, members[0], interval_days=7)
        assignments = _run(test_family, members, tmpl, date(2026, 6, 1))
        # Weekly = once. Regression: was 7 (one per weekday).
        assert len(assignments) == 1
        assert assignments[0].assigned_to == members[0].id

    def test_daily_fixed_still_yields_seven(self, test_family):
        members = _members(test_family, 3)
        tmpl = _fixed_tmpl(test_family, members[0], interval_days=1)
        assignments = _run(test_family, members, tmpl, date(2026, 6, 1))
        # Daily fixed chore legitimately recurs every day.
        assert len(assignments) == 7
        assert all(a.assigned_to == members[0].id for a in assignments)

    def test_every_three_days_fixed_count(self, test_family):
        members = _members(test_family, 3)
        tmpl = _fixed_tmpl(test_family, members[0], interval_days=3)
        assignments = _run(test_family, members, tmpl, date(2026, 6, 1))
        # interval 3 -> 3 occurrences in a 7-day week (Mon/Thu/Sun anchor).
        assert len(assignments) == 3
        assert all(a.assigned_to == members[0].id for a in assignments)


def _run_many(family, members, tmpls, week_monday, rest_days=None):
    rng = random.Random("seed")
    assignments, _t, _s = TaskAssignmentService._compute_assignments(
        rng, family.id, week_monday,
        regular_templates=tmpls, bonus_templates=[], members=members,
        today=week_monday, rest_days=rest_days,
    )
    return assignments


class TestDaySpreadAndRestDays:
    def test_weekly_fixed_chores_spread_across_days(self, test_family):
        # Three weekly chores pinned to ONE member must fan out across three
        # distinct days, not all stack on Monday.
        members = _members(test_family, 3)
        tmpls = [_fixed_tmpl(test_family, members[0], 7) for _ in range(3)]
        assignments = _run_many(test_family, members, tmpls, date(2026, 6, 1))
        assert len(assignments) == 3
        assert all(a.assigned_to == members[0].id for a in assignments)
        assert len({a.assigned_date for a in assignments}) == 3  # distinct days

    def test_rest_day_gets_no_assignments(self, test_family):
        # A daily AUTO chore with Sunday (weekday 6) as a rest day never lands
        # on Sunday -> 6 occurrences Mon–Sat, not 7.
        members = _members(test_family, 3)
        t = TaskTemplate(
            title="Daily sweep", points=10, effort_level=1, interval_days=1,
            is_bonus=False, assignment_type=AssignmentType.AUTO,
            family_id=test_family.id,
        )
        t.id = uuid.uuid4()
        assignments = _run_many(test_family, members, [t], date(2026, 6, 1),
                                rest_days=[6])
        assert len(assignments) == 6
        assert all(a.assigned_date.weekday() != 6 for a in assignments)

    def test_weekly_fixed_avoids_rest_day(self, test_family):
        members = _members(test_family, 3)
        tmpls = [_fixed_tmpl(test_family, members[0], 7) for _ in range(3)]
        assignments = _run_many(test_family, members, tmpls, date(2026, 6, 1),
                                rest_days=[6])
        assert all(a.assigned_date.weekday() != 6 for a in assignments)


def _auto_daily(family, points=10):
    t = TaskTemplate(
        title="Daily", points=points, effort_level=1, interval_days=1,
        is_bonus=False, assignment_type=AssignmentType.AUTO, family_id=family.id,
    )
    t.id = uuid.uuid4()
    return t


class TestMemberBalance:
    def test_daily_auto_balances_members(self, test_family):
        # Several daily AUTO chores must split evenly across members — no member
        # runs away with the load (regression: fixed-order round-robin drifted
        # to 150 vs 70 because its rank tiebreak always favored the same member).
        members = _members(test_family, 4)
        tmpls = [_auto_daily(test_family) for _ in range(4)]
        assignments = _run_many(test_family, members, tmpls, date(2026, 6, 1))
        totals = {m.id: 0 for m in members}
        for a in assignments:
            totals[a.assigned_to] += 10
        spread = max(totals.values()) - min(totals.values())
        # 4 daily chores × 7 days = 28 slots / 4 = 7 each; allow ≤ 1 chore-day gap.
        assert spread <= 10, f"member spread too wide: {sorted(totals.values())}"

    def test_fixed_load_is_compensated(self, test_family):
        # A member pinned to extra FIXED work should NOT also get an equal share
        # of AUTO chores — the balancer gives them fewer so totals converge.
        members = _members(test_family, 4)
        pinned = members[0]
        tmpls = [_fixed_tmpl(test_family, pinned, 7) for _ in range(3)]  # +30 pinned
        tmpls += [_auto_daily(test_family) for _ in range(4)]
        assignments = _run_many(test_family, members, tmpls, date(2026, 6, 1))
        totals = {m.id: 0 for m in members}
        for a in assignments:
            totals[a.assigned_to] += 10
        # Pinned member carries the 3 FIXED but is not the runaway max by a lot.
        spread = max(totals.values()) - min(totals.values())
        assert spread <= 30, f"compensation failed: {sorted(totals.values())}"

    def test_forced_first_keeps_equal_members_balanced(self, test_family):
        # Two equally-eligible members; one is pinned to extra FIXED work. AUTO
        # chores must flow to the OTHER member to compensate so their totals stay
        # close. Regression: a points-desc processing order assigned AUTO chores
        # before the pinned load was credited, so the balancer couldn't offset it
        # and two equally-eligible teens drifted to 180 vs 90 in prod. Processing
        # member-forced chores first fixes this.
        from collections import Counter
        members = _members(test_family, 4)
        t0, t1 = members[0], members[1]
        pinned = TaskTemplate(
            title="Pinned daily", points=10, effort_level=1, interval_days=1,
            is_bonus=False, assignment_type=AssignmentType.FIXED,
            assigned_user_ids=[str(t0.id)], family_id=test_family.id,
        )
        pinned.id = uuid.uuid4()
        autos = [_auto_daily(test_family) for _ in range(4)]
        assignments = _run_many(test_family, members, [pinned] + autos,
                                date(2026, 6, 1), rest_days=[6])
        tot = Counter()
        for a in assignments:
            tot[a.assigned_to] += 10
        gap = abs(tot[t0.id] - tot[t1.id])
        assert gap <= 30, f"forced-first failed to balance: {sorted(tot.values())}"


def _auto_interval(family, interval_days, points=10):
    t = TaskTemplate(
        title=f"Every{interval_days}d", points=points, effort_level=1,
        interval_days=interval_days, is_bonus=False,
        assignment_type=AssignmentType.AUTO, family_id=family.id,
    )
    t.id = uuid.uuid4()
    return t


class TestPerMemberDaySpread:
    def test_member_weekly_chores_fan_across_days(self, test_family):
        # The leveling pass spreads a member's WEEKLY chores across their days —
        # no bunching 4-on-Thursday-nothing-elsewhere (prod: Ariana).
        from collections import Counter
        members = _members(test_family, 4)
        tmpls = [_fixed_tmpl(test_family, members[0], 7) for _ in range(6)]
        assignments = _run_many(test_family, members, tmpls, date(2026, 6, 1),
                                rest_days=[6])
        per_day = Counter(
            a.assigned_date.weekday()
            for a in assignments if a.assigned_to == members[0].id
        )
        counts = [per_day.get(wd, 0) for wd in range(6)]  # Mon–Sat
        assert max(counts) - min(counts) <= 1, f"weekly bunched: {counts}"

    def test_interval_chore_cadence_is_preserved(self, test_family):
        # An every-3-days chore keeps its SPACED schedule — the leveler must NOT
        # scatter it into consecutive days (prod: "cada 3d" was running daily).
        members = _members(test_family, 3)
        mop = _auto_interval(test_family, interval_days=3)
        # weekly chores present so the leveler is actively running
        tmpls = [mop] + [_fixed_tmpl(test_family, members[0], 7) for _ in range(3)]
        assignments = _run_many(test_family, members, tmpls, date(2026, 6, 1))
        mop_dates = sorted(
            a.assigned_date for a in assignments if a.template_id == mop.id
        )
        # _expand_dates(Mon 2026-06-01, interval 3) -> Mon, Thu, Sun
        assert mop_dates == [date(2026, 6, 1), date(2026, 6, 4), date(2026, 6, 7)]

    def test_daily_chore_hits_every_day(self, test_family):
        # A daily chore must occupy every material day exactly once — the leveler
        # must not pull an occurrence off a day and leave a gap.
        members = _members(test_family, 3)
        daily = _auto_daily(test_family)
        tmpls = [daily] + [_fixed_tmpl(test_family, members[0], 7) for _ in range(2)]
        assignments = _run_many(test_family, members, tmpls, date(2026, 6, 1),
                                rest_days=[6])
        daily_days = sorted(
            a.assigned_date.weekday()
            for a in assignments if a.template_id == daily.id
        )
        assert daily_days == [0, 1, 2, 3, 4, 5]  # Mon–Sat, one each, no gaps
