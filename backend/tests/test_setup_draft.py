"""UX-E3 guided setup: schemas and the pure draft functions (pack path, parser)."""
import json
from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticError

from app.schemas.setup_draft import KidAnswer, SetupDraftRequest
from app.services.setup_draft_service import (
    CHORES_PER_KID_MAX, GIGS_MAX, PACK_CHORES_PER_KID, PACK_GIGS, PACK_REWARDS, REWARDS_MAX,
    DraftParseError, band_for_birthdate, build_prompt, mark_duplicates, pack_draft, parse_draft,
)


def _req(**over):
    base = dict(
        kids=[{"name": "Sofía", "age_band": "6-8"}, {"name": "Diego", "age_band": "13+"}],
        priorities=["school", "pets"], note=None, reward_styles=["screen_time"], wants_gigs=True, lang="en",
    )
    base.update(over)
    return SetupDraftRequest(**base)


class TestRequest:
    def test_bounds(self):
        with pytest.raises(PydanticError):
            _req(kids=[])
        with pytest.raises(PydanticError):
            _req(kids=[{"name": f"k{i}", "age_band": "6-8"} for i in range(11)])
        with pytest.raises(PydanticError):
            _req(kids=[{"name": "x", "age_band": "4-7"}])
        with pytest.raises(PydanticError):
            _req(priorities=["homework"])
        with pytest.raises(PydanticError):
            _req(reward_styles=["money"])
        with pytest.raises(PydanticError):
            _req(note="x" * 301)
        with pytest.raises(PydanticError):
            _req(kids=[{"name": "   ", "age_band": "6-8"}])

    def test_lists_dedupe_and_note_is_cleaned(self):
        r = _req(priorities=["pets", "school", "pets"], reward_styles=["toys", "toys"], note="  hi\x00 there\n ok  ")
        assert r.priorities == ["pets", "school"] and r.reward_styles == ["toys"]
        assert r.note == "hi there ok"
        assert _req(note="   ").note is None
        assert _req(kids=[{"name": "  Sofía ", "age_band": "6-8"}]).kids[0].name == "Sofía"


class TestBand:
    def test_boundaries(self):
        today = date(2026, 10, 4)
        assert band_for_birthdate(date(2021, 10, 5), today) == "3-5"   # turns 5 tomorrow... still 4
        assert band_for_birthdate(date(2020, 10, 4), today) == "6-8"   # 6 today
        assert band_for_birthdate(date(2018, 10, 5), today) == "6-8"   # 7
        assert band_for_birthdate(date(2017, 10, 4), today) == "9-12"  # 9 today
        assert band_for_birthdate(date(2014, 10, 5), today) == "9-12"  # 11
        assert band_for_birthdate(date(2013, 10, 4), today) == "13+"   # 13 today


class TestPack:
    def test_filters_each_kid_band_by_priorities_and_caps(self):
        kids, rewards, gigs = pack_draft(_req())
        assert [k.name for k in kids] == ["Sofía", "Diego"]
        sofia, diego = kids
        assert 0 < len(sofia.chores) <= PACK_CHORES_PER_KID
        assert {c.title for c in sofia.chores} == {"Feed the pet", "Do homework without reminders", "Pack your school bag for tomorrow"}
        assert {c.title for c in diego.chores} == {"Vacuum the living room", "Complete your weekly study plan"}
        for c in sofia.chores + diego.chores:
            assert c.days == [] and c.is_bonus is False and c.duplicate_of is None

    def test_no_priorities_or_no_match_means_the_whole_band(self):
        kids, _, _ = pack_draft(_req(priorities=[]))
        assert len(kids[0].chores) == PACK_CHORES_PER_KID
        kids, _, _ = pack_draft(_req(kids=[{"name": "A", "age_band": "3-5"}], priorities=["school"]))
        # 3-5 answers "school" with exactly one chore (books) — still a filter, not the whole band
        assert [c.title for c in kids[0].chores] == ["Put the books back on the shelf"]

    def test_rewards_filtered_by_style_deduped_across_bands_capped(self):
        _, rewards, _ = pack_draft(_req(reward_styles=["screen_time"]))
        assert rewards and all(r.category == "screen_time" for r in rewards)
        titles = [r.title for r in rewards]
        assert len(titles) == len(set(titles)) and len(rewards) <= PACK_REWARDS
        _, rewards, _ = pack_draft(_req(reward_styles=[]))
        assert len(rewards) == PACK_REWARDS

    def test_gigs_only_when_wanted(self):
        _, _, gigs = pack_draft(_req())
        assert 0 < len(gigs) <= PACK_GIGS and all(g.points > 0 and 1 <= g.difficulty <= 3 for g in gigs)
        assert pack_draft(_req(wants_gigs=False))[2] == []

    def test_spanish_titles(self):
        kids, rewards, gigs = pack_draft(_req(lang="es", priorities=["pets"]))
        assert kids[0].chores[0].title == "Dar de comer a la mascota"

    def test_member_id_is_carried(self):
        mid = uuid4()
        kids, _, _ = pack_draft(_req(kids=[{"name": "Sofía", "age_band": "6-8", "member_id": str(mid)}]))
        assert kids[0].member_id == mid


class TestPrompt:
    def test_mentions_kids_bands_priorities_note_styles_and_examples(self):
        p = build_prompt(_req(note="Sofía loves the dog"))
        for s in ["Sofía", "6-8", "Diego", "13+", "school", "pets", "Sofía loves the dog", "screen_time", "Feed the pet", "Do your own laundry"]:
            assert s in p
        assert "cash gigs: yes" in p
        assert "cash gigs: no" in build_prompt(_req(wants_gigs=False))
        assert "Spanish" in build_prompt(_req(lang="es")) and "English" in p


def _reply(kids=None, rewards=None, gigs=None):
    return json.dumps({"kids": kids or [], "rewards": rewards or [], "gigs": gigs or []})


class TestParse:
    def test_happy_path_with_prose_around_the_json(self):
        text = "Here you go:\n" + _reply(
            kids=[{"name": "Sofía", "chores": [{"title": "Feed the dog", "points": 10, "days": ["mon", "wed"], "is_bonus": False, "notes": "after school"}]},
                  {"name": "Diego", "chores": [{"title": "Cook dinner", "points": 500, "days": "weekends", "is_bonus": "false"}]}],
            rewards=[{"title": "Movie night", "points_cost": 2, "category": "activities"}, {"title": "Cash", "points_cost": 50, "category": "money"}],
            gigs=[{"title": "Wash the car", "points": 5000, "difficulty": 7, "category": "nope"}],
        ) + "\nEnjoy!"
        kids, rewards, gigs = parse_draft(text, _req())
        assert kids[0].chores[0].title == "Feed the dog" and kids[0].chores[0].days == [0, 2] and kids[0].chores[0].description == "after school"
        assert kids[1].chores[0].points == 100 and kids[1].chores[0].days == [5, 6] and kids[1].chores[0].is_bonus is False
        assert rewards[0].points_cost == 5 and rewards[1].category == "privileges"
        assert gigs[0].points == 500 and gigs[0].difficulty == 3 and gigs[0].category == "other"

    def test_parse_matches_kid_names_by_fold(self):
        kids, _, _ = parse_draft(_reply(kids=[{"name": "sofia", "chores": [{"title": "Make bed"}]}]), _req())
        assert kids[0].name == "Sofía" and [c.title for c in kids[0].chores] == ["Make bed"]
        assert kids[1].chores == []

    def test_unknown_kid_dropped_and_caps(self):
        many = [{"title": f"c{i}"} for i in range(20)]
        kids, rewards, gigs = parse_draft(_reply(
            kids=[{"name": "Pepe", "chores": many}, {"name": "Diego", "chores": many}],
            rewards=[{"title": f"r{i}"} for i in range(20)], gigs=[{"title": f"g{i}"} for i in range(20)],
        ), _req())
        assert kids[0].chores == [] and len(kids[1].chores) == CHORES_PER_KID_MAX
        assert len(rewards) == REWARDS_MAX and len(gigs) == GIGS_MAX
        assert rewards[0].points_cost == 50 and gigs[0].points == 20 and kids[1].chores[0].points == 10

    def test_parse_duplicate_kid_names_go_to_first(self):
        req = _req(kids=[{"name": "Max", "age_band": "6-8"}, {"name": "max", "age_band": "9-12"}])
        kids, _, _ = parse_draft(_reply(kids=[{"name": "Max", "chores": [{"title": "A"}]}]), req)
        assert [c.title for c in kids[0].chores] == ["A"] and kids[1].chores == []

    def test_gigs_ignored_when_cash_off(self):
        _, _, gigs = parse_draft(_reply(kids=[{"name": "Sofía", "chores": [{"title": "A"}]}], gigs=[{"title": "G"}]), _req(wants_gigs=False))
        assert gigs == []

    def test_no_json_or_no_chores_raises(self):
        with pytest.raises(DraftParseError):
            parse_draft("I cannot help with that.", _req())
        with pytest.raises(DraftParseError):
            parse_draft("{not json", _req())
        with pytest.raises(DraftParseError):
            parse_draft(_reply(kids=[{"name": "Sofía", "chores": []}], rewards=[{"title": "R"}]), _req())


class TestDuplicates:
    def test_marks_by_folded_title_per_kind(self):
        kids, rewards, gigs = pack_draft(_req(priorities=["pets"]))
        mark_duplicates(kids, rewards, gigs,
                        chore_titles={"feed the pet": "Feed the pet"},
                        reward_titles={"30 minutes of screen time": "30 minutes of screen time"},
                        gig_titles={})
        assert kids[0].chores[0].duplicate_of == "Feed the pet"
        assert any(r.duplicate_of == "30 minutes of screen time" for r in rewards)
        assert all(g.duplicate_of is None for g in gigs)
