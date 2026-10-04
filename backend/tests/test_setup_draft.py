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
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest_asyncio

from app.models.gig import GigCategory, GigOffering
from app.models.reward import Reward, RewardCategory
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import APPROVAL_PENDING, User, UserRole
from app.schemas.setup_draft import SetupDraftResponse
from app.services.setup_draft_service import SetupDraftService


def _completion(text):
    msg = MagicMock(); msg.content = text
    choice = MagicMock(); choice.message = msg
    completion = MagicMock(); completion.choices = [choice]
    return completion


@pytest_asyncio.fixture
async def kids(db_session, test_family):
    from app.core.security import get_password_hash
    rows = [
        User(email="sofia@test.com", name="Sofía Martínez", password_hash=get_password_hash("password123"),
             role=UserRole.CHILD, family_id=test_family.id, is_active=True, email_verified=True),
        User(email="pending@test.com", name="Pepe", password_hash=get_password_hash("password123"),
             role=UserRole.CHILD, family_id=test_family.id, is_active=True, email_verified=True,
             approval_status=APPROVAL_PENDING),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    for r in rows:
        await db_session.refresh(r)
    return rows


class TestService:
    @pytest.mark.asyncio
    async def test_free_family_gets_pack_and_never_builds_the_client(self, db_session, test_family, kids, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        with patch("app.core.llm.OpenAI") as mock_openai:
            out = await SetupDraftService.draft(db_session, test_family.id, _req())
        assert isinstance(out, SetupDraftResponse)
        assert out.source == "pack" and out.ai_available is False and out.ai_failed is False
        mock_openai.assert_not_called()
        assert out.kids[0].chores

    @pytest.mark.asyncio
    async def test_paid_family_uses_the_ai_reply(self, db_session, test_family, kids, plus_subscription, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        reply = _reply(kids=[{"name": "Sofía", "chores": [{"title": "Walk the dog", "points": 12}]}],
                       rewards=[{"title": "Movie night", "points_cost": 40, "category": "activities"}])
        with patch("app.core.llm.OpenAI") as mock_openai:
            c = MagicMock(); c.chat.completions.create.return_value = _completion(reply)
            mock_openai.return_value = c
            out = await SetupDraftService.draft(db_session, test_family.id, _req())
        assert out.source == "ai" and out.ai_available is True and out.ai_failed is False
        assert out.kids[0].chores[0].title == "Walk the dog" and out.rewards[0].title == "Movie night"
        kwargs = c.chat.completions.create.call_args.kwargs
        assert kwargs["messages"][0]["role"] == "system" and "Sofía" in kwargs["messages"][1]["content"]

    @pytest.mark.asyncio
    async def test_ai_failure_falls_back_to_pack_with_flag(self, db_session, test_family, kids, plus_subscription, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        with patch("app.core.llm.OpenAI") as mock_openai:
            c = MagicMock(); c.chat.completions.create.side_effect = RuntimeError("boom")
            mock_openai.return_value = c
            out = await SetupDraftService.draft(db_session, test_family.id, _req())
        assert out.source == "pack" and out.ai_available is True and out.ai_failed is True
        assert out.kids[0].chores
        with patch("app.core.llm.OpenAI") as mock_openai:
            c = MagicMock(); c.chat.completions.create.return_value = _completion("Sorry, no.")
            mock_openai.return_value = c
            out = await SetupDraftService.draft(db_session, test_family.id, _req())
        assert out.source == "pack" and out.ai_failed is True

    @pytest.mark.asyncio
    async def test_no_llm_key_means_ai_unavailable_even_when_paid(self, db_session, test_family, kids, plus_subscription, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "")
        with patch("app.core.llm.OpenAI") as mock_openai:
            out = await SetupDraftService.draft(db_session, test_family.id, _req())
        assert out.source == "pack" and out.ai_available is False
        mock_openai.assert_not_called()

    @pytest.mark.asyncio
    async def test_binds_members_by_name_and_by_id_but_not_foreign_or_pending(self, db_session, test_family, kids):
        sofia, pepe = kids
        out = await SetupDraftService.draft(db_session, test_family.id, _req(kids=[
            {"name": "sofia", "age_band": "6-8"},                                   # by first name
            {"name": "Nobody", "age_band": "9-12", "member_id": str(sofia.id)},   # by explicit id
            {"name": "Pepe", "age_band": "9-12"},                                  # pending → unbound
            {"name": "Ghost", "age_band": "13+", "member_id": str(uuid4())},     # foreign id → unbound
        ]))
        assert [k.member_id for k in out.kids] == [sofia.id, sofia.id, None, None]

    @pytest.mark.asyncio
    async def test_draft_never_binds_a_parent(self, db_session, test_family, test_parent_user, kids):
        out = await SetupDraftService.draft(db_session, test_family.id, _req(kids=[
            {"name": test_parent_user.name, "age_band": "13+"},
            {"name": "x", "age_band": "13+", "member_id": str(test_parent_user.id)},
        ]))
        assert [k.member_id for k in out.kids] == [None, None]

    @pytest.mark.asyncio
    async def test_duplicates_marked_against_active_family_rows_only(self, db_session, test_family, test_parent_user, kids):
        other = test_family.__class__(name="Other")
        db_session.add(other); await db_session.commit(); await db_session.refresh(other)
        db_session.add_all([
            TaskTemplate(title="Feed the pet", points=5, interval_days=1, assignment_type=AssignmentType.AUTO,
                         is_bonus=False, is_active=True, family_id=test_family.id),
            TaskTemplate(title="Do homework without reminders", points=5, interval_days=1, assignment_type=AssignmentType.AUTO,
                         is_bonus=False, is_active=False, family_id=test_family.id),            # inactive → not a duplicate
            TaskTemplate(title="Pack your school bag for tomorrow", points=5, interval_days=1, assignment_type=AssignmentType.AUTO,
                         is_bonus=False, is_active=True, family_id=other.id),                   # other family → not a duplicate
            Reward(title="30 MINUTES of screen time", points_cost=15, category=RewardCategory.SCREEN_TIME,
                   family_id=test_family.id, is_active=True),
            GigOffering(title="Help wash the car", points=30, difficulty=2, category=GigCategory.CHORES,
                        family_id=test_family.id, created_by=test_parent_user.id, is_active=True),
        ])
        await db_session.commit()
        out = await SetupDraftService.draft(db_session, test_family.id, _req())
        by_title = {c.title: c.duplicate_of for c in out.kids[0].chores}
        assert by_title["Feed the pet"] == "Feed the pet"
        assert by_title["Do homework without reminders"] is None
        assert by_title["Pack your school bag for tomorrow"] is None
        assert any(r.duplicate_of == "30 MINUTES of screen time" for r in out.rewards)
        assert any(g.duplicate_of == "Help wash the car" for g in out.gigs)
from httpx import AsyncClient
from sqlalchemy import func, select


PAYLOAD = {
    "kids": [{"name": "Sofía", "age_band": "6-8"}], "priorities": ["pets"], "note": None,
    "reward_styles": [], "wants_gigs": True, "lang": "en",
}


class TestRoute:
    @pytest.mark.asyncio
    async def test_parent_gets_a_draft_and_nothing_is_stored(self, client: AsyncClient, auth_headers, db_session, test_family):
        async def counts():
            out = []
            for m in (TaskTemplate, Reward, GigOffering):
                out.append((await db_session.execute(select(func.count()).select_from(m).where(m.family_id == test_family.id))).scalar())
            return tuple(out)
        before = await counts()
        r = await client.post("/api/families/onboarding/setup-draft", json=PAYLOAD, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "pack" and body["kids"][0]["name"] == "Sofía" and body["kids"][0]["chores"]
        assert body["gigs"] and body["rewards"]
        assert await counts() == before

    @pytest.mark.asyncio
    async def test_bounds_422(self, client: AsyncClient, auth_headers):
        for bad in (
            {**PAYLOAD, "kids": []},
            {**PAYLOAD, "kids": [{"name": "k", "age_band": "6-8"}] * 11},
            {**PAYLOAD, "kids": [{"name": "k", "age_band": "2-4"}]},
            {**PAYLOAD, "priorities": ["homework"]},
            {**PAYLOAD, "note": "n" * 301},
        ):
            r = await client.post("/api/families/onboarding/setup-draft", json=bad, headers=auth_headers)
            assert r.status_code == 422, bad

    @pytest.mark.asyncio
    async def test_child_403(self, client: AsyncClient, test_child_user):
        login = await client.post("/api/auth/login", json={"email": "child@test.com", "password": "password123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = await client.post("/api/families/onboarding/setup-draft", json=PAYLOAD, headers=headers)
        assert r.status_code == 403
