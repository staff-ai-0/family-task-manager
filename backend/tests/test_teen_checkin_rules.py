"""Jarvis teen check-in — pure rules."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.task_assignment import ApprovalStatus as AP, AssignmentStatus as ST
from app.services.teen_checkin_service import (
    CANDIDATE_DAYS, MAX_PER_WEEK, NOTE_MAX, NOTE_REASONS, PAUSE_DAYS, REASONS, Candidate,
    may_offer, normalize_note, pick_candidate, trigger_for,
)

TODAY = datetime.now(timezone.utc).date()
# A Wednesday near today: never a week edge, never a hard-coded date.
WED = TODAY + timedelta(days=(2 - TODAY.weekday()) % 7)


def cand(trigger, days_ago, title="x"):
    return Candidate(uuid4(), TODAY - timedelta(days=days_ago), trigger, title, None, 10)


def test_constants():
    assert REASONS == ("too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other")
    assert NOTE_REASONS == {"app_problem", "other"}
    assert (NOTE_MAX, CANDIDATE_DAYS, MAX_PER_WEEK, PAUSE_DAYS) == (200, 14, 3, 7)


class TestTrigger:
    def test_sent_back_is_a_reopened_rejected_chore_any_day(self):
        assert trigger_for(ST.PENDING, AP.REJECTED, TODAY, TODAY) == "sent_back"
        assert trigger_for(ST.PENDING, AP.REJECTED, TODAY - timedelta(days=3), TODAY) == "sent_back"

    def test_sent_back_survives_the_overdue_sweep(self):
        # The hourly sweep flips a re-opened chore dated before today to
        # OVERDUE and leaves approval_status alone: still "sent back".
        assert trigger_for(ST.OVERDUE, AP.REJECTED, TODAY - timedelta(days=1), TODAY) == "sent_back"

    def test_late_is_open_and_dated_before_today(self):
        assert trigger_for(ST.OVERDUE, AP.NONE, TODAY - timedelta(days=1), TODAY) == "late"
        assert trigger_for(ST.PENDING, AP.NONE, TODAY - timedelta(days=1), TODAY) == "late"

    def test_todays_open_chore_and_finished_chores_are_neither(self):
        assert trigger_for(ST.PENDING, AP.NONE, TODAY, TODAY) is None
        assert trigger_for(ST.COMPLETED, AP.NONE, TODAY - timedelta(days=1), TODAY) is None
        assert trigger_for(ST.COMPLETED, AP.REJECTED, TODAY, TODAY) is None
        assert trigger_for(ST.CANCELLED, AP.NONE, TODAY - timedelta(days=1), TODAY) is None


class TestPickCandidate:
    def test_nothing_to_offer(self):
        assert pick_candidate([]) is None

    def test_sent_back_wins_over_late(self):
        late, sent = cand("late", 1), cand("sent_back", 5)
        assert pick_candidate([late, sent]) is sent

    def test_the_most_recent_one_wins_within_a_kind(self):
        old, new = cand("late", 6), cand("late", 2)
        assert pick_candidate([old, new]) is new
        a, b = cand("sent_back", 4), cand("sent_back", 0)
        assert pick_candidate([a, b, cand("late", 1)]) is b

    def test_ties_are_broken_the_same_way_every_time(self):
        a, b = cand("late", 2), cand("late", 2)
        assert pick_candidate([a, b]) is pick_candidate([b, a])


class TestMayOffer:
    def test_a_fresh_teen_may_be_offered(self):
        assert may_offer(WED, []) is True

    def test_one_a_day(self):
        assert may_offer(WED, [(WED, "answered")]) is False

    def test_three_a_week(self):
        monday = WED - timedelta(days=2)
        two = [(monday, "answered"), (monday + timedelta(days=1), "answered")]
        assert may_offer(WED + timedelta(days=1), two) is True
        three = two + [(WED, "answered")]
        assert may_offer(WED + timedelta(days=1), three) is False
        # A new week starts clean.
        assert may_offer(monday + timedelta(days=7), three) is True

    def test_last_weeks_answers_do_not_count_toward_this_week(self):
        last_week = [(WED - timedelta(days=7 + i), "answered") for i in range(3)]
        assert may_offer(WED, last_week) is True

    def test_not_now_pauses_a_week(self):
        said_no = WED - timedelta(days=10)
        for gap in range(PAUSE_DAYS):
            assert may_offer(said_no + timedelta(days=gap), [(said_no, "dismissed")]) is False
        assert may_offer(said_no + timedelta(days=PAUSE_DAYS), [(said_no, "dismissed")]) is True

    def test_an_answer_does_not_pause(self):
        assert may_offer(WED, [(WED - timedelta(days=1), "answered")]) is True


class TestNote:
    def test_blank_becomes_none(self):
        assert normalize_note("other", None) is None
        assert normalize_note("other", "   \n ") is None
        assert normalize_note("too_hard", "  ") is None

    def test_trimmed_for_the_two_open_reasons(self):
        assert normalize_note("app_problem", "  the photo button does nothing ") == "the photo button does nothing"
        assert normalize_note("other", "x" * NOTE_MAX) == "x" * NOTE_MAX

    @pytest.mark.parametrize("reason", ["too_hard", "not_clear", "no_time", "not_fair", "forgot", None])
    def test_refused_for_every_other_reason(self, reason):
        with pytest.raises(ValueError):
            normalize_note(reason, "my brother never does his")

    def test_control_characters_and_line_breaks_are_cleaned(self):
        assert normalize_note("other", "no\x00 abre\x07") == "no abre"
        assert normalize_note("app_problem", "line one\n\tline two") == "line one line two"
        assert normalize_note("other", "\x00\x01") is None

    def test_refused_when_too_long(self):
        with pytest.raises(ValueError):
            normalize_note("other", "x" * (NOTE_MAX + 1))
