"""UX-E1 chore-chart scanner: pure helpers and the (mocked) vision call."""
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.services.chart_scanner_service import (
    MAX_PROPOSALS, Member, build_prompt, clamp_points, fold, match_members, normalize_days, parse_chart,
    scan_chore_chart,
)

DIEGO, SOFIA, MARIANA = uuid4(), uuid4(), uuid4()
MEMBERS = [Member(DIEGO, "Diego Martínez", "teen"), Member(SOFIA, "Sofía Martínez", "child"), Member(MARIANA, "Mariana", "parent")]


def _mock_completion(text):
    msg = MagicMock(); msg.content = text
    choice = MagicMock(); choice.message = msg
    completion = MagicMock(); completion.choices = [choice]
    return completion


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
    monkeypatch.setattr(config.settings, "LITELLM_API_BASE", "https://litellm.test")


class TestFold:
    def test_case_accents_and_spaces(self):
        assert fold("  Sofía   MARTÍNEZ ") == "sofia martinez"
        assert fold("Ñoño") == "nono"
        assert fold("") == ""


class TestMatch:
    def test_first_name_or_full_name_any_case_or_accent(self):
        ids, missing = match_members(["diego", "SOFIA MARTINEZ", "Mariana"], MEMBERS)
        assert ids == [DIEGO, SOFIA, MARIANA] and missing == []

    def test_unknown_names_are_reported_not_guessed(self):
        ids, missing = match_members(["Pepe", "Diego"], MEMBERS)
        assert ids == [DIEGO] and missing == ["Pepe"]

    def test_an_ambiguous_first_name_is_unmatched(self):
        twins = MEMBERS + [Member(uuid4(), "Diego López", "child")]
        ids, missing = match_members(["Diego"], twins)
        assert ids == [] and missing == ["Diego"]
        ids, missing = match_members(["Diego López"], twins)
        assert len(ids) == 1 and missing == []

    def test_blank_and_duplicate_names(self):
        ids, missing = match_members(["", "  ", "Diego", "diego"], MEMBERS)
        assert ids == [DIEGO] and missing == []


class TestDays:
    def test_numbers_words_and_ranges(self):
        assert normalize_days([4, 0, 2, 2]) == [0, 2, 4]
        assert normalize_days(["mon", "Wednesday", "fri"]) == [0, 2, 4]
        assert normalize_days(["weekends"]) == [5, 6]
        assert normalize_days(["weekdays"]) == [0, 1, 2, 3, 4]
        assert normalize_days(["sábado", "domingo"]) == [5, 6]

    def test_garbage_is_dropped(self):
        assert normalize_days([7, -1, "nope", None, 3.0]) == [3]
        assert normalize_days(None) == []
        assert normalize_days("daily") == []


class TestPoints:
    @pytest.mark.parametrize("raw,expected", [(10, 10), ("25", 25), (-5, 0), (5000, 1000), (None, 10), ("x", 10), (7.9, 7)])
    def test_clamped_with_a_default(self, raw, expected):
        assert clamp_points(raw) == expected


class TestPrompt:
    def test_names_roles_and_language_are_in_the_prompt(self):
        p = build_prompt(MEMBERS, "es")
        for s in ("Diego Martínez (teen)", "Sofía Martínez (child)", "Mariana (parent)", "Spanish", '"chores"', "weekdays"):
            assert s in p
        assert "English" in build_prompt(MEMBERS, "en")


class TestParse:
    def test_a_chart_becomes_proposals(self):
        existing = {fold("Feed the dog"): uuid4()}
        raw = json.dumps({"doc_type": "chore_chart", "confidence": 0.9, "chores": [
            {"title": " Feed the dog ", "points": 15, "is_bonus": False, "days": ["mon", "wed"], "assignees": ["Diego"], "notes": "evenings"},
            {"title": "Wash car", "points": 500000, "is_bonus": True, "days": [], "assignees": ["Pepe", "sofia"]},
            {"title": "", "points": 5},
            {"points": 5},
        ]})
        out = parse_chart(raw, MEMBERS, existing)
        assert (out.doc_type, out.confidence) == ("chore_chart", 0.9)
        assert len(out.chores) == 2
        a, b = out.chores
        assert (a.title, a.points, a.is_bonus, a.days_of_week, a.assignee_names, a.assigned_user_ids, a.unmatched_names) == (
            "Feed the dog", 15, False, [0, 2], ["Diego"], [DIEGO], [])
        assert a.duplicate_of == existing[fold("Feed the dog")] and a.description == "evenings"
        assert (b.title, b.points, b.is_bonus, b.days_of_week, b.assigned_user_ids, b.unmatched_names, b.duplicate_of, b.description) == (
            "Wash car", 1000, True, [], [SOFIA], ["Pepe"], None, None)

    def test_json_inside_prose_and_a_cap_of_forty(self):
        rows = [{"title": f"Chore {i}", "points": 10} for i in range(60)]
        raw = "Sure! Here is the JSON:\n" + json.dumps({"doc_type": "list", "confidence": 0.5, "chores": rows}) + "\nHope this helps."
        out = parse_chart(raw, MEMBERS, {})
        assert len(out.chores) == MAX_PROPOSALS == 40 and out.chores[0].title == "Chore 0"

    def test_garbage_never_crashes(self):
        for raw in ("", "no json here", "{]", json.dumps({"chores": "nope"}), json.dumps({"chores": [None, 3, "x"]})):
            if raw in ("", "no json here", "{]"):
                with pytest.raises(ValidationError):
                    parse_chart(raw, MEMBERS, {})
            else:
                assert parse_chart(raw, MEMBERS, {}).chores == []

    def test_is_bonus_must_be_a_real_true(self):
        raw = json.dumps({"chores": [{"title": "a", "is_bonus": "false"}, {"title": "b", "is_bonus": 1}, {"title": "c", "is_bonus": True}]})
        assert [c.is_bonus for c in parse_chart(raw, MEMBERS, {}).chores] == [False, False, True]

    def test_assignee_names_are_bounded_in_length_and_count(self):
        raw = json.dumps({"chores": [{"title": "a", "assignees": ["x" * 300] + [f"n{i}" for i in range(30)]}]})
        c = parse_chart(raw, MEMBERS, {}).chores[0]
        assert len(c.assignee_names) == 10 and len(c.unmatched_names) == 10 and all(len(n) <= 60 for n in c.assignee_names)

    def test_titles_are_bounded_and_description_too(self):
        raw = json.dumps({"chores": [{"title": "x" * 300, "notes": "y" * 2000, "days": "weekdays"}]})
        c = parse_chart(raw, MEMBERS, {}).chores[0]
        assert len(c.title) == 200 and len(c.description) == 1000 and c.days_of_week == [0, 1, 2, 3, 4] and c.points == 10


class TestScan:
    async def test_calls_the_vision_model_with_the_image_and_the_family(self):
        payload = json.dumps({"doc_type": "chore_chart", "confidence": 0.8, "chores": [{"title": "Make bed", "assignees": ["Sofía"]}]})
        with patch("app.core.llm.OpenAI") as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = _mock_completion(payload)
            mock_openai.return_value = client
            out = await scan_chore_chart(b"\x89PNG...", "image/png", MEMBERS, {}, "es")
        assert out.chores[0].assigned_user_ids == [SOFIA]
        kwargs = client.chat.completions.create.call_args.kwargs
        content = kwargs["messages"][0]["content"]
        assert content[0]["type"] == "image_url" and content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "Sofía Martínez (child)" in content[1]["text"] and "Spanish" in content[1]["text"]

    async def test_model_failure_is_a_validation_error_not_a_crash(self):
        with patch("app.core.llm.OpenAI") as mock_openai:
            client = MagicMock()
            client.chat.completions.create.side_effect = RuntimeError("upstream down")
            mock_openai.return_value = client
            with pytest.raises(ValidationError):
                await scan_chore_chart(b"img", "image/jpeg", MEMBERS, {}, "en")

    async def test_no_api_key_raises(self, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "")
        with pytest.raises(ValidationError):
            await scan_chore_chart(b"img", "image/jpeg", MEMBERS, {}, "en")


def test_scan_constants_live_in_upload_validation():
    from app.core.upload_validation import ALLOWED_SCAN_TYPES, MAX_SCAN_BYTES
    from app.api.routes import calendar
    assert calendar.ALLOWED_SCAN_TYPES is ALLOWED_SCAN_TYPES and calendar.MAX_SCAN_BYTES == MAX_SCAN_BYTES == 8 * 1024 * 1024
    assert {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"} == ALLOWED_SCAN_TYPES
