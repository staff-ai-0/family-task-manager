"""UX-D3 pure weekly-quest rules (no DB)."""
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from app.models.task_assignment import ApprovalStatus as A, AssignmentStatus as S
from app.services.quest_service import (
    OPEN_ENDED_CAP,
    QUESTS,
    ChoreRow,
    WeekStats,
    bonus_state,
    chore_state,
    pick_quest,
    rotation,
    size_target,
    week_monday,
    week_stats,
)

UTC = ZoneInfo("UTC")
MON = date(2026, 9, 28)          # a Monday
WED = MON + timedelta(days=2)
SUN = MON + timedelta(days=6)


def row(day, *, status=S.COMPLETED, approval=A.NONE, grade=None, completed_at=None, bonus=False):
    return ChoreRow(assigned_date=day, status=status, completed_at=completed_at, grade=grade,
                    approval=approval, is_bonus=bonus)


def at(day, hour=12):
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


class TestCatalogAndRotation:
    def test_catalog_is_the_spec_order_and_defaults(self):
        assert list(QUESTS.items()) == [("on_time", 3), ("extra_mile", 1), ("perfect_days", 2), ("go_getter", 1)]

    def test_week_monday(self):
        assert week_monday(WED) == MON and week_monday(MON) == MON and week_monday(SUN) == MON

    def test_rotation_is_a_cycle_of_the_four_keys(self):
        order = rotation(MON, UUID(int=0))
        assert sorted(order) == sorted(QUESTS) and len(order) == 4
        keys = list(QUESTS)
        start = keys.index(order[0])
        assert order == keys[start:] + keys[:start]

    def test_a_kid_moves_one_step_each_week(self):
        kid = UUID(int=7)
        assert rotation(MON + timedelta(days=7), kid)[0] == rotation(MON, kid)[1]

    def test_siblings_start_at_different_points(self):
        assert rotation(MON, UUID(int=0))[0] != rotation(MON, UUID(int=1))[0]


class TestSizeTarget:
    def test_no_history_gives_the_default(self):
        assert size_target(3, 0, 0, 10) == 3

    def test_stretches_ten_percent_above_the_four_week_average_rounded_up(self):
        assert size_target(3, 40, 0, 20) == 11      # avg 10 -> 11 exactly (no float creep to 12)
        assert size_target(3, 41, 0, 20) == 12      # avg 10.25 -> 11.275 -> 12

    def test_never_below_the_default(self):
        assert size_target(3, 4, 0, 10) == 3        # avg 1 -> 1.1 -> 2, default wins

    def test_capped_by_what_is_still_possible(self):
        assert size_target(3, 0, 1, 1) == 2

    def test_not_achievable_when_nothing_is_left(self):
        assert size_target(3, 0, 2, 0) is None

    def test_a_quest_never_starts_finished(self):
        assert size_target(3, 0, 5, 4) is None      # already past the stretch goal

    def test_not_offered(self):
        assert size_target(3, 0, 0, None) is None


class TestChoreState:
    def test_completed_on_time_without_review_counts(self):
        assert chore_state(row(WED), WED, UTC) == "yes"
        assert chore_state(row(WED, completed_at=at(WED, 23)), WED, UTC) == "yes"

    def test_approved_counts(self):
        assert chore_state(row(WED, approval=A.APPROVED), WED, UTC) == "yes"

    def test_awaiting_review_can_still_count(self):
        assert chore_state(row(WED, approval=A.PENDING), WED, UTC) == "maybe"

    def test_rejected_missed_or_late_never_counts(self):
        assert chore_state(row(WED, approval=A.REJECTED), WED, UTC) == "no"
        assert chore_state(row(WED, grade="missed"), WED, UTC) == "no"
        assert chore_state(row(MON, completed_at=at(WED)), WED, UTC) == "no"

    def test_family_timezone_decides_the_day(self):
        mx = ZoneInfo("America/Mexico_City")
        late_evening_local = datetime(2026, 9, 29, 4, 30, tzinfo=timezone.utc)   # Mon 22:30 in Mexico City
        assert chore_state(row(MON, completed_at=late_evening_local), WED, mx) == "yes"
        assert chore_state(row(MON, completed_at=late_evening_local), WED, UTC) == "no"

    def test_open_chore_today_or_later_can_still_count(self):
        assert chore_state(row(WED, status=S.PENDING), WED, UTC) == "maybe"
        assert chore_state(row(SUN, status=S.PENDING), WED, UTC) == "maybe"

    def test_open_chore_from_an_earlier_day_cannot(self):
        assert chore_state(row(MON, status=S.PENDING), WED, UTC) == "no"
        assert chore_state(row(MON, status=S.OVERDUE), WED, UTC) == "no"


class TestBonusState:
    """Bonus tasks are finite dated rows: like chores, minus the on-time rule."""

    def b(self, day, **kw):
        return row(day, bonus=True, **kw)

    def test_completed_without_review_or_approved_counts(self):
        assert bonus_state(self.b(WED), WED) == "yes"
        assert bonus_state(self.b(WED, approval=A.APPROVED), WED) == "yes"

    def test_awaiting_review_can_still_count(self):
        assert bonus_state(self.b(WED, approval=A.PENDING), WED) == "maybe"

    def test_rejected_or_graded_missed_never_counts(self):
        assert bonus_state(self.b(WED, approval=A.REJECTED), WED) == "no"
        assert bonus_state(self.b(WED, grade="missed"), WED) == "no"

    def test_open_today_or_later_can_still_count(self):
        assert bonus_state(self.b(WED, status=S.PENDING), WED) == "maybe"
        assert bonus_state(self.b(WED, status=S.CLAIMED), WED) == "maybe"
        assert bonus_state(self.b(WED + timedelta(days=1), status=S.PENDING), WED) == "maybe"

    def test_open_from_an_earlier_day_or_overdue_cannot(self):
        yesterday = WED - timedelta(days=1)
        assert bonus_state(self.b(yesterday, status=S.PENDING), WED) == "no"
        assert bonus_state(self.b(yesterday, status=S.CLAIMED), WED) == "no"
        assert bonus_state(self.b(MON, status=S.OVERDUE), WED) == "no"
        assert bonus_state(self.b(WED, status=S.OVERDUE), WED) == "no"

    def test_a_bonus_finished_late_still_counts(self):
        assert bonus_state(self.b(MON, completed_at=at(WED)), WED) == "yes"


class TestWeekStats:
    def test_counts_each_type(self):
        rows = [
            row(MON), row(MON),                                   # Monday: perfect
            row(MON + timedelta(days=1)), row(MON + timedelta(days=1), status=S.OVERDUE),   # Tuesday: failed
            row(WED, status=S.PENDING), row(WED, approval=A.PENDING),                         # Wednesday: open
            row(SUN, status=S.PENDING),                           # Sunday: open
            row(WED, status=S.CANCELLED),                         # waived: not a due chore
            row(WED, bonus=True, approval=A.APPROVED),            # bonus done
            row(WED, bonus=True, approval=A.PENDING),             # bonus awaiting review
        ]
        s = week_stats(rows, 2, WED, UTC)
        assert s.done == {"on_time": 3, "perfect_days": 1, "extra_mile": 1, "go_getter": 2}
        assert s.possible["on_time"] == 3          # Wed pending + Wed awaiting review + Sun pending
        assert s.possible["perfect_days"] == 2     # Wednesday and Sunday can still become perfect
        assert s.possible["extra_mile"] == 1       # the bonus task awaiting review

    def test_open_bonus_tasks_are_what_extra_mile_can_still_reach(self):
        rows = [
            row(WED, bonus=True, status=S.PENDING), row(WED, bonus=True, status=S.CLAIMED),   # open today
            row(MON, bonus=True, status=S.OVERDUE),                                           # gone
            row(WED, bonus=True, status=S.CANCELLED),                                         # waived
        ]
        s = week_stats(rows, 0, WED, UTC)
        assert s.done["extra_mile"] == 0 and s.possible["extra_mile"] == 2

    def test_a_day_with_nothing_due_is_neither_perfect_nor_open(self):
        s = week_stats([], 0, WED, UTC)
        assert s.done == {"on_time": 0, "perfect_days": 0, "extra_mile": 0, "go_getter": 0}
        assert s.possible["on_time"] == 0 and s.possible["perfect_days"] == 0

    def test_on_sunday_only_today_is_still_possible(self):
        rows = [row(MON, status=S.OVERDUE), row(SUN, status=S.PENDING)]
        s = week_stats(rows, 0, SUN, UTC)
        assert s.possible["on_time"] == 1 and s.possible["perfect_days"] == 1


class TestPickQuest:
    ORDER = ["on_time", "extra_mile", "perfect_days", "go_getter"]
    ALL = {"on_time": True, "extra_mile": True, "perfect_days": True, "go_getter": True}

    def stats(self, done=None, possible=None):
        zero = dict.fromkeys(QUESTS, 0)
        return WeekStats(done={**zero, **(done or {})}, possible={**zero, **(possible or {})})

    def test_first_achievable_type_in_order_wins(self):
        assert pick_quest(self.ORDER, self.stats(possible={"on_time": 6}), {}, self.ALL) == ("on_time", 3)

    def test_skips_a_type_that_cannot_be_achieved(self):
        # no chores left -> on_time impossible -> extra_mile (open-ended, default 1)
        assert pick_quest(self.ORDER, self.stats(), {}, self.ALL) == ("extra_mile", 1)

    def test_skips_a_type_that_is_not_offered(self):
        offered = {**self.ALL, "extra_mile": False, "go_getter": False}
        got = pick_quest(self.ORDER, self.stats(possible={"perfect_days": 4}), {}, offered)
        assert got == ("perfect_days", 2)

    def test_none_when_nothing_qualifies(self):
        offered = {"on_time": True, "perfect_days": True, "extra_mile": False, "go_getter": False}
        assert pick_quest(self.ORDER, self.stats(), {}, offered) is None

    def test_open_ended_goal_uses_history_and_is_capped(self):
        offered = {**self.ALL, "on_time": False}
        order = ["extra_mile", "on_time", "perfect_days", "go_getter"]
        assert pick_quest(order, self.stats(), {"extra_mile": 400}, offered) == ("extra_mile", OPEN_ENDED_CAP)
        # already at the cap -> nothing more to ask for -> the next offered type is used
        assert pick_quest(order, self.stats(done={"extra_mile": 7}), {}, offered) == ("go_getter", 1)

    def test_a_type_already_past_its_goal_is_skipped(self):
        # 2 gigs already approved, default goal 1 -> the goal is already met -> not this week's quest
        order = ["go_getter", "on_time", "extra_mile", "perfect_days"]
        assert pick_quest(order, self.stats(done={"go_getter": 2}), {}, self.ALL) == ("extra_mile", 1)
