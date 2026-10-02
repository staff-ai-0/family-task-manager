"""UX-D4a pure rules: window, streak wording, quest step, priority, copy."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.notification import NotificationType as NT
from app.models.task_assignment import ApprovalStatus as AP, AssignmentStatus as ST
from app.services.notification_service import SUPERSEDING_TYPES, NotificationService
from app.services.ping_service import (
    PING_TYPES, in_ping_window, pick_ping, quest_can_do_today, quest_ping, streak_ping, today_facts,
)
from app.services.quest_service import ChoreRow

UTC = ZoneInfo("UTC")
TODAY = datetime.now(UTC).date()


def row(status=ST.PENDING, *, bonus=False, grade=None, approval=AP.NONE, day=None):
    return ChoreRow(day or TODAY, status, None, grade, approval, bonus)


class TestWindow:
    @pytest.mark.parametrize("hour,minute,expected", [
        (17, 59, False), (18, 0, True), (19, 30, True), (20, 59, True), (21, 0, False), (0, 0, False),
    ])
    def test_edges(self, hour, minute, expected):
        assert in_ping_window(datetime.combine(TODAY, time(hour, minute), tzinfo=UTC)) is expected


class TestTodayFacts:
    def test_counts_open_mandatory_only(self):
        rows = [row(), row(ST.OVERDUE), row(ST.COMPLETED), row(ST.CANCELLED), row(bonus=True)]
        assert today_facts(rows) == (2, False)

    def test_a_missed_or_rejected_chore_loses_the_day(self):
        assert today_facts([row(), row(ST.COMPLETED, grade="missed")]) == (1, True)
        assert today_facts([row(), row(ST.COMPLETED, approval=AP.REJECTED)]) == (1, True)

    def test_a_rejected_chore_reopened_for_a_redo_loses_the_day(self):
        # What production writes on a rejection: back to PENDING, still marked.
        reopened = row(ST.PENDING, grade="missed", approval=AP.REJECTED)
        assert today_facts([row(), reopened]) == (2, True)

    def test_a_missed_bonus_or_a_cancelled_chore_does_not(self):
        rows = [row(), row(ST.COMPLETED, bonus=True, grade="missed"), row(ST.CANCELLED, grade="missed")]
        assert today_facts(rows) == (1, False)


class TestStreakPing:
    def test_needs_three_days(self):
        assert streak_ping(2, False, 1, False) is None
        assert streak_ping(3, False, 1, False) == "streak_at_risk_pass_one"

    def test_wording_follows_the_free_pass_and_the_count(self):
        assert streak_ping(5, True, 1, False) == "streak_at_risk_last_one"
        assert streak_ping(5, True, 3, False) == "streak_at_risk_last"
        assert streak_ping(5, False, 1, False) == "streak_at_risk_pass_one"
        assert streak_ping(5, False, 2, False) == "streak_at_risk_pass"

    def test_nothing_left_to_do_or_day_lost_sends_nothing(self):
        assert streak_ping(9, True, 0, False) is None
        assert streak_ping(9, True, 2, True) is None


class TestQuestCanDoToday:
    def test_on_time_needs_a_pending_chore(self):
        assert quest_can_do_today("on_time", [row()], TODAY, UTC, 0) is True
        assert quest_can_do_today("on_time", [row(ST.OVERDUE)], TODAY, UTC, 0) is False
        assert quest_can_do_today("on_time", [row(ST.COMPLETED, approval=AP.PENDING)], TODAY, UTC, 0) is False
        assert quest_can_do_today("on_time", [row(bonus=True)], TODAY, UTC, 0) is False

    def test_a_rejected_chore_reopened_for_a_redo_is_not_a_step(self):
        # The redo keeps its "missed" mark, so the quest will not count it:
        # a nudge that points at it would promise a step that does not exist.
        reopened = row(ST.PENDING, grade="missed", approval=AP.REJECTED)
        assert quest_can_do_today("on_time", [reopened], TODAY, UTC, 0) is False
        assert quest_can_do_today("on_time", [reopened, row()], TODAY, UTC, 0) is True
        assert quest_can_do_today("perfect_days", [reopened, row()], TODAY, UTC, 0) is False
        bonus = row(ST.PENDING, bonus=True, grade="missed", approval=AP.REJECTED)
        assert quest_can_do_today("extra_mile", [bonus], TODAY, UTC, 0) is False

    def test_perfect_days_also_needs_no_failed_chore_today(self):
        assert quest_can_do_today("perfect_days", [row(), row(ST.COMPLETED)], TODAY, UTC, 0) is True
        assert quest_can_do_today("perfect_days", [row(), row(ST.COMPLETED, grade="missed")], TODAY, UTC, 0) is False
        assert quest_can_do_today("perfect_days", [row(), row(ST.CANCELLED)], TODAY, UTC, 0) is True

    def test_extra_mile_needs_an_open_bonus_task(self):
        assert quest_can_do_today("extra_mile", [row(bonus=True)], TODAY, UTC, 0) is True
        assert quest_can_do_today("extra_mile", [row(ST.CLAIMED, bonus=True)], TODAY, UTC, 0) is True
        assert quest_can_do_today("extra_mile", [row(ST.COMPLETED, bonus=True, approval=AP.PENDING)], TODAY, UTC, 0) is False
        assert quest_can_do_today("extra_mile", [row()], TODAY, UTC, 0) is False

    def test_go_getter_needs_an_open_gig(self):
        assert quest_can_do_today("go_getter", [], TODAY, UTC, 0) is False
        assert quest_can_do_today("go_getter", [], TODAY, UTC, 2) is True

    def test_unknown_quest_is_never_doable(self):
        assert quest_can_do_today("mystery", [row()], TODAY, UTC, 5) is False


class TestQuestPing:
    def test_only_exactly_one_away(self):
        assert quest_ping(1, 3, False, True, False) is False
        assert quest_ping(2, 3, False, True, False) is True
        assert quest_ping(3, 3, False, True, False) is False

    def test_blockers(self):
        assert quest_ping(2, 3, True, True, False) is False     # already paid
        assert quest_ping(2, 3, False, False, False) is False   # cannot be done today
        assert quest_ping(2, 3, False, True, True) is False     # already nudged this week


class TestPriority:
    def test_streak_wins_then_quest_then_nothing(self):
        assert pick_ping("streak_at_risk_last", True) == "streak_at_risk_last"
        assert pick_ping(None, True) == "quest_nudge"
        assert pick_ping(None, False) is None


class TestTypesAndCopy:
    def test_both_types_supersede(self):
        assert set(PING_TYPES) == {NT.STREAK_AT_RISK, NT.QUEST_NUDGE}
        assert NT.STREAK_AT_RISK == "streak_at_risk" and NT.QUEST_NUDGE == "quest_nudge"
        assert set(PING_TYPES) <= SUPERSEDING_TYPES

    @pytest.mark.parametrize("key,type_", [
        ("streak_at_risk_last", "streak_at_risk"), ("streak_at_risk_last_one", "streak_at_risk"),
        ("streak_at_risk_pass", "streak_at_risk"), ("streak_at_risk_pass_one", "streak_at_risk"),
        ("quest_nudge", "quest_nudge"),
    ])
    def test_copy_keys_map_to_their_type(self, key, type_):
        assert NotificationService.copy_type(key) == type_

    def test_streak_copy(self):
        p = {"days": 5, "n": 3}
        assert NotificationService.render("streak_at_risk_last", "en", p) == (
            "🔥 Your 5-day streak ends tonight", "3 chores left today. Finish them to keep it.")
        assert NotificationService.render("streak_at_risk_last_one", "es", p) == (
            "🔥 Tu racha de 5 días termina esta noche", "Te falta 1 tarea hoy. Termínala para conservarla.")
        assert NotificationService.render("streak_at_risk_pass", "es", p) == (
            "🔥 Conserva tu racha de 5 días", "Te faltan 3 tareas hoy. Termínalas y guarda tu pase libre 🛡️.")
        assert NotificationService.render("streak_at_risk_pass_one", "en", p) == (
            "🔥 Keep your 5-day streak", "1 chore left today. Finish it and save your free pass 🛡️.")
        assert NotificationService.render("streak_at_risk_last", "es", p)[1] == (
            "Te faltan 3 tareas hoy. Termínalas para conservarla.")
        assert NotificationService.render("streak_at_risk_last_one", "en", p)[1] == (
            "1 chore left today. Finish it to keep it.")
        assert NotificationService.render("streak_at_risk_pass", "en", p)[1] == (
            "3 chores left today. Finish them and save your free pass 🛡️.")
        assert NotificationService.render("streak_at_risk_pass_one", "es", p)[1] == (
            "Te falta 1 tarea hoy. Termínala y guarda tu pase libre 🛡️.")

    def test_quest_copy(self):
        assert NotificationService.render("quest_nudge", "en", {"bonus": 20}) == (
            "🏁 1 away from this week's quest", "Finish it for +20 points.")
        assert NotificationService.render("quest_nudge", "es", {"bonus": 20}) == (
            "🏁 Te falta 1 para tu misión de la semana", "Complétala y gana +20 puntos.")
