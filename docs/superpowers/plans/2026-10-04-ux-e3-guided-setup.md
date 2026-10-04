# UX-E3 AI-guided family setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A four-step wizard at `/parent/setup` turns "kids + what matters + reward style" into a reviewed, one-click-created first set of chores, rewards and gigs — AI-drafted on paid plans, starter-pack-drafted on free — with a Jarvis hand-off for refinement.

**Architecture:** One new backend endpoint `POST /api/families/onboarding/setup-draft` returns a draft and stores nothing; a service with pure pack/parse functions decides AI vs pack and degrades to pack on any AI failure. The browser creates every ticked row through the ordinary create endpoints (E1 pattern: injected `post`, errors on rows). Name matching moves to a shared `name_match.py`.

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy async; LiteLLM via `app.core.llm.get_llm_client()` (`CATEGORIZER_MODEL`); pytest (mock `app.core.llm.OpenAI`); Astro 5 page + vanilla `<script>`; vitest (node, source-structure tests).

**Spec:** `docs/superpowers/specs/2026-10-04-ux-e3-guided-setup-design.md`

## Global Constraints

- The draft endpoint stores nothing; all creation goes through `POST /api/task-templates/`, `POST /api/rewards/`, `POST /api/gigs/offerings`, `POST /api/auth/register`, `PATCH /api/families/me`. No migration, no new table, no new onboarding event type.
- AI gate is SILENT: `family_tier_allows(db, family_id, "ai_features")` + `settings.LITELLM_API_KEY`; a free family gets HTTP 200 with `source = "pack"`. Route carries `@limiter.limit(AI_LIMIT)`. Pair added to `test_ai_gating.py`.
- Bounds: kids 1–10, name ≤ 60, priorities ⊂ {routine, school, home, kitchen, pets, self_care} ≤ 6, note ≤ 300 (control chars stripped), reward_styles ⊂ {screen_time, treats, activities, privileges, toys} ≤ 5. Draft caps: AI ≤ 8 chores/kid, ≤ 6 rewards, ≤ 4 gigs; pack 6 / 5 / 3. Clamps: chore points 1–100 (default 10), reward 5–500 (50), gig 10–500 (20), difficulty 1–3 (1).
- Every chore in `starter_packs.py` carries ≥ 1 tag from the six priorities (`CHORE_TAGS`).
- Frontend copy ONLY in `frontend/src/lib/setupWizard.ts` (page uses `SETUP_COPY`); `SetupCard` keeps its inline ES/EN style.
- Never native `alert`/`confirm`/`prompt`; `confirmSheet` from `lib/dialogs`; `showToast` from `lib/toast`; buttons through `buttonClass`; `hidden` attribute for states; text reaches the DOM through `textContent`/`value`, never `innerHTML`; no emoji in `<h1>`.
- Page tone `sky`; add `"pages/parent/setup.astro": "sky"` to `frontend/test/section-tones.test.ts`.
- Kid account role by band: `13+` → `teen`, else `child`.
- Commit trailer: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Tests: backend `$SP/e3jpt.sh <files>` (local PG 5435 + redis, see §Test helpers), frontend `$SP/e3jft.sh <files>`.

## Review Focus

1. A kid named like a PARENT ("Mariana" is the mother) — the draft must not bind the kid to the parent's account (only CHILD/TEEN members are candidates). Test: `test_draft_never_binds_a_parent` (Task 4).
2. The AI returns the kid's chores under a slightly different name ("Sofia" vs "Sofía") — must still land on that kid (fold). Test: `test_parse_matches_kid_names_by_fold` (Task 3).
3. The AI reply contains two kids with the SAME name — chores go to the first, the second stays empty, nothing crashes. Test: `test_parse_duplicate_kid_names_go_to_first` (Task 3).
4. Create with one failing row then Retry — only the failed row is re-posted, created rows are never duplicated. Test: `createAll retries only failed rows` (Task 6).
5. A family with `enabled_modules = null` turning cash OFF must keep every other module on (list = all togglable minus gigs), not switch everything off. Test: `modulesBodyWithoutGigs` (Task 6) + parity test against `backend/app/core/modules.py`.

## Test helpers (create once, before Task 1)

`$SP = /private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad`. Copy `emjpt.sh` → `e3jpt.sh` and `emjft.sh` → `e3jft.sh` with the worktree path changed to `.claude/worktrees/ux-e3-guided-setup`. The ephemeral PG (5435) and redis must be up (see memory `project_local_tests_sin_podman`).

---

### Task 1: Priority tags on every starter-pack chore

**Files:**
- Modify: `backend/app/data/starter_packs.py` (after `PACK_KEYS`, and at the end of the file)
- Test: `backend/tests/test_starter_pack_tags.py`

**Interfaces:**
- Produces: `PRIORITY_TAGS: tuple[str, ...] = ("routine", "school", "home", "kitchen", "pets", "self_care")`; `CHORE_TAGS: dict[str, tuple[str, ...]]`; every `STARTER_PACKS[band]["chores"][i]["tags"]: list[str]`.

- [ ] **Step 1: Write the failing test**

```python
"""UX-E3: every starter-pack chore carries priority tags the setup wizard filters on."""
from app.data.starter_packs import CHORE_TAGS, PRIORITY_TAGS, STARTER_PACKS


def test_priority_tags_are_the_six_wizard_chips():
    assert PRIORITY_TAGS == ("routine", "school", "home", "kitchen", "pets", "self_care")


def test_every_chore_has_at_least_one_known_tag():
    for band, pack in STARTER_PACKS.items():
        for chore in pack["chores"]:
            tags = chore.get("tags")
            assert isinstance(tags, list) and tags, f"{chore['id']} has no tags"
            assert set(tags) <= set(PRIORITY_TAGS), f"{chore['id']} unknown tag {tags}"


def test_chore_tags_map_matches_the_catalog_exactly():
    ids = {c["id"] for p in STARTER_PACKS.values() for c in p["chores"]}
    assert set(CHORE_TAGS) == ids


def test_every_priority_is_reachable_in_every_age_band():
    # The pack path filters a kid's band by the family's priorities; a tag no
    # band can answer would always fall back to the whole pack.
    for band in ("3-5", "6-8", "9-12", "13+"):
        covered = {t for c in STARTER_PACKS[band]["chores"] for t in c["tags"]}
        assert covered == set(PRIORITY_TAGS), f"{band} misses {set(PRIORITY_TAGS) - covered}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$SP/e3jpt.sh tests/test_starter_pack_tags.py`
Expected: FAIL with `ImportError: cannot import name 'CHORE_TAGS'`

- [ ] **Step 3: Add the tags**

In `backend/app/data/starter_packs.py`, right after `PACK_KEYS = AGE_BANDS + THEMED_PACKS`:

```python
# UX-E3 guided setup: the six "what matters" chips. Every chore carries one or
# more so the free-plan draft can filter a band by the family's answers.
PRIORITY_TAGS = ("routine", "school", "home", "kitchen", "pets", "self_care")
```

At the END of the file (after the `STARTER_PACKS` dict closes):

```python
# Chore id → priority tags (UX-E3). Kept as one table rather than inline keys
# so the catalog above stays readable; the loop below folds them in. The
# invariant test asserts the two sets of ids are identical and that every age
# band answers every tag (3-5 and 13+ are the thin ones — mind them).
CHORE_TAGS: dict[str, tuple[str, ...]] = {
    "3-5.chore.juguetes": ("home",),
    "3-5.chore.ropa-cesto": ("home", "routine"),
    "3-5.chore.zapatos": ("home", "routine"),
    "3-5.chore.dientes": ("self_care", "routine"),
    "3-5.chore.cama-ayuda": ("routine", "home"),
    "3-5.chore.servilletas": ("kitchen",),
    "3-5.chore.libros": ("home", "school"),
    "3-5.chore.mascota-ayuda": ("pets",),
    "3-5.chore.pijama": ("routine", "self_care"),
    "6-8.chore.cama": ("routine", "home"),
    "6-8.chore.cuarto": ("home",),
    "6-8.chore.mesa": ("kitchen",),
    "6-8.chore.mascota": ("pets",),
    "6-8.chore.tarea": ("school",),
    "6-8.chore.plato": ("kitchen",),
    "6-8.chore.mochila": ("school", "routine"),
    "6-8.chore.doblar-ropa": ("home", "self_care"),
    "6-8.chore.plantas": ("home",),
    "9-12.chore.cama-cuarto": ("routine", "home"),
    "9-12.chore.platos": ("kitchen",),
    "9-12.chore.basura": ("home",),
    "9-12.chore.tarea": ("school",),
    "9-12.chore.ropa": ("home", "self_care"),
    "9-12.chore.cocina": ("kitchen", "home"),
    "9-12.chore.cena-ayuda": ("kitchen",),
    "9-12.chore.perro": ("pets",),
    "9-12.chore.bano": ("home", "self_care"),
    "13+.chore.cuarto": ("home", "routine"),
    "13+.chore.lavar-ropa": ("self_care", "home"),
    "13+.chore.cocinar": ("kitchen",),
    "13+.chore.trastes": ("kitchen",),
    "13+.chore.basura": ("home",),
    "13+.chore.aspirar": ("home", "pets"),
    "13+.chore.despensa": ("kitchen",),
    "13+.chore.estudio": ("school",),
    "tdah.chore.rutina-manana": ("routine", "self_care"),
    "tdah.chore.mochila-noche": ("school", "routine"),
    "tdah.chore.ropa-lista": ("routine",),
    "tdah.chore.tablero-visual": ("routine",),
    "tdah.chore.escritorio-tarea": ("school",),
    "tdah.chore.descanso-movimiento": ("self_care",),
    "tdah.chore.rutina-noche": ("routine",),
    "tdah.chore.una-cosa": ("home",),
    "tdah.chore.plan-semana": ("routine", "school"),
}

for _pack in STARTER_PACKS.values():
    for _chore in _pack["chores"]:
        _chore["tags"] = list(CHORE_TAGS.get(_chore["id"], ()))
```

(`13+.chore.aspirar` carries `pets` on purpose — vacuuming is the pet-hair chore and it is the only way the 13+ band answers the `pets` tag; the band test enforces full coverage.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `$SP/e3jpt.sh tests/test_starter_pack_tags.py tests/test_starter_packs.py`
Expected: PASS (4 new + the existing pack suite — `StarterChore` schema ignores the extra key? It is a Pydantic model built from dicts; verify `list_packs` still passes. If `StarterChore` has `extra="forbid"`, add `tags: List[str] = []` to it in `backend/app/schemas/onboarding.py`.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/starter_packs.py backend/tests/test_starter_pack_tags.py backend/app/schemas/onboarding.py
git commit -m "feat(ux-e3): priority tags on every starter-pack chore

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Shared name matching module

**Files:**
- Create: `backend/app/services/name_match.py`
- Modify: `backend/app/services/chart_scanner_service.py` (remove `Member`, `fold`, `match_members` bodies; import them)
- Test: `backend/tests/test_name_match.py`

**Interfaces:**
- Produces: `name_match.Member(id: UUID, name: str, role: str)` (frozen dataclass), `name_match.fold(text: str) -> str`, `name_match.match_members(names: list[str], members: list[Member]) -> tuple[list[UUID], list[str]]`. `chart_scanner_service` re-exports all three (its tests import from there and stay unchanged).

- [ ] **Step 1: Write the failing test**

```python
"""The member-name matcher shared by the chart scanner (E1) and the setup wizard (E3)."""
from uuid import uuid4

from app.services.name_match import Member, fold, match_members


def test_fold_is_case_accent_and_space_insensitive():
    assert fold("  Sofía   MARTÍNEZ ") == "sofia martinez"


def test_match_by_first_or_full_name_and_report_unknown():
    d, s = uuid4(), uuid4()
    members = [Member(d, "Diego Martínez", "teen"), Member(s, "Sofía Martínez", "child")]
    ids, missing = match_members(["sofia", "Pepe"], members)
    assert ids == [s] and missing == ["Pepe"]


def test_chart_scanner_still_exposes_the_same_names():
    from app.services import chart_scanner_service as cs
    assert cs.fold is fold and cs.match_members is match_members and cs.Member is Member
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$SP/e3jpt.sh tests/test_name_match.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.name_match'`

- [ ] **Step 3: Create the module and import it from the scanner**

`backend/app/services/name_match.py`:

```python
"""Member-name matching shared by the chart scanner (UX-E1) and the guided
setup wizard (UX-E3): a name typed by a parent or read by the model → the
family member it means, never a guess."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Member:
    id: UUID
    name: str
    role: str


def fold(text: str) -> str:
    """Lower-case, accents stripped, whitespace collapsed — the comparison form."""
    stripped = "".join(ch for ch in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def match_members(names: list[str], members: list[Member]) -> tuple[list[UUID], list[str]]:
    """Member ids for the names given, in order, plus the names that matched
    nobody. A name matches a member's full name or first name; an ambiguous
    first name (two members share it) matches nobody — never assign a chore
    to the wrong kid."""
    by_full: dict[str, UUID] = {fold(m.name): m.id for m in members}
    first_counts: dict[str, int] = {}
    for m in members:
        first = fold(m.name).split(" ")[0] if fold(m.name) else ""
        first_counts[first] = first_counts.get(first, 0) + 1
    by_first: dict[str, UUID] = {
        fold(m.name).split(" ")[0]: m.id for m in members if first_counts.get(fold(m.name).split(" ")[0]) == 1
    }
    ids: list[UUID] = []
    missing: list[str] = []
    for raw in names or []:
        name = (raw or "").strip() if isinstance(raw, str) else ""
        if not name:
            continue
        key = fold(name)
        hit = by_full.get(key) or by_first.get(key)
        if hit is None:
            if name not in missing:
                missing.append(name)
        elif hit not in ids:
            ids.append(hit)
    return ids, missing
```

In `chart_scanner_service.py`: delete the `Member` dataclass, `fold` and `match_members` definitions and the now-unused `unicodedata` import and `dataclass` (keep `dataclass, field` — `ScannedChore` still uses them; drop only `unicodedata`). Add:

```python
from app.services.name_match import Member, fold, match_members  # noqa: F401 — re-exported for callers and tests
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$SP/e3jpt.sh tests/test_name_match.py tests/test_chart_scanner.py && cd backend && ruff check app`
Expected: PASS, ruff clean (if ruff flags the re-export, keep the `# noqa: F401`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/name_match.py backend/app/services/chart_scanner_service.py backend/tests/test_name_match.py
git commit -m "refactor(ux-e3): share member-name matching between scanner and setup

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Draft schemas + pure draft functions (pack path, prompt, parser, duplicates)

**Files:**
- Create: `backend/app/schemas/setup_draft.py`
- Create: `backend/app/services/setup_draft_service.py` (pure part; the DB part comes in Task 4)
- Test: `backend/tests/test_setup_draft.py`

**Interfaces:**
- Consumes: Task 1 `PRIORITY_TAGS`, `STARTER_PACKS[...]["chores"][i]["tags"]`; Task 2 `fold`; `chart_scanner_service.normalize_days`.
- Produces (schemas): `KidAnswer(name, age_band, member_id)`, `SetupDraftRequest(kids, priorities, note, reward_styles, wants_gigs, lang)`, `ChoreDraft`, `RewardDraft`, `GigDraft`, `KidDraft`, `SetupDraftResponse(source, ai_available, ai_failed, kids, rewards, gigs)`, `REWARD_STYLES`.
- Produces (service): `DraftParseError`, `band_for_birthdate(birthdate: date, today: date) -> str`, `pack_draft(req) -> tuple[list[KidDraft], list[RewardDraft], list[GigDraft]]`, `build_prompt(req) -> str`, `SYSTEM_PROMPT: str`, `parse_draft(text: str, req) -> same tuple`, `mark_duplicates(kids, rewards, gigs, chore_titles: dict[str, str], reward_titles: dict[str, str], gig_titles: dict[str, str]) -> None`, constants `CHORES_PER_KID_MAX = 8`, `REWARDS_MAX = 6`, `GIGS_MAX = 4`, `PACK_CHORES_PER_KID = 6`, `PACK_REWARDS = 5`, `PACK_GIGS = 3`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$SP/e3jpt.sh tests/test_setup_draft.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.setup_draft'`

- [ ] **Step 3: Write the schemas**

`backend/app/schemas/setup_draft.py`:

```python
"""UX-E3 guided setup: the wizard's answers in, a draft out. Nothing here is
persisted — the browser creates the ticked rows through the ordinary APIs."""
from __future__ import annotations

from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.data.starter_packs import PRIORITY_TAGS

AgeBand = Literal["3-5", "6-8", "9-12", "13+"]
# Reward categories a parent can ask for — never "money": only the gig board pays cash.
REWARD_STYLES = ("screen_time", "treats", "activities", "privileges", "toys")
KIDS_MAX = 10
KID_NAME_MAX = 60
NOTE_MAX = 300


def _clean_text(value: Optional[str]) -> Optional[str]:
    """One line, control characters removed (a NUL would 500 nothing here, but
    the text is echoed into an LLM prompt), None when blank."""
    text = " ".join("".join(ch for ch in (value or "") if ch.isprintable() or ch.isspace()).split())
    return text or None


def _dedupe(values: List[str], allowed: tuple) -> List[str]:
    out: List[str] = []
    for v in values:
        if v not in allowed:
            raise ValueError(f"unknown value: {v}")
        if v not in out:
            out.append(v)
    return out


class KidAnswer(BaseModel):
    name: str = Field(..., min_length=1, max_length=KID_NAME_MAX)
    age_band: AgeBand
    # Client-supplied; the service re-checks it belongs to the caller's family.
    member_id: Optional[UUID] = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is blank")
        return v


class SetupDraftRequest(BaseModel):
    kids: List[KidAnswer] = Field(..., min_length=1, max_length=KIDS_MAX)
    priorities: List[str] = Field(default_factory=list, max_length=len(PRIORITY_TAGS))
    note: Optional[str] = Field(None, max_length=NOTE_MAX)
    reward_styles: List[str] = Field(default_factory=list, max_length=len(REWARD_STYLES))
    wants_gigs: bool = True
    lang: Literal["es", "en"] = "en"

    @field_validator("priorities")
    @classmethod
    def _priorities(cls, v: List[str]) -> List[str]:
        return _dedupe(v, PRIORITY_TAGS)

    @field_validator("reward_styles")
    @classmethod
    def _styles(cls, v: List[str]) -> List[str]:
        return _dedupe(v, REWARD_STYLES)

    @field_validator("note")
    @classmethod
    def _note(cls, v: Optional[str]) -> Optional[str]:
        return _clean_text(v)


class ChoreDraft(BaseModel):
    title: str
    points: int
    days: List[int] = Field(default_factory=list)   # 0 = Monday … 6 = Sunday; [] = every day
    is_bonus: bool = False
    description: Optional[str] = None
    duplicate_of: Optional[str] = None


class RewardDraft(BaseModel):
    title: str
    points_cost: int
    category: str
    description: Optional[str] = None
    duplicate_of: Optional[str] = None


class GigDraft(BaseModel):
    title: str
    points: int          # cash, MXN
    difficulty: int = 1
    category: str = "other"
    duplicate_of: Optional[str] = None


class KidDraft(BaseModel):
    name: str
    age_band: AgeBand
    member_id: Optional[UUID] = None
    chores: List[ChoreDraft] = Field(default_factory=list)


class SetupDraftResponse(BaseModel):
    source: Literal["ai", "pack"]
    ai_available: bool
    ai_failed: bool = False
    kids: List[KidDraft]
    rewards: List[RewardDraft]
    gigs: List[GigDraft]
```

- [ ] **Step 4: Write the pure service functions**

`backend/app/services/setup_draft_service.py` (Task 4 appends the DB class to this same file):

```python
"""UX-E3 guided setup: answers → a draft set of chores, rewards and gigs.

Two paths behind one shape: an LLM draft (paid plans, through LiteLLM) and a
deterministic starter-pack draft (free plans, and the fallback whenever the
AI path fails). The draft is never stored — see the route docstring.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Optional

from app.data.starter_packs import STARTER_PACKS
from app.models.gig import GigCategory
from app.schemas.setup_draft import (
    REWARD_STYLES, ChoreDraft, GigDraft, KidDraft, RewardDraft, SetupDraftRequest,
)
from app.services.chart_scanner_service import normalize_days
from app.services.name_match import fold

logger = logging.getLogger(__name__)

CHORES_PER_KID_MAX = 8
REWARDS_MAX = 6
GIGS_MAX = 4
PACK_CHORES_PER_KID = 6
PACK_REWARDS = 5
PACK_GIGS = 3
TITLE_MAX = 200
DESCRIPTION_MAX = 1000
# (min, max, default) — chores earn points, rewards cost points, gigs pay cash.
CHORE_POINTS = (1, 100, 10)
REWARD_POINTS = (5, 500, 50)
GIG_POINTS = (10, 500, 20)
_GIG_CATEGORIES = {c.value for c in GigCategory}


class DraftParseError(Exception):
    """The model's answer held no usable draft."""


def band_for_birthdate(birthdate: date, today: date) -> str:
    age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
    if age < 6:
        return "3-5"
    if age <= 8:
        return "6-8"
    if age <= 12:
        return "9-12"
    return "13+"


def _clamp(raw: Any, lo: int, hi: int, default: int) -> int:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _title(raw: Any) -> str:
    return " ".join(str(raw or "").split())[:TITLE_MAX]


def _description(raw: Any) -> Optional[str]:
    text = " ".join(str(raw).split())[:DESCRIPTION_MAX] if isinstance(raw, str) and raw.strip() else ""
    return text or None


# ── Pack path ────────────────────────────────────────────────────────────────

def pack_draft(req: SetupDraftRequest) -> tuple[list[KidDraft], list[RewardDraft], list[GigDraft]]:
    """Deterministic draft from the age-band packs, filtered by the answers.
    A priority set no chore of the band answers falls back to the whole band."""
    lang = req.lang
    wanted = set(req.priorities)
    kids: list[KidDraft] = []
    for kid in req.kids:
        pool = STARTER_PACKS[kid.age_band]["chores"]
        chores = [c for c in pool if wanted & set(c.get("tags", ()))] or pool
        kids.append(KidDraft(
            name=kid.name, age_band=kid.age_band, member_id=kid.member_id,
            chores=[ChoreDraft(title=c[f"title_{lang}"], points=c["points"]) for c in chores[:PACK_CHORES_PER_KID]],
        ))
    bands = list(dict.fromkeys(k.age_band for k in req.kids))
    styles = set(req.reward_styles)
    rewards: list[RewardDraft] = []
    seen: set[str] = set()
    for band in bands:
        for r in STARTER_PACKS[band]["rewards"]:
            if styles and r["category"] not in styles:
                continue
            key = fold(r[f"title_{lang}"])
            if key in seen:
                continue
            seen.add(key)
            rewards.append(RewardDraft(title=r[f"title_{lang}"], points_cost=r["points_cost"], category=r["category"]))
    gigs: list[GigDraft] = []
    if req.wants_gigs:
        seen = set()
        for band in bands:
            for g in STARTER_PACKS[band]["gigs"]:
                key = fold(g[f"title_{lang}"])
                if key in seen:
                    continue
                seen.add(key)
                gigs.append(GigDraft(title=g[f"title_{lang}"], points=g["points"], difficulty=g["difficulty"], category=g["category"]))
    return kids, rewards[:PACK_REWARDS], gigs[:PACK_GIGS]


# ── AI path: prompt + parser ─────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You help a parent set up a family chore and reward board. "
    "Reply with ONE JSON object and nothing else — no prose, no markdown fences."
)


def build_prompt(req: SetupDraftRequest) -> str:
    language = "Spanish (Mexico)" if req.lang == "es" else "English"
    kids = "\n".join(
        f"- {k.name}, age band {k.age_band}" + (" (already uses the app)" if k.member_id else "") for k in req.kids
    )
    bands = list(dict.fromkeys(k.age_band for k in req.kids))
    examples = []
    for band in bands:
        pack = STARTER_PACKS[band]
        examples.append(f"Age band {band}:")
        examples += [f"  chore: {c[f'title_{req.lang}']} ({c['points']} pts)" for c in pack["chores"]]
        examples += [f"  reward: {r[f'title_{req.lang}']} ({r['points_cost']} pts, {r['category']})" for r in pack["rewards"]]
        examples += [f"  gig: {g[f'title_{req.lang}']} (${g['points']} MXN, difficulty {g['difficulty']})" for g in pack["gigs"]]
    priorities = ", ".join(req.priorities) or "(none given)"
    styles = ", ".join(req.reward_styles) or "(any of screen_time, treats, activities, privileges, toys)"
    note = req.note or "(none)"
    return f"""The family's kids:
{kids}

What matters to the parent: {priorities}
Parent's note: {note}
Reward styles they like: {styles}
Do they want cash gigs: {"yes" if req.wants_gigs else "no"}

Examples of the right size and tone for these ages — adapt them to the answers, do not copy blindly:
{chr(10).join(examples)}

Return ONLY JSON in this shape:
{{
  "kids": [
    {{"name": "<kid name exactly as listed>", "chores": [
      {{"title": "Feed the dog", "points": 10, "days": ["mon", "wed", "fri"], "is_bonus": false, "notes": "after school or null"}}
    ]}}
  ],
  "rewards": [{{"title": "Movie night", "points_cost": 50, "category": "activities"}}],
  "gigs": [{{"title": "Wash the car", "points": 50, "difficulty": 2, "category": "chores"}}]
}}

Rules:
- Write every title in {language}, short and imperative. Never put a kid's name inside a title.
- One entry per kid, {CHORES_PER_KID_MAX} chores at most each, fitting the kid's age band and the parent's priorities; mark at most 2 per kid as is_bonus (optional extra).
- points: 1 to 100 by effort (5 tiny, 10 normal, 20 big).
- days: "mon".."sun", "weekdays", "weekends", or an empty list for every day.
- rewards: {REWARDS_MAX} at most, points_cost 5 to 500, category one of screen_time, treats, activities, privileges, toys. Never money.
- gigs: {"up to " + str(GIGS_MAX) + " paid extra jobs, points = pesos (10 to 500), difficulty 1-3, category one of chores, errands, creative, learning, outdoor, other" if req.wants_gigs else "an empty list"}."""


def parse_draft(text: str, req: SetupDraftRequest) -> tuple[list[KidDraft], list[RewardDraft], list[GigDraft]]:
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        raise DraftParseError("no JSON in the reply")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise DraftParseError(f"bad JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DraftParseError("reply is not an object")

    # Each kid's slot is keyed by folded name; a second kid with the same
    # name keeps an empty slot (the model's chores go to the first).
    slot: dict[str, int] = {}
    for i, kid in enumerate(req.kids):
        slot.setdefault(fold(kid.name), i)
    chores_by_kid: list[list[ChoreDraft]] = [[] for _ in req.kids]
    raw_kids = data.get("kids")
    for raw_kid in raw_kids if isinstance(raw_kids, list) else []:
        if not isinstance(raw_kid, dict):
            continue
        idx = slot.get(fold(str(raw_kid.get("name") or "")))
        if idx is None:
            continue
        raw_chores = raw_kid.get("chores")
        for raw in raw_chores if isinstance(raw_chores, list) else []:
            if not isinstance(raw, dict):
                continue
            title = _title(raw.get("title"))
            if not title:
                continue
            chores_by_kid[idx].append(ChoreDraft(
                title=title,
                points=_clamp(raw.get("points"), *CHORE_POINTS),
                days=normalize_days(raw.get("days")),
                is_bonus=raw.get("is_bonus") is True,          # the string "false" must not count
                description=_description(raw.get("notes")),
            ))
            if len(chores_by_kid[idx]) >= CHORES_PER_KID_MAX:
                break
    kids = [
        KidDraft(name=k.name, age_band=k.age_band, member_id=k.member_id, chores=chores_by_kid[i])
        for i, k in enumerate(req.kids)
    ]
    if not any(k.chores for k in kids):
        raise DraftParseError("no chores for any kid")

    rewards: list[RewardDraft] = []
    raw_rewards = data.get("rewards")
    for raw in raw_rewards if isinstance(raw_rewards, list) else []:
        if not isinstance(raw, dict):
            continue
        title = _title(raw.get("title"))
        if not title:
            continue
        category = raw.get("category") if raw.get("category") in REWARD_STYLES else "privileges"
        rewards.append(RewardDraft(
            title=title, points_cost=_clamp(raw.get("points_cost"), *REWARD_POINTS),
            category=category, description=_description(raw.get("description")),
        ))
        if len(rewards) >= REWARDS_MAX:
            break

    gigs: list[GigDraft] = []
    raw_gigs = data.get("gigs")
    for raw in (raw_gigs if isinstance(raw_gigs, list) and req.wants_gigs else []):
        if not isinstance(raw, dict):
            continue
        title = _title(raw.get("title"))
        if not title:
            continue
        category = raw.get("category") if raw.get("category") in _GIG_CATEGORIES else "other"
        gigs.append(GigDraft(
            title=title, points=_clamp(raw.get("points"), *GIG_POINTS),
            difficulty=_clamp(raw.get("difficulty"), 1, 3, 1), category=category,
        ))
        if len(gigs) >= GIGS_MAX:
            break
    return kids, rewards, gigs


def mark_duplicates(
    kids: list[KidDraft], rewards: list[RewardDraft], gigs: list[GigDraft],
    chore_titles: dict[str, str], reward_titles: dict[str, str], gig_titles: dict[str, str],
) -> None:
    """Fill `duplicate_of` with the family's existing title whose fold() equals
    the draft's. The maps are fold(title) → the title as stored."""
    for kid in kids:
        for c in kid.chores:
            c.duplicate_of = chore_titles.get(fold(c.title))
    for r in rewards:
        r.duplicate_of = reward_titles.get(fold(r.title))
    for g in gigs:
        g.duplicate_of = gig_titles.get(fold(g.title))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$SP/e3jpt.sh tests/test_setup_draft.py && cd backend && ruff check app`
Expected: PASS (21 tests), ruff clean. If `TestPack.test_filters_each_kid_band_by_priorities_and_caps` disagrees on a title set, the tags from Task 1 are the authority — fix the expected set in the test only if the Task 1 table says so.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/setup_draft.py backend/app/services/setup_draft_service.py backend/tests/test_setup_draft.py
git commit -m "feat(ux-e3): setup-draft schemas, pack draft, prompt and parser

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `SetupDraftService.draft` — member binding, AI vs pack, duplicates

**Files:**
- Modify: `backend/app/services/setup_draft_service.py` (append)
- Test: `backend/tests/test_setup_draft.py` (append `TestService`)

**Interfaces:**
- Consumes: Task 3 functions; `app.core.premium.family_tier_allows(db, family_id, feature) -> bool`; `app.core.llm.get_llm_client()`, `CATEGORIZER_MODEL`; `app.core.metrics.record_llm_call`; `FamilyService.get_family_members(db, family_id)`; `APPROVAL_APPROVED`; `name_match.Member/match_members`.
- Produces: `SetupDraftService.draft(db, family_id: UUID, req: SetupDraftRequest) -> SetupDraftResponse`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_setup_draft.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$SP/e3jpt.sh tests/test_setup_draft.py -k TestService`
Expected: FAIL with `ImportError: cannot import name 'SetupDraftService'`

- [ ] **Step 3: Append the service class**

Append to `backend/app/services/setup_draft_service.py` (add the imports at the top of the file: `from uuid import UUID`, `from fastapi.concurrency import run_in_threadpool`, `from sqlalchemy import select`, `from sqlalchemy.ext.asyncio import AsyncSession`, `from app.core.config import settings`, `from app.core.llm import CATEGORIZER_MODEL, get_llm_client`, `from app.core.metrics import record_llm_call`, `from app.core.premium import family_tier_allows`, `from app.models.gig import GigOffering`, `from app.models.reward import Reward`, `from app.models.task_template import TaskTemplate`, `from app.models.user import APPROVAL_APPROVED`, `from app.schemas.setup_draft import SetupDraftResponse`, `from app.services.family_service import FamilyService`, `from app.services.name_match import Member, match_members`):

```python
# ── The service ──────────────────────────────────────────────────────────────

_KID_ROLES = ("child", "teen")


async def _ai_draft(req: SetupDraftRequest) -> tuple[list[KidDraft], list[RewardDraft], list[GigDraft]]:
    client = get_llm_client()
    prompt = build_prompt(req)
    record_llm_call()
    completion = await run_in_threadpool(
        lambda: client.chat.completions.create(
            model=CATEGORIZER_MODEL,
            max_tokens=3072,
            temperature=0.4,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
    )
    return parse_draft((completion.choices[0].message.content or "").strip(), req)


class SetupDraftService:
    @staticmethod
    async def draft(db: AsyncSession, family_id: UUID, req: SetupDraftRequest) -> SetupDraftResponse:
        # Only kids who take part: active, approved, CHILD or TEEN. A parent is
        # never a binding candidate, whatever name or id the client sends.
        members = [
            Member(m.id, m.name, str(getattr(m.role, "value", m.role)).lower())
            for m in await FamilyService.get_family_members(db, family_id)
            if m.is_active and m.approval_status == APPROVAL_APPROVED
            and str(getattr(m.role, "value", m.role)).lower() in _KID_ROLES
        ]
        by_id = {m.id for m in members}
        bound = []
        for kid in req.kids:
            member_id = kid.member_id if kid.member_id in by_id else None
            if member_id is None:
                ids, _ = match_members([kid.name], members)
                member_id = ids[0] if ids else None
            bound.append(kid.model_copy(update={"member_id": member_id}))
        req = req.model_copy(update={"kids": bound})

        ai_available = bool(settings.LITELLM_API_KEY) and await family_tier_allows(db, family_id, "ai_features")
        source = "pack"
        ai_failed = False
        kids = rewards = gigs = None
        if ai_available:
            try:
                kids, rewards, gigs = await _ai_draft(req)
                source = "ai"
            except Exception as exc:  # transport, timeout, DraftParseError — the pack is the answer
                logger.warning("setup draft: AI path failed, using starter packs: %s", exc)
                ai_failed = True
        if source == "pack":
            kids, rewards, gigs = pack_draft(req)

        chore_titles: dict[str, str] = {}
        for title, title_es in (await db.execute(
            select(TaskTemplate.title, TaskTemplate.title_es)
            .where(TaskTemplate.family_id == family_id, TaskTemplate.is_active.is_(True))
        )).all():
            for t in (title, title_es):
                if t:
                    chore_titles.setdefault(fold(t), t)
        reward_titles = {
            fold(t): t for t in (await db.execute(
                select(Reward.title).where(Reward.family_id == family_id, Reward.is_active.is_(True))
            )).scalars() if t
        }
        gig_titles = {
            fold(t): t for t in (await db.execute(
                select(GigOffering.title).where(GigOffering.family_id == family_id, GigOffering.is_active.is_(True))
            )).scalars() if t
        }
        mark_duplicates(kids, rewards, gigs, chore_titles, reward_titles, gig_titles)
        return SetupDraftResponse(
            source=source, ai_available=ai_available, ai_failed=ai_failed,
            kids=kids, rewards=rewards, gigs=gigs,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$SP/e3jpt.sh tests/test_setup_draft.py && cd backend && ruff check app`
Expected: PASS (28), ruff clean. If `test_duplicates_marked_against_active_family_rows_only` fails building `Family(name=...)`, check `test_family`'s fixture for the required columns and mirror them.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/setup_draft_service.py backend/tests/test_setup_draft.py
git commit -m "feat(ux-e3): SetupDraftService — member binding, AI with pack fallback, duplicates

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Route `POST /api/families/onboarding/setup-draft` + gating pair

**Files:**
- Modify: `backend/app/api/routes/onboarding.py`
- Test: `backend/tests/test_setup_draft.py` (append `TestRoute`), `backend/tests/test_ai_gating.py` (append pair)

**Interfaces:**
- Consumes: Task 4 `SetupDraftService.draft`; `app.core.rate_limiter.limiter, AI_LIMIT`.
- Produces: `POST /api/families/onboarding/setup-draft` → `SetupDraftResponse` (200), 422 on bounds, 403 for non-parents.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_draft.py`:

```python
from httpx import AsyncClient
from sqlalchemy import func


PAYLOAD = {
    "kids": [{"name": "Sofía", "age_band": "6-8"}], "priorities": ["pets"], "note": None,
    "reward_styles": [], "wants_gigs": True, "lang": "en",
}


class TestRoute:
    @pytest.mark.asyncio
    async def test_parent_gets_a_draft_and_nothing_is_stored(self, client: AsyncClient, auth_headers, db_session, test_family):
        async def counts():
            return tuple(
                (await db_session.execute(select(func.count()).select_from(m).where(m.family_id == test_family.id))).scalar()
                for m in (TaskTemplate, Reward, GigOffering)
            )
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
```

Append to `tests/test_ai_gating.py` (after the scan-chart pair):

```python
SETUP_DRAFT = {"kids": [{"name": "Sofía", "age_band": "6-8"}], "priorities": [], "reward_styles": [], "wants_gigs": False, "lang": "en"}


@pytest.mark.asyncio
async def test_setup_draft_free_is_pack_and_never_calls_the_llm(client: AsyncClient, auth_headers, monkeypatch):
    """UX-E3 is a SILENT gate: the free plan gets the starter-pack draft (200),
    not a 403 — but the LLM client must never be built for it."""
    from unittest.mock import patch
    from app.core import config
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
    with patch("app.core.llm.OpenAI") as mock_openai:
        r = await client.post("/api/families/onboarding/setup-draft", json=SETUP_DRAFT, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "pack" and r.json()["ai_available"] is False
    mock_openai.assert_not_called()


@pytest.mark.asyncio
async def test_setup_draft_plus_calls_the_llm(client: AsyncClient, auth_headers, plus_subscription, monkeypatch):
    from unittest.mock import MagicMock, patch
    from app.core import config
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
    with patch("app.core.llm.OpenAI") as mock_openai:
        msg = MagicMock(); msg.content = '{"kids": [{"name": "Sofía", "chores": [{"title": "Make bed"}]}], "rewards": [], "gigs": []}'
        choice = MagicMock(); choice.message = msg
        completion = MagicMock(); completion.choices = [choice]
        c = MagicMock(); c.chat.completions.create.return_value = completion
        mock_openai.return_value = c
        r = await client.post("/api/families/onboarding/setup-draft", json=SETUP_DRAFT, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "ai" and r.json()["kids"][0]["chores"][0]["title"] == "Make bed"
    mock_openai.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$SP/e3jpt.sh tests/test_setup_draft.py -k TestRoute tests/test_ai_gating.py -k setup_draft`
Expected: FAIL — `assert 404 == 200` (route missing).

- [ ] **Step 3: Add the route**

In `backend/app/api/routes/onboarding.py`: extend the fastapi import to `from fastapi import APIRouter, Depends, HTTPException, Request, Response, status`; add `from app.core.rate_limiter import limiter, AI_LIMIT`, `from app.schemas.setup_draft import SetupDraftRequest, SetupDraftResponse`, `from app.services.setup_draft_service import SetupDraftService`. After `apply_starter_pack`:

```python
@router.post("/setup-draft", response_model=SetupDraftResponse)
@limiter.limit(AI_LIMIT)
async def setup_draft(
    request: Request,
    payload: SetupDraftRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """UX-E3 guided setup: the wizard's answers → a draft of chores per kid,
    rewards and gigs. STORES NOTHING — the browser creates the ticked rows
    through the ordinary create endpoints. The AI gate is silent: a free
    family gets the starter-pack draft (200), never a 403; AI_LIMIT because
    the paid path spends LLM budget."""
    family_id = to_uuid_required(current_user.family_id)
    return await SetupDraftService.draft(db, family_id, payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$SP/e3jpt.sh tests/test_setup_draft.py tests/test_ai_gating.py tests/test_onboarding.py tests/test_starter_packs.py && cd backend && ruff check app`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/onboarding.py backend/tests/test_setup_draft.py backend/tests/test_ai_gating.py
git commit -m "feat(ux-e3): POST /api/families/onboarding/setup-draft (silent AI gate)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Frontend lib `setupWizard.ts`

**Files:**
- Create: `frontend/src/lib/setupWizard.ts`
- Test: `frontend/test/setup-wizard.test.ts`

**Interfaces:**
- Consumes: `lib/chartScan.ts` `errorDetail`, `fill`, `PostResult`.
- Produces: everything the page (Task 7) imports — see the file's exports below.

- [ ] **Step 1: Write the failing tests**

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
    BANDS, PRIORITIES, REWARD_STYLES, SETUP_COPY, TOGGLABLE_MODULES, bandForBirthdate, canAdvanceKids, choreBody,
    createAll, draftRequest, gigBody, jarvisPrefill, kidRowsFromMembers, modulesBodyWithoutGigs, registerBody,
    reviewRows, rewardBody, type Poster, type Review, type WizardState,
} from "../src/lib/setupWizard";

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");

const members = [
    { id: "s1", name: "Sofía", role: "child", is_active: true, approval_status: "approved" },
    { id: "d1", name: "Diego", role: "teen", is_active: true, approval_status: "approved" },
    { id: "m1", name: "Mariana", role: "parent", is_active: true, approval_status: "approved" },
    { id: "p1", name: "Pepe", role: "child", is_active: true, approval_status: "pending" },
    { id: "x1", name: "Gone", role: "child", is_active: false, approval_status: "approved" },
];

const state = (over: Partial<WizardState> = {}): WizardState => ({
    kids: [
        { key: "k0", name: "Sofía", band: "6-8", memberId: "s1", locked: true, included: true },
        { key: "k1", name: "Nuevo", band: "13+", memberId: null, locked: false, included: true },
        { key: "k2", name: "Skip", band: "3-5", memberId: null, locked: false, included: false },
    ],
    priorities: ["school"], note: "", rewardStyles: ["treats"], wantsGigs: true, ...over,
});

const draft = {
    source: "ai", ai_available: true, ai_failed: false,
    kids: [
        { name: "Sofía", age_band: "6-8", member_id: "s1", chores: [
            { title: "Feed the pet", points: 5, days: [0, 2], is_bonus: false, description: null, duplicate_of: "Feed the pet" },
            { title: "Homework", points: 10, days: [], is_bonus: true, description: "after lunch", duplicate_of: null },
        ] },
        { name: "Nuevo", age_band: "13+", member_id: null, chores: [{ title: "Cook", points: 20, days: [], is_bonus: false, description: null, duplicate_of: null }] },
    ],
    rewards: [{ title: "Pizza", points_cost: 40, category: "treats", description: null, duplicate_of: null }],
    gigs: [{ title: "Wash car", points: 50, difficulty: 2, category: "chores", duplicate_of: null }],
};

describe("constants", () => {
    it("bands, priorities and styles match the backend", () => {
        expect(BANDS).toEqual(["3-5", "6-8", "9-12", "13+"]);
        expect(PRIORITIES).toEqual(["routine", "school", "home", "kitchen", "pets", "self_care"]);
        expect(REWARD_STYLES).toEqual(["screen_time", "treats", "activities", "privileges", "toys"]);
        const py = read("../../backend/app/core/modules.py");
        for (const m of TOGGLABLE_MODULES) expect(py).toContain(`"${m}"`);
        expect(TOGGLABLE_MODULES).toHaveLength(7);
    });
    it("every copy key has both languages", () => {
        for (const [k, v] of Object.entries(SETUP_COPY)) expect(Object.keys(v), k).toEqual(["es", "en"]);
    });
});

describe("kids step", () => {
    it("kidRowsFromMembers keeps active approved kids only, band by role", () => {
        const rows = kidRowsFromMembers(members);
        expect(rows.map((r) => [r.name, r.band, r.memberId, r.locked])).toEqual([["Sofía", "6-8", "s1", true], ["Diego", "13+", "d1", true]]);
        expect(kidRowsFromMembers(null)).toEqual([]);
    });
    it("bandForBirthdate boundaries", () => {
        const today = new Date(2026, 9, 4);
        expect(bandForBirthdate("2021-10-05", today)).toBe("3-5");
        expect(bandForBirthdate("2020-10-04", today)).toBe("6-8");
        expect(bandForBirthdate("2017-10-04", today)).toBe("9-12");
        expect(bandForBirthdate("2013-10-04", today)).toBe("13+");
    });
    it("canAdvanceKids needs one included row with a name and a band", () => {
        expect(canAdvanceKids(state())).toBe(true);
        expect(canAdvanceKids(state({ kids: [{ key: "k", name: " ", band: "6-8", memberId: null, locked: false, included: true }] }))).toBe(false);
        expect(canAdvanceKids(state({ kids: [{ key: "k", name: "A", band: null, memberId: null, locked: false, included: true }] }))).toBe(false);
        expect(canAdvanceKids(state({ kids: [{ key: "k", name: "A", band: "6-8", memberId: null, locked: false, included: false }] }))).toBe(false);
    });
    it("draftRequest sends included rows only, trimmed", () => {
        const body = draftRequest(state({ note: "  dog  " }), "es");
        expect(body).toEqual({
            kids: [{ name: "Sofía", age_band: "6-8", member_id: "s1" }, { name: "Nuevo", age_band: "13+", member_id: null }],
            priorities: ["school"], note: "dog", reward_styles: ["treats"], wants_gigs: true, lang: "es",
        });
        expect(draftRequest(state({ note: "   " }), "en").note).toBeNull();
    });
});

describe("review", () => {
    it("reviewRows unticks duplicates and starts idle", () => {
        const r = reviewRows(draft);
        expect(r.kids).toHaveLength(2);
        expect(r.kids[0].chores[0]).toMatchObject({ title: "Feed the pet", included: false, duplicateOf: "Feed the pet", status: "idle", error: null, days: [0, 2] });
        expect(r.kids[0].chores[1]).toMatchObject({ included: true, isBonus: true, description: "after lunch" });
        expect(r.kids[1]).toMatchObject({ name: "Nuevo", memberId: null });
        expect(r.rewards[0]).toMatchObject({ title: "Pizza", pointsCost: 40, category: "treats", included: true });
        expect(r.gigs[0]).toMatchObject({ title: "Wash car", points: 50, difficulty: 2, included: true });
        expect(reviewRows(null)).toEqual({ kids: [], rewards: [], gigs: [] });
    });
    it("choreBody is FIXED to the kid when bound, AUTO otherwise; Spanish fills the es columns", () => {
        const row = reviewRows(draft).kids[0].chores[1];
        expect(choreBody(row, "s1", "en")).toEqual({
            title: "Homework", points: 10, is_bonus: true, days_of_week: null, interval_days: 1,
            assignment_type: "fixed", assigned_user_ids: ["s1"], description: "after lunch",
        });
        const auto = choreBody(reviewRows(draft).kids[0].chores[0], null, "es");
        expect(auto).toMatchObject({ assignment_type: "auto", assigned_user_ids: null, days_of_week: [0, 2], title_es: "Feed the pet", description_es: null });
    });
    it("rewardBody, gigBody, registerBody", () => {
        expect(rewardBody(reviewRows(draft).rewards[0])).toEqual({ title: "Pizza", points_cost: 40, category: "treats", description: null });
        expect(gigBody(reviewRows(draft).gigs[0])).toEqual({ title: "Wash car", points: 50, difficulty: 2, category: "chores" });
        expect(registerBody({ name: "Nuevo", band: "13+" }, "n@x.com", "secret123")).toEqual({ name: "Nuevo", email: "n@x.com", password: "secret123", role: "teen" });
        expect(registerBody({ name: "Peque", band: "3-5" }, "p@x.com", "secret123").role).toBe("child");
    });
    it("modulesBodyWithoutGigs keeps every other module", () => {
        expect(modulesBodyWithoutGigs(null)).toEqual({ enabled_modules: ["meals", "shopping", "calendar", "pet", "chat", "budget"] });
        expect(modulesBodyWithoutGigs(["budget", "gigs", "chat"])).toEqual({ enabled_modules: ["budget", "chat"] });
    });
});

describe("createAll", () => {
    const review = (): Review => reviewRows(draft);
    it("posts ticked rows in order and reports counts", async () => {
        const calls: string[] = [];
        const post: Poster = async (path) => { calls.push(path); return { ok: true, detail: null }; };
        const r = review();
        const counts = await createAll(r, "en", post);
        expect(calls).toEqual(["/api/task-templates/", "/api/task-templates/", "/api/rewards/", "/api/gigs/offerings"]);
        expect(counts).toEqual({ chores: 2, rewards: 1, gigs: 1 });
        expect(r.kids[0].chores[1].status).toBe("done");
        expect(r.kids[0].chores[0].status).toBe("idle"); // unticked duplicate untouched
    });
    it("createAll retries only failed rows", async () => {
        let n = 0;
        const post: Poster = async (path) => { n += 1; return path === "/api/rewards/" && n <= 3 ? { ok: false, detail: "nope" } : { ok: true, detail: null }; };
        const r = review();
        const first = await createAll(r, "en", post);
        expect(first).toEqual({ chores: 2, rewards: 0, gigs: 1 });
        expect(r.rewards[0]).toMatchObject({ status: "error", error: "nope" });
        const seen: string[] = [];
        const second = await createAll(r, "en", async (path) => { seen.push(path); return { ok: true, detail: null }; });
        expect(seen).toEqual(["/api/rewards/"]);
        expect(second).toEqual({ chores: 0, rewards: 1, gigs: 0 });
        expect(r.rewards[0]).toMatchObject({ status: "done", error: null });
    });
    it("a thrown post becomes the generic error and progress is reported", async () => {
        const r = review();
        const steps: Array<[number, number]> = [];
        await createAll(r, "es", async () => { throw new Error("net"); }, (i, t) => steps.push([i, t]));
        expect(steps).toEqual([[1, 4], [2, 4], [3, 4], [4, 4]]);
        expect(r.gigs[0].error).toBe(SETUP_COPY.createFailed.es);
    });
});

describe("jarvisPrefill", () => {
    it("names the kids, priorities and counts, within 2000 chars", () => {
        const s = jarvisPrefill(state(), { chores: 8, rewards: 4, gigs: 2 }, "en");
        for (const part of ["Sofía (6-8)", "Nuevo (13+)", "school", "8 chores", "4 rewards", "2 gigs"]) expect(s).toContain(part);
        expect(s).not.toContain("Skip");
        const long = state({ note: "x".repeat(5000) });
        expect(jarvisPrefill(long, { chores: 1, rewards: 1, gigs: 0 }, "es").length).toBeLessThanOrEqual(2000);
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$SP/e3jft.sh test/setup-wizard.test.ts`
Expected: FAIL — `Failed to resolve import "../src/lib/setupWizard"`.

- [ ] **Step 3: Write the lib**

`frontend/src/lib/setupWizard.ts`:

```ts
/** UX-E3 guided family setup — copy and the pure pieces of /parent/setup. */
import { errorDetail, fill, type PostResult } from "./chartScan";

export { errorDetail, fill, type PostResult };

export type Lang = "es" | "en";
export type Band = "3-5" | "6-8" | "9-12" | "13+";
export const BANDS: Band[] = ["3-5", "6-8", "9-12", "13+"];
export const PRIORITIES = ["routine", "school", "home", "kitchen", "pets", "self_care"] as const;
export const REWARD_STYLES = ["screen_time", "treats", "activities", "privileges", "toys"] as const;
/** Mirror of backend/app/core/modules.py TOGGLABLE_MODULES (parity test). */
export const TOGGLABLE_MODULES = ["meals", "shopping", "calendar", "pet", "chat", "budget", "gigs"] as const;

export const SETUP_COPY = {
    title: { es: "Configura tu familia", en: "Set up your family" },
    subtitle: { es: "Tres preguntas y te proponemos tareas, premios y chambitas", en: "Three questions and we propose chores, rewards and gigs" },
    stepKids: { es: "¿Quiénes son tus hijos?", en: "Who are your kids?" },
    stepKidsHint: { es: "Los que ya se unieron aparecen aquí. Agrega a los que faltan.", en: "Kids who already joined are listed. Add the ones who haven't." },
    kidName: { es: "Nombre", en: "Name" },
    kidBand: { es: "Edad", en: "Age" },
    addKid: { es: "+ Agregar hijo/a", en: "+ Add a kid" },
    removeKid: { es: "Quitar", en: "Remove" },
    skipKid: { es: "Incluir en esta configuración", en: "Include in this setup" },
    browsePacks: { es: "¿Prefieres ver paquetes listos?", en: "Prefer to browse ready-made packs?" },
    stepPriorities: { es: "¿Qué es lo más importante?", en: "What matters most?" },
    stepPrioritiesHint: { es: "Elige las que quieras (o ninguna).", en: "Pick any (or none)." },
    noteLabel: { es: "¿Algo más que debamos saber? (opcional)", en: "Anything else we should know? (optional)" },
    stepRewards: { es: "Premios y dinero", en: "Rewards & cash" },
    stepRewardsHint: { es: "¿Qué tipo de premios funcionan en tu casa?", en: "What kind of rewards work at home?" },
    wantsGigs: { es: "Un tablero de chambitas con dinero para trabajos extra", en: "A cash gig board for extra jobs" },
    back: { es: "Atrás", en: "Back" },
    next: { es: "Siguiente", en: "Next" },
    build: { es: "Armar mi plan", en: "Build my plan" },
    building: { es: "Armando el plan de tu familia…", en: "Building your family's plan…" },
    stepReview: { es: "Revisa y crea", en: "Review and create" },
    aiFailed: { es: "La IA no estuvo disponible; aquí tienes un set inicial según tus respuestas.", en: "AI was not available; here is a starter set for your answers." },
    joined: { es: "Ya usa la app", en: "Already uses the app" },
    notJoined: { es: "Aún no se ha unido", en: "Hasn't joined yet" },
    joinCodeHint: { es: "Comparte este código; {name} elige «Hijo/a» al registrarse.", en: "Share this code; {name} picks “Child” when signing up." },
    noJoinCode: { es: "Generar código", en: "Generate code" },
    rotationHint: { es: "Hasta que {name} se una, sus tareas van a la rotación compartida. Asígnalas desde Tareas cuando esté dentro.", en: "Until {name} joins, these chores go into the shared rotation. Assign them from Tasks once {name} is in." },
    createAccount: { es: "Crear su cuenta ahora", en: "Create the account now" },
    email: { es: "Correo", en: "Email" },
    password: { es: "Contraseña (mínimo 8)", en: "Password (8+ characters)" },
    createAccountBtn: { es: "Crear cuenta", en: "Create account" },
    accountCreated: { es: "Cuenta creada", en: "Account created" },
    accountFailed: { es: "No se pudo crear la cuenta.", en: "Could not create the account." },
    chores: { es: "Tareas", en: "Chores" },
    rewards: { es: "Premios", en: "Rewards" },
    gigs: { es: "Chambitas (dinero)", en: "Gigs (cash)" },
    points: { es: "puntos", en: "points" },
    pesos: { es: "$ MXN", en: "$ MXN" },
    bonus: { es: "Extra", en: "Bonus" },
    exists: { es: "Ya existe: {title}", en: "Already exists: {title}" },
    difficulty: { es: ["Fácil", "Media", "Difícil"], en: ["Easy", "Medium", "Hard"] },
    create: { es: "Crear {n}", en: "Create {n}" },
    creating: { es: "Creando {i} de {n}…", en: "Creating {i} of {n}…" },
    retry: { es: "Reintentar los fallidos", en: "Retry failed" },
    createFailed: { es: "No se pudo crear. Intenta de nuevo.", en: "Could not create. Try again." },
    draftFailed: { es: "No pudimos armar el plan. Intenta de nuevo.", en: "We couldn't build the plan. Try again." },
    done: { es: "Listo: {chores} tareas, {rewards} premios, {gigs} chambitas", en: "Done: {chores} chores, {rewards} rewards, {gigs} gigs" },
    refine: { es: "Afinar con Jarvis", en: "Refine with Jarvis" },
    goHub: { es: "Ir a mi inicio", en: "Go to my hub" },
    leaveTitle: { es: "¿Salir de la configuración?", en: "Leave setup?" },
    leaveBody: { es: "Lo que ya creaste se queda; las respuestas no se guardan.", en: "What you already created stays; your answers are not saved." },
    leaveConfirm: { es: "Salir", en: "Leave" },
} as const;

export const BAND_LABELS: Record<Band, { es: string; en: string }> = {
    "3-5": { es: "3 a 5", en: "3–5" }, "6-8": { es: "6 a 8", en: "6–8" }, "9-12": { es: "9 a 12", en: "9–12" }, "13+": { es: "13+", en: "13+" },
};
export const PRIORITY_LABELS: Record<(typeof PRIORITIES)[number], { es: string; en: string }> = {
    routine: { es: "Rutinas (mañana y noche)", en: "Routines (mornings & bedtime)" },
    school: { es: "Escuela (tarea y lectura)", en: "School (homework & reading)" },
    home: { es: "Casa (orden y limpieza)", en: "Home (tidying & cleaning)" },
    kitchen: { es: "Cocina (comida y mesa)", en: "Kitchen (meals & table)" },
    pets: { es: "Mascotas", en: "Pets" },
    self_care: { es: "Cuidado personal", en: "Self-care" },
};
export const REWARD_STYLE_LABELS: Record<(typeof REWARD_STYLES)[number], { es: string; en: string }> = {
    screen_time: { es: "Tiempo de pantalla", en: "Screen time" },
    treats: { es: "Antojos", en: "Treats" },
    activities: { es: "Actividades y salidas", en: "Activities & outings" },
    privileges: { es: "Privilegios", en: "Privileges" },
    toys: { es: "Juguetes y cositas", en: "Toys & small things" },
};

export type KidRow = { key: string; name: string; band: Band | null; memberId: string | null; locked: boolean; included: boolean };
export type WizardState = { kids: KidRow[]; priorities: string[]; note: string; rewardStyles: string[]; wantsGigs: boolean };

const str = (v: unknown) => (typeof v === "string" ? v : "");

export function bandForBirthdate(iso: string, today: Date): Band {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    if (!m) return "6-8";
    const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
    let age = today.getFullYear() - y;
    if (today.getMonth() + 1 < mo || (today.getMonth() + 1 === mo && today.getDate() < d)) age -= 1;
    if (age < 6) return "3-5";
    if (age <= 8) return "6-8";
    if (age <= 12) return "9-12";
    return "13+";
}

/** Active, approved CHILD/TEEN members → locked rows; band from a birthdate
 *  when the payload carries one (it does not today), else by role. */
export function kidRowsFromMembers(members: unknown, today: Date = new Date()): KidRow[] {
    if (!Array.isArray(members)) return [];
    const out: KidRow[] = [];
    for (const m of members as Array<Record<string, unknown>>) {
        if (!m || typeof m.id !== "string" || typeof m.name !== "string") continue;
        const role = String(m.role ?? "").toLowerCase();
        if (role !== "child" && role !== "teen") continue;
        if (m.is_active === false) continue;
        if (typeof m.approval_status === "string" && m.approval_status !== "approved") continue;
        const band: Band = typeof m.birthdate === "string" ? bandForBirthdate(m.birthdate, today) : role === "teen" ? "13+" : "6-8";
        out.push({ key: `m-${m.id}`, name: m.name, band, memberId: m.id, locked: true, included: true });
    }
    return out;
}

export function canAdvanceKids(state: WizardState): boolean {
    return state.kids.some((k) => k.included && k.name.trim().length > 0 && k.band !== null);
}

export function draftRequest(state: WizardState, lang: Lang) {
    return {
        kids: state.kids.filter((k) => k.included && k.name.trim() && k.band).map((k) => ({ name: k.name.trim(), age_band: k.band, member_id: k.memberId })),
        priorities: [...state.priorities],
        note: state.note.trim() || null,
        reward_styles: [...state.rewardStyles],
        wants_gigs: state.wantsGigs,
        lang,
    };
}

export type RowStatus = "idle" | "creating" | "done" | "error";
type RowBase = { key: string; title: string; duplicateOf: string | null; included: boolean; status: RowStatus; error: string | null };
export type ChoreRow = RowBase & { points: number; days: number[]; isBonus: boolean; description: string | null };
export type RewardRow = RowBase & { pointsCost: number; category: string; description: string | null };
export type GigRow = RowBase & { points: number; difficulty: number; category: string };
export type KidReview = { key: string; name: string; band: Band; memberId: string | null; chores: ChoreRow[] };
export type Review = { kids: KidReview[]; rewards: RewardRow[]; gigs: GigRow[] };

const base = (key: string, o: Record<string, unknown>): RowBase | null => {
    const title = str(o.title).trim();
    if (!title) return null;
    const duplicateOf = str(o.duplicate_of) || null;
    return { key, title, duplicateOf, included: !duplicateOf, status: "idle", error: null };
};
const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);

export function reviewRows(draft: unknown): Review {
    const d = (draft ?? {}) as Record<string, unknown>;
    const kids: KidReview[] = [];
    (Array.isArray(d.kids) ? d.kids : []).forEach((k: Record<string, unknown>, ki: number) => {
        if (!k || typeof k.name !== "string") return;
        const chores: ChoreRow[] = [];
        (Array.isArray(k.chores) ? k.chores : []).forEach((c: Record<string, unknown>, ci: number) => {
            const b = c && base(`k${ki}c${ci}`, c);
            if (!b) return;
            chores.push({ ...b, points: num(c.points, 10), isBonus: c.is_bonus === true,
                days: Array.isArray(c.days) ? c.days.filter((x): x is number => Number.isInteger(x) && x >= 0 && x <= 6) : [],
                description: str(c.description).trim() || null });
        });
        kids.push({ key: `k${ki}`, name: k.name, band: (BANDS.includes(k.age_band as Band) ? k.age_band : "6-8") as Band,
            memberId: typeof k.member_id === "string" ? k.member_id : null, chores });
    });
    const rewards: RewardRow[] = [];
    (Array.isArray(d.rewards) ? d.rewards : []).forEach((r: Record<string, unknown>, i: number) => {
        const b = r && base(`r${i}`, r);
        if (b) rewards.push({ ...b, pointsCost: num(r.points_cost, 50), category: str(r.category) || "privileges", description: str(r.description).trim() || null });
    });
    const gigs: GigRow[] = [];
    (Array.isArray(d.gigs) ? d.gigs : []).forEach((g: Record<string, unknown>, i: number) => {
        const b = g && base(`g${i}`, g);
        if (b) gigs.push({ ...b, points: num(g.points, 20), difficulty: Math.min(3, Math.max(1, num(g.difficulty, 1))), category: str(g.category) || "other" });
    });
    return { kids, rewards, gigs };
}

/** POST /api/task-templates/ — FIXED to the kid when bound, AUTO (shared rotation) otherwise. */
export function choreBody(row: ChoreRow, memberId: string | null, lang: Lang) {
    const title = row.title.trim();
    const description = row.description && row.description.trim() ? row.description.trim() : null;
    const body: Record<string, unknown> = {
        title,
        points: Math.max(0, Math.min(1000, Math.round(Number(row.points) || 0))),
        is_bonus: row.isBonus,
        days_of_week: row.days.length ? [...row.days].sort((a, b) => a - b) : null,
        interval_days: 1,
        assignment_type: memberId ? "fixed" : "auto",
        assigned_user_ids: memberId ? [memberId] : null,
        description,
    };
    if (lang === "es") { body.title_es = title; body.description_es = description; }
    return body;
}

export function rewardBody(row: RewardRow) {
    return { title: row.title.trim(), points_cost: Math.max(1, Math.min(10000, Math.round(Number(row.pointsCost) || 1))), category: row.category, description: row.description };
}

export function gigBody(row: GigRow) {
    return { title: row.title.trim(), points: Math.max(1, Math.round(Number(row.points) || 1)), difficulty: row.difficulty, category: row.category };
}

export function registerBody(kid: { name: string; band: Band | null }, email: string, password: string) {
    return { name: kid.name.trim(), email: email.trim(), password, role: kid.band === "13+" ? "teen" : "child" };
}

export function modulesBodyWithoutGigs(current: unknown) {
    const list = Array.isArray(current) ? current.filter((m): m is string => typeof m === "string") : [...TOGGLABLE_MODULES];
    return { enabled_modules: list.filter((m) => m !== "gigs") };
}

export type Poster = (path: string, body: Record<string, unknown>) => Promise<PostResult>;
export type Counts = { chores: number; rewards: number; gigs: number };

/** One ordinary create per ticked row, chores → rewards → gigs. A failed row
 *  keeps `error`/`status = "error"` and is re-posted next time; a done row is
 *  never posted again. */
export async function createAll(review: Review, lang: Lang, post: Poster, onProgress?: (i: number, n: number) => void): Promise<Counts> {
    type Job = { row: RowBase; path: string; body: Record<string, unknown>; kind: keyof Counts };
    const jobs: Job[] = [];
    for (const kid of review.kids) for (const c of kid.chores) if (c.included && c.status !== "done") jobs.push({ row: c, path: "/api/task-templates/", body: choreBody(c, kid.memberId, lang), kind: "chores" });
    for (const r of review.rewards) if (r.included && r.status !== "done") jobs.push({ row: r, path: "/api/rewards/", body: rewardBody(r), kind: "rewards" });
    for (const g of review.gigs) if (g.included && g.status !== "done") jobs.push({ row: g, path: "/api/gigs/offerings", body: gigBody(g), kind: "gigs" });
    const counts: Counts = { chores: 0, rewards: 0, gigs: 0 };
    for (let i = 0; i < jobs.length; i++) {
        const job = jobs[i];
        onProgress?.(i + 1, jobs.length);
        job.row.status = "creating";
        try {
            const result = await post(job.path, job.body);
            if (result.ok) { job.row.status = "done"; job.row.error = null; counts[job.kind] += 1; }
            else { job.row.status = "error"; job.row.error = result.detail || SETUP_COPY.createFailed[lang]; }
        } catch {
            job.row.status = "error"; job.row.error = SETUP_COPY.createFailed[lang];
        }
    }
    return counts;
}

export function jarvisPrefill(state: WizardState, counts: Counts, lang: Lang): string {
    const kids = state.kids.filter((k) => k.included && k.name.trim()).map((k) => `${k.name.trim()} (${k.band ?? "?"})`).join(", ");
    const prio = state.priorities.join(", ") || (lang === "es" ? "sin prioridades" : "no priorities");
    const note = state.note.trim();
    const text = lang === "es"
        ? `Acabo de configurar mi familia con el asistente: ${kids}. Prioridades: ${prio}. Creé ${counts.chores} tareas, ${counts.rewards} premios y ${counts.gigs} chambitas.${note ? ` Nota: ${note}.` : ""} Ayúdame a ajustarlas — por ejemplo, revisa que los puntos sean parejos entre hermanos.`
        : `I just set up my family with the wizard: ${kids}. Priorities: ${prio}. I created ${counts.chores} chores, ${counts.rewards} rewards and ${counts.gigs} gigs.${note ? ` Note: ${note}.` : ""} Help me adjust them — for example, check the points are fair between siblings.`;
    return text.slice(0, 2000);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$SP/e3jft.sh test/setup-wizard.test.ts`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/setupWizard.ts frontend/test/setup-wizard.test.ts
git commit -m "feat(ux-e3): setup wizard lib — copy, rows, bodies, createAll, Jarvis prefill

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The page `/parent/setup` + proxy route

**Files:**
- Create: `frontend/src/pages/api/families/onboarding/setup-draft.ts`
- Create: `frontend/src/pages/parent/setup.astro`
- Modify: `frontend/test/section-tones.test.ts` (add the page)
- Test: `frontend/test/setup-page.test.ts`

**Interfaces:**
- Consumes: Task 6 lib; `lib/dialogs.confirmSheet({title, body, confirmLabel, danger})`; `lib/toast.showToast(msg, type)`; `lib/buttonClasses.buttonClass(variant, size)`; `components/ui/PageLayout.astro` (`title, tone, backHref, backLabel, role, active, lang, mainClass`, slot `header-extra`).
- Produces: the page; the POST-only proxy.

- [ ] **Step 1: Write the failing test**

```ts
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");

describe("/parent/setup page", () => {
    const page = read("../src/pages/parent/setup.astro");
    it("is parent-only, sky tone, and seeds the wizard from the family", () => {
        expect(page).toMatch(/if \(user\.role !== "parent"\) return Astro\.redirect\("\/dashboard"\);/);
        expect(page).toMatch(/tone="sky"/);
        expect(page).toMatch(/const kidRows = kidRowsFromMembers\(family\?\.members/);
        expect(page).toMatch(/data-kids=\{JSON\.stringify\(kidRows\)\}/);
        expect(page).toMatch(/data-join-code=/);
        expect(page).toMatch(/data-modules=\{JSON\.stringify\(family\?\.enabled_modules ?? null\)\}/);
    });
    it("has four steps and copy from the lib only", () => {
        for (const s of ["1", "2", "3", "4"]) expect(page).toContain(`data-step="${s}"`);
        expect(page).toContain("SETUP_COPY");
        expect(page).not.toMatch(/lang === "es" \? "/);  // no inline copy on this page
    });
    it("drafts through the proxied route and creates through the shared loop", () => {
        expect(page).toMatch(/fetch\("\/api\/families\/onboarding\/setup-draft"/);
        expect(page).toMatch(/await createAll\(review, lang, post, \(i, n\) =>/);
        expect(page).toMatch(/registerBody\(/);
        expect(page).toMatch(/fetch\("\/api\/auth\/register"/);
        expect(page).toMatch(/modulesBodyWithoutGigs\(/);
        expect(page).toMatch(/fetch\("\/api\/families\/me", \{\s*method: "PATCH"/);
        expect(page).toMatch(/jarvisPrefill\(/);
        expect(page).toMatch(/\/parent\/jarvis\?q=/);
        expect(page).toMatch(/if \(row\.error\) \{[\s\S]*?err\.textContent = row\.error;/);
        expect(existsSync(path("../src/pages/api/families/onboarding/setup-draft.ts"))).toBe(true);
        expect(existsSync(path("../src/pages/api/auth/register.ts"))).toBe(true);
        expect(existsSync(path("../src/pages/api/gigs/[...path].ts"))).toBe(true);
        expect(existsSync(path("../src/pages/api/rewards/[...path].ts"))).toBe(true);
    });
    it("asks before leaving the review through a sheet, never a native dialog", () => {
        expect(page).toMatch(/confirmSheet\(/);
        expect(page).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(page).not.toMatch(/innerHTML/);
        expect(page).not.toMatch(/<h1[^>]*>[^<]*[\u{1F300}-\u{1FAFF}]/u);
        expect(page).toContain("browsePacks");
        expect(page).toMatch(/href="\/parent\/starter-packs"/);
    });
    it("proxy is POST-only and forwards the cookie token", () => {
        const proxy = read("../src/pages/api/families/onboarding/setup-draft.ts");
        expect(proxy).toMatch(/export const POST: APIRoute/);
        expect(proxy).not.toMatch(/export const (GET|PUT|DELETE|PATCH)/);
        expect(proxy).toMatch(/\/api\/families\/onboarding\/setup-draft`/);
        expect(proxy).toMatch(/Authorization: `Bearer \$\{token\}`/);
    });
});
```

Also add `"pages/parent/setup.astro": "sky",` to `PAGE_LAYOUT_TONES` in `frontend/test/section-tones.test.ts` (after `"pages/parent/tasks/[id]/edit.astro": "sky",`).

- [ ] **Step 2: Run test to verify it fails**

Run: `$SP/e3jft.sh test/setup-page.test.ts test/section-tones.test.ts`
Expected: FAIL — `ENOENT ... setup.astro`.

- [ ] **Step 3: Write the proxy**

`frontend/src/pages/api/families/onboarding/setup-draft.ts`:

```ts
import type { APIRoute } from "astro";

const API = () =>
    process.env.API_BASE_URL ||
    process.env.PUBLIC_API_BASE_URL ||
    "http://backend:8000";

function unauthorized() {
    return new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
    });
}

/** UX-E3: the wizard's answers → a draft. POST only; nothing is stored upstream. */
export const POST: APIRoute = async ({ cookies, request }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    try {
        const body = await request.text();
        const r = await fetch(`${API()}/api/families/onboarding/setup-draft`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body,
        });
        return new Response(await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("onboarding/setup-draft POST error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
```

- [ ] **Step 4: Write the page**

`frontend/src/pages/parent/setup.astro`:

```astro
---
import PageLayout from "@components/ui/PageLayout.astro";
import { apiFetch } from "../../lib/api";
import { SETUP_COPY, kidRowsFromMembers } from "../../lib/setupWizard";
import { buttonClass } from "../../lib/buttonClasses";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = (Astro.cookies.get("lang")?.value ?? "es") as "en" | "es";
const { data: user } = await apiFetch<any>("/api/auth/me", { token });
if (!user) {
    Astro.cookies.delete("access_token", { path: "/" });
    return Astro.redirect("/login");
}
if (user.role !== "parent") return Astro.redirect("/dashboard");

const [{ data: family }, { data: codeData }] = await Promise.all([
    apiFetch<any>("/api/families/me", { token }),
    apiFetch<any>("/api/families/join-code/current", { token }),
]);
// Kids who already joined start as locked rows; the parent adds the rest.
const kidRows = kidRowsFromMembers(family?.members ?? []);
const joinCode: string | null = codeData?.join_code ?? null;
const c = SETUP_COPY;
---

<PageLayout
    title={c.title[lang]}
    tone="sky"
    backHref="/parent"
    backLabel={c.goHub[lang]}
    role={user.role}
    active="parent"
    lang={lang}
    mainClass="flex-1 px-4 py-6 space-y-4"
>
    <p slot="header-extra" class="text-brand-ink text-sm mt-1">{c.subtitle[lang]}</p>

    <div id="setup-root" data-lang={lang} data-kids={JSON.stringify(kidRows)} data-join-code={joinCode ?? ""}
         data-modules={JSON.stringify(family?.enabled_modules ?? null)}>
        <ol id="progress" class="flex items-center justify-center gap-2 mb-4" aria-label="progress">
            {[1, 2, 3, 4].map((n) => (
                <li data-dot={n} class="h-2.5 w-2.5 rounded-full bg-brand-ink/20"></li>
            ))}
        </ol>

        <section data-step="1" class="space-y-3">
            <h2 class="font-bold text-brand-ink text-lg">{c.stepKids[lang]}</h2>
            <p class="text-sm text-brand-ink-soft">{c.stepKidsHint[lang]}</p>
            <div id="kid-rows" class="space-y-2"></div>
            <button type="button" id="add-kid" class={buttonClass("secondary", "sm")}>{c.addKid[lang]}</button>
            <p class="text-xs text-brand-ink-soft pt-2">
                <a href="/parent/starter-packs" class="font-semibold text-brand-sky-text hover:underline">{c.browsePacks[lang]}</a>
            </p>
        </section>

        <section data-step="2" hidden class="space-y-3">
            <h2 class="font-bold text-brand-ink text-lg">{c.stepPriorities[lang]}</h2>
            <p class="text-sm text-brand-ink-soft">{c.stepPrioritiesHint[lang]}</p>
            <div id="priority-chips" class="flex flex-wrap gap-2"></div>
            <label class="block text-sm text-brand-ink">
                <span class="font-semibold">{c.noteLabel[lang]}</span>
                <textarea id="note" maxlength="300" rows="2" class="mt-1 w-full px-3 py-2 rounded-xl border border-brand-ink/20 bg-white text-sm text-brand-ink"></textarea>
            </label>
        </section>

        <section data-step="3" hidden class="space-y-3">
            <h2 class="font-bold text-brand-ink text-lg">{c.stepRewards[lang]}</h2>
            <p class="text-sm text-brand-ink-soft">{c.stepRewardsHint[lang]}</p>
            <div id="style-chips" class="flex flex-wrap gap-2"></div>
            <label class="flex items-center gap-3 bg-brand-cream rounded-2xl p-4 border border-brand-ink/10">
                <input type="checkbox" id="wants-gigs" checked class="h-5 w-5 rounded" />
                <span class="text-sm font-semibold text-brand-ink">{c.wantsGigs[lang]}</span>
            </label>
        </section>

        <section data-step="4" hidden class="space-y-4">
            <h2 class="font-bold text-brand-ink text-lg">{c.stepReview[lang]}</h2>
            <div id="building" hidden class="bg-brand-cream rounded-2xl p-6 text-center border border-brand-ink/10">
                <div class="inline-block animate-spin h-8 w-8 border-4 border-brand-ink/20 border-t-brand-ink rounded-full"></div>
                <p class="mt-3 text-sm text-brand-ink-soft">{c.building[lang]}</p>
            </div>
            <p id="ai-failed" hidden class="p-3 bg-brand-sun/20 border border-brand-sun text-brand-ink text-sm rounded-xl">{c.aiFailed[lang]}</p>
            <div id="review-kids" class="space-y-4"></div>
            <div id="review-rewards" class="space-y-2"></div>
            <div id="review-gigs" class="space-y-2"></div>
            <button type="button" id="create-btn" class={`w-full ${buttonClass("primary", "md")}`}></button>
            <div id="done-box" hidden class="p-4 bg-brand-mint/20 border border-brand-mint rounded-2xl space-y-3">
                <p id="done-text" class="text-sm font-semibold text-brand-mint-text"></p>
                <div class="flex flex-wrap gap-2">
                    <a id="refine-link" hidden class={buttonClass("secondary", "sm")}>{c.refine[lang]}</a>
                    <a href="/parent" class={buttonClass("primary", "sm")}>{c.goHub[lang]}</a>
                </div>
            </div>
        </section>

        <div id="nav" class="flex items-center justify-between gap-3 pt-4 pb-safe">
            <button type="button" id="back-btn" class={buttonClass("secondary", "md")}>{c.back[lang]}</button>
            <button type="button" id="next-btn" class={buttonClass("primary", "md")}>{c.next[lang]}</button>
        </div>
    </div>
</PageLayout>

<script>
    import {
        BANDS, BAND_LABELS, PRIORITIES, PRIORITY_LABELS, REWARD_STYLES, REWARD_STYLE_LABELS, SETUP_COPY,
        canAdvanceKids, createAll, draftRequest, errorDetail, fill, jarvisPrefill, modulesBodyWithoutGigs,
        registerBody, reviewRows, type Band, type Counts, type KidRow, type Poster, type Review, type WizardState,
    } from "../../lib/setupWizard";
    import { confirmSheet } from "../../lib/dialogs";
    import { showToast } from "../../lib/toast";
    import { buttonClass } from "../../lib/buttonClasses";

    const root = document.getElementById("setup-root");
    if (root) {
        const lang = root.dataset.lang === "en" ? "en" : "es";
        const c = SETUP_COPY;
        const parse = <T,>(s: string | undefined, d: T): T => { try { return s ? JSON.parse(s) : d; } catch { return d; } };
        const state: WizardState = { kids: parse<KidRow[]>(root.dataset.kids, []), priorities: [], note: "", rewardStyles: [], wantsGigs: true };
        let joinCode = root.dataset.joinCode || "";
        const modules = parse<string[] | null>(root.dataset.modules, null);
        let review: Review = { kids: [], rewards: [], gigs: [] };
        let aiAvailable = false;
        let step = 1;
        let seq = 0;
        const total: Counts = { chores: 0, rewards: 0, gigs: 0 };

        const $ = (id: string) => document.getElementById(id)!;
        const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text = "") => {
            const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n;
        };
        const backBtn = $("back-btn") as HTMLButtonElement, nextBtn = $("next-btn") as HTMLButtonElement, createBtn = $("create-btn") as HTMLButtonElement;
        const chipClass = (on: boolean) => `px-3 py-1.5 rounded-full text-sm font-semibold border ${on ? "bg-brand-sky text-brand-ink border-brand-ink" : "bg-white text-brand-ink border-brand-ink/20"}`;
        const inputClass = "px-2 py-1.5 rounded-lg border border-brand-ink/20 bg-white text-sm text-brand-ink";

        // ── Step 1: kids ────────────────────────────────────────────────
        const kidRowsEl = $("kid-rows");
        const renderKids = () => {
            kidRowsEl.replaceChildren();
            for (const kid of state.kids) {
                const card = el("div", "bg-brand-cream rounded-2xl p-3 border border-brand-ink/10 space-y-2");
                const top = el("div", "flex items-center gap-2");
                const include = el("input") as HTMLInputElement; include.type = "checkbox"; include.checked = kid.included; include.className = "h-5 w-5 rounded";
                include.setAttribute("aria-label", c.skipKid[lang]);
                include.addEventListener("change", () => { kid.included = include.checked; syncNav(); });
                const name = el("input") as HTMLInputElement; name.type = "text"; name.value = kid.name; name.maxLength = 60; name.placeholder = c.kidName[lang];
                name.className = `flex-1 ${inputClass}`; name.disabled = kid.locked; name.setAttribute("aria-label", c.kidName[lang]);
                name.addEventListener("input", () => { kid.name = name.value; syncNav(); });
                top.append(include, name);
                if (!kid.locked) {
                    const rm = el("button", "text-xs font-semibold text-brand-coral-text", c.removeKid[lang]) as HTMLButtonElement; rm.type = "button";
                    rm.addEventListener("click", () => { state.kids = state.kids.filter((k) => k !== kid); renderKids(); });
                    top.append(rm);
                }
                card.append(top);
                const bands = el("div", "flex flex-wrap gap-1 items-center");
                bands.append(el("span", "text-xs text-brand-ink-soft mr-1", c.kidBand[lang]));
                for (const b of BANDS) {
                    const btn = el("button", chipClass(kid.band === b), BAND_LABELS[b][lang]) as HTMLButtonElement; btn.type = "button";
                    btn.setAttribute("aria-pressed", String(kid.band === b));
                    btn.addEventListener("click", () => { kid.band = b; renderKids(); });
                    bands.append(btn);
                }
                card.append(bands);
                kidRowsEl.append(card);
            }
            syncNav();
        };
        $("add-kid").addEventListener("click", () => {
            if (state.kids.length >= 10) return;
            state.kids.push({ key: `n-${Date.now()}`, name: "", band: null, memberId: null, locked: false, included: true });
            renderKids();
            (kidRowsEl.lastElementChild?.querySelector("input[type=text]") as HTMLInputElement | null)?.focus();
        });
        if (state.kids.length === 0) state.kids.push({ key: "n-0", name: "", band: null, memberId: null, locked: false, included: true });

        // ── Steps 2–3: chips ────────────────────────────────────────────
        const chips = (host: HTMLElement, ids: readonly string[], labels: Record<string, { es: string; en: string }>, list: string[]) => {
            host.replaceChildren();
            for (const id of ids) {
                const on = list.includes(id);
                const b = el("button", chipClass(on), labels[id][lang]) as HTMLButtonElement; b.type = "button"; b.setAttribute("aria-pressed", String(on));
                b.addEventListener("click", () => {
                    const i = list.indexOf(id); if (i >= 0) list.splice(i, 1); else list.push(id);
                    chips(host, ids, labels, list);
                });
                host.append(b);
            }
        };
        chips($("priority-chips"), PRIORITIES, PRIORITY_LABELS, state.priorities);
        chips($("style-chips"), REWARD_STYLES, REWARD_STYLE_LABELS, state.rewardStyles);
        ($("note") as HTMLTextAreaElement).addEventListener("input", (e) => { state.note = (e.target as HTMLTextAreaElement).value; });
        ($("wants-gigs") as HTMLInputElement).addEventListener("change", (e) => { state.wantsGigs = (e.target as HTMLInputElement).checked; });

        // ── Navigation ──────────────────────────────────────────────────
        const show = (n: number) => {
            step = n;
            document.querySelectorAll<HTMLElement>("[data-step]").forEach((s) => s.toggleAttribute("hidden", s.dataset.step !== String(n)));
            document.querySelectorAll<HTMLElement>("[data-dot]").forEach((d) => {
                const on = Number(d.dataset.dot) <= n;
                d.className = `h-2.5 w-2.5 rounded-full ${on ? "bg-brand-ink" : "bg-brand-ink/20"}`;
                if (Number(d.dataset.dot) === n) d.setAttribute("aria-current", "step"); else d.removeAttribute("aria-current");
            });
            $("nav").toggleAttribute("hidden", n === 4);
            nextBtn.textContent = n === 3 ? c.build[lang] : c.next[lang];
            backBtn.toggleAttribute("hidden", n === 1);
            syncNav();
            window.scrollTo({ top: 0 });
        };
        const syncNav = () => { nextBtn.disabled = step === 1 && !canAdvanceKids(state); };
        backBtn.addEventListener("click", () => show(Math.max(1, step - 1)));
        nextBtn.addEventListener("click", async () => {
            if (step < 3) { show(step + 1); return; }
            await buildDraft();
        });

        // ── Draft ───────────────────────────────────────────────────────
        const buildDraft = async () => {
            const mine = ++seq;
            nextBtn.disabled = true;
            show(4);
            $("building").removeAttribute("hidden");
            $("ai-failed").setAttribute("hidden", "");
            try {
                const r = await fetch("/api/families/onboarding/setup-draft", {
                    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(draftRequest(state, lang)),
                });
                if (mine !== seq) return;
                if (!r.ok) throw new Error(String(r.status));
                const data = await r.json();
                aiAvailable = data?.ai_available === true;
                if (data?.ai_failed === true) $("ai-failed").removeAttribute("hidden");
                review = reviewRows(data);
                renderReview();
            } catch {
                if (mine !== seq) return;
                showToast(c.draftFailed[lang], "error");
                show(3);
            } finally {
                if (mine === seq) { $("building").setAttribute("hidden", ""); nextBtn.disabled = false; }
            }
        };

        // ── Review ──────────────────────────────────────────────────────
        const rowError = (row: { error: string | null }) => {
            const err = el("p", "text-xs text-red-700"); err.setAttribute("data-row-error", "");
            if (row.error) {
                err.textContent = row.error;
            } else {
                err.setAttribute("hidden", "");
            }
            return err;
        };
        const tick = (row: { included: boolean; status: string }) => {
            const check = el("input") as HTMLInputElement; check.type = "checkbox"; check.checked = row.included; check.className = "mt-2 h-5 w-5 rounded";
            check.disabled = row.status === "done";
            check.addEventListener("change", () => { row.included = check.checked; syncCreate(); });
            return check;
        };
        const titleInput = (row: { title: string; status: string }) => {
            const t = el("input") as HTMLInputElement; t.type = "text"; t.value = row.title; t.maxLength = 200; t.className = `flex-1 ${inputClass}`; t.disabled = row.status === "done";
            t.addEventListener("input", () => { row.title = t.value; });
            return t;
        };
        const numInput = (get: () => number, set: (v: number) => void, min: number, max: number, done: boolean) => {
            const n = el("input") as HTMLInputElement; n.type = "number"; n.min = String(min); n.max = String(max); n.value = String(get()); n.className = `w-20 ${inputClass}`; n.disabled = done;
            n.addEventListener("input", () => set(Number(n.value)));
            return n;
        };
        const doneClass = (status: string) => status === "done" ? " opacity-60" : "";

        const renderReview = () => {
            const kidsEl = $("review-kids"), rewardsEl = $("review-rewards"), gigsEl = $("review-gigs");
            kidsEl.replaceChildren(); rewardsEl.replaceChildren(); gigsEl.replaceChildren();
            for (const kid of review.kids) {
                const card = el("section", "bg-brand-cream rounded-2xl p-4 border border-brand-ink/10 shadow-[var(--shadow-card)] space-y-3");
                card.dataset.kidKey = kid.key;
                const head = el("div", "flex items-center justify-between gap-2");
                head.append(el("h3", "font-bold text-brand-ink", `${kid.name} · ${BAND_LABELS[kid.band][lang]}`));
                head.append(el("span", "text-xs font-semibold " + (kid.memberId ? "text-brand-mint-text" : "text-brand-coral-text"), kid.memberId ? c.joined[lang] : c.notJoined[lang]));
                card.append(head);
                if (!kid.memberId) card.append(unjoinedBlock(kid));
                for (const row of kid.chores) {
                    const line = el("div", "space-y-1 pt-2 border-t border-brand-ink/10" + doneClass(row.status));
                    const top = el("div", "flex items-start gap-2"); top.append(tick(row), titleInput(row)); line.append(top);
                    const meta = el("div", "flex flex-wrap items-center gap-2 text-xs text-brand-ink");
                    meta.append(numInput(() => row.points, (v) => { row.points = v; }, 0, 1000, row.status === "done"), el("span", "", c.points[lang]));
                    if (row.isBonus) meta.append(el("span", "px-2 py-0.5 rounded-full bg-brand-sun/30 font-semibold", c.bonus[lang]));
                    line.append(meta);
                    const days = el("div", "flex gap-1");
                    (lang === "es" ? ["L", "M", "X", "J", "V", "S", "D"] : ["M", "T", "W", "T", "F", "S", "S"]).forEach((label, d) => {
                        const b = el("button", "", label) as HTMLButtonElement; b.type = "button"; b.disabled = row.status === "done";
                        const paint = () => { b.className = `h-7 w-7 rounded-full text-xs font-bold border ${row.days.includes(d) ? "bg-brand-sky text-brand-ink border-brand-ink" : "bg-white text-brand-ink border-brand-ink/20"}`; };
                        b.addEventListener("click", () => { row.days = row.days.includes(d) ? row.days.filter((x) => x !== d) : [...row.days, d]; paint(); });
                        paint(); days.append(b);
                    });
                    line.append(days);
                    if (row.duplicateOf) line.append(el("p", "text-xs font-bold text-brand-coral-text", fill(c.exists[lang], { title: row.duplicateOf })));
                    line.append(rowError(row));
                    card.append(line);
                }
                kidsEl.append(card);
            }
            if (review.rewards.length) {
                rewardsEl.append(el("h3", "font-bold text-brand-ink px-1", c.rewards[lang]));
                for (const row of review.rewards) {
                    const line = el("div", "bg-brand-cream rounded-2xl p-3 border border-brand-ink/10 space-y-1" + doneClass(row.status));
                    const top = el("div", "flex items-start gap-2"); top.append(tick(row), titleInput(row)); line.append(top);
                    const meta = el("div", "flex items-center gap-2 text-xs text-brand-ink");
                    meta.append(numInput(() => row.pointsCost, (v) => { row.pointsCost = v; }, 1, 10000, row.status === "done"), el("span", "", c.points[lang]), el("span", "text-brand-ink-soft", REWARD_STYLE_LABELS[row.category as keyof typeof REWARD_STYLE_LABELS]?.[lang] ?? row.category));
                    line.append(meta);
                    if (row.duplicateOf) line.append(el("p", "text-xs font-bold text-brand-coral-text", fill(c.exists[lang], { title: row.duplicateOf })));
                    line.append(rowError(row));
                    rewardsEl.append(line);
                }
            }
            if (review.gigs.length) {
                gigsEl.append(el("h3", "font-bold text-brand-ink px-1", c.gigs[lang]));
                for (const row of review.gigs) {
                    const line = el("div", "bg-brand-cream rounded-2xl p-3 border border-brand-ink/10 space-y-1" + doneClass(row.status));
                    const top = el("div", "flex items-start gap-2"); top.append(tick(row), titleInput(row)); line.append(top);
                    const meta = el("div", "flex items-center gap-2 text-xs text-brand-ink");
                    meta.append(numInput(() => row.points, (v) => { row.points = v; }, 1, 10000, row.status === "done"), el("span", "", c.pesos[lang]), el("span", "text-brand-ink-soft", c.difficulty[lang][row.difficulty - 1] ?? ""));
                    line.append(meta);
                    if (row.duplicateOf) line.append(el("p", "text-xs font-bold text-brand-coral-text", fill(c.exists[lang], { title: row.duplicateOf })));
                    line.append(rowError(row));
                    gigsEl.append(line);
                }
            }
            syncCreate();
        };

        // Join code + optional account creation for a kid who has not joined.
        const unjoinedBlock = (kid: Review["kids"][number]) => {
            const box = el("div", "rounded-xl bg-white border border-brand-ink/10 p-3 space-y-2 text-sm text-brand-ink");
            const codeLine = el("div", "flex items-center gap-2 flex-wrap");
            const codeText = el("span", "", fill(c.joinCodeHint[lang], { name: kid.name }));
            const code = el("span", "font-mono text-lg font-bold tracking-[0.2em] text-brand-coral-text", joinCode);
            codeLine.append(codeText, code);
            if (!joinCode) {
                const gen = el("button", buttonClass("secondary", "sm"), c.noJoinCode[lang]) as HTMLButtonElement; gen.type = "button";
                gen.addEventListener("click", async () => {
                    gen.disabled = true;
                    try {
                        const r = await fetch("/api/families/join-code/generate", { method: "POST", credentials: "same-origin" });
                        const d = r.ok ? await r.json() : null;
                        if (d?.join_code) { joinCode = d.join_code; renderReview(); } else { gen.disabled = false; }
                    } catch { gen.disabled = false; }
                });
                codeLine.append(gen);
            }
            box.append(codeLine);
            box.append(el("p", "text-xs text-brand-ink-soft", fill(c.rotationHint[lang], { name: kid.name })));
            const details = el("details"); details.append(el("summary", "cursor-pointer text-xs font-semibold text-brand-sky-text", c.createAccount[lang]));
            const form = el("form", "mt-2 space-y-2");
            const email = el("input") as HTMLInputElement; email.type = "email"; email.required = true; email.placeholder = c.email[lang]; email.className = `w-full ${inputClass}`; email.setAttribute("aria-label", c.email[lang]);
            const pw = el("input") as HTMLInputElement; pw.type = "password"; pw.required = true; pw.minLength = 8; pw.placeholder = c.password[lang]; pw.className = `w-full ${inputClass}`; pw.setAttribute("aria-label", c.password[lang]);
            const submit = el("button", buttonClass("primary", "sm"), c.createAccountBtn[lang]) as HTMLButtonElement; submit.type = "submit";
            const err = el("p", "text-xs text-red-700"); err.setAttribute("hidden", "");
            form.append(email, pw, submit, err);
            form.addEventListener("submit", async (e) => {
                e.preventDefault();
                submit.disabled = true; err.setAttribute("hidden", "");
                try {
                    const r = await fetch("/api/auth/register", {
                        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(registerBody({ name: kid.name, band: kid.band }, email.value, pw.value)),
                    });
                    const d = await r.json().catch(() => null);
                    if (r.ok && d?.id) {
                        kid.memberId = String(d.id);
                        showToast(c.accountCreated[lang], "success");
                        renderReview();
                    } else {
                        err.textContent = errorDetail(d, c.accountFailed[lang]); err.removeAttribute("hidden"); submit.disabled = false;
                    }
                } catch {
                    err.textContent = c.accountFailed[lang]; err.removeAttribute("hidden"); submit.disabled = false;
                }
            });
            details.append(form);
            box.append(details);
            return box;
        };

        const pending = () => {
            let n = 0;
            for (const k of review.kids) for (const r of k.chores) if (r.included && r.status !== "done") n += 1;
            for (const r of review.rewards) if (r.included && r.status !== "done") n += 1;
            for (const r of review.gigs) if (r.included && r.status !== "done") n += 1;
            return n;
        };
        const anyError = () => [...review.kids.flatMap((k) => k.chores), ...review.rewards, ...review.gigs].some((r) => r.status === "error");
        const syncCreate = () => {
            const n = pending();
            createBtn.textContent = anyError() ? c.retry[lang] : fill(c.create[lang], { n });
            createBtn.disabled = n === 0;
        };

        const post: Poster = async (path, body) => {
            const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
            if (r.ok) return { ok: true, detail: null };
            const parsed = await r.json().catch(() => null);
            return { ok: false, detail: errorDetail(parsed, c.createFailed[lang]) };
        };

        createBtn.addEventListener("click", async () => {
            createBtn.disabled = true;
            const counts = await createAll(review, lang, post, (i, n) => { createBtn.textContent = fill(c.creating[lang], { i, n }); });
            total.chores += counts.chores; total.rewards += counts.rewards; total.gigs += counts.gigs;
            if (!state.wantsGigs) {
                try {
                    await fetch("/api/families/me", { method: "PATCH", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(modulesBodyWithoutGigs(modules)) });
                } catch { /* best effort — the gig board is UX-only gating */ }
            }
            renderReview();
            const done = $("done-box"), text = $("done-text"), refine = $("refine-link") as HTMLAnchorElement;
            text.textContent = fill(c.done[lang], total);
            refine.href = `/parent/jarvis?q=${encodeURIComponent(jarvisPrefill(state, total, lang))}`;
            refine.toggleAttribute("hidden", !aiAvailable);
            done.removeAttribute("hidden");
            if (counts.chores + counts.rewards + counts.gigs > 0) showToast(fill(c.done[lang], counts), "success");
        });

        // Leaving the review after something was created: a sheet, never a native confirm.
        document.querySelectorAll<HTMLAnchorElement>('a[href="/parent"]').forEach((a) => a.addEventListener("click", async (e) => {
            if (step !== 4 || total.chores + total.rewards + total.gigs === 0) return;
            e.preventDefault();
            if (await confirmSheet({ title: c.leaveTitle[lang], body: c.leaveBody[lang], confirmLabel: c.leaveConfirm[lang] })) window.location.href = "/parent";
        }));

        renderKids();
        show(1);
    }
</script>
```

- [ ] **Step 5: Run the tests, then the whole frontend suite + build**

Run: `$SP/e3jft.sh test/setup-page.test.ts test/section-tones.test.ts test/no-native-dialogs.test.ts test/visual-consistency.test.ts`
Expected: PASS. If `visual-consistency` flags a class (e.g. `text-red-700` is allowed on E1's page — check its exemption list and mirror E1's choices), fix the page, not the guard.

Run: `cd frontend && npx astro check 2>&1 | tail -5 && npx astro build 2>&1 | tail -3`
Expected: 0 errors, build OK. (Two things that bit E1/D4b: an unescaped `\"` inside a JS string in `.astro`, and the `<T,>` generic in a `.astro` script — if `astro check` complains about `parse<T,>`, write it as a plain `function parse<T>(…)`.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/parent/setup.astro frontend/src/pages/api/families/onboarding/setup-draft.ts frontend/test/setup-page.test.ts frontend/test/section-tones.test.ts
git commit -m "feat(ux-e3): /parent/setup wizard page + setup-draft proxy

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Hub entry — `SetupCard` link

**Files:**
- Modify: `frontend/src/components/home/SetupCard.astro` (the `/parent/starter-packs` anchor)
- Test: `frontend/test/setup-page.test.ts` (append)

- [ ] **Step 1: Write the failing test** (append to `setup-page.test.ts`)

```ts
describe("SetupCard entry", () => {
    const card = read("../src/components/home/SetupCard.astro");
    it("points the main setup link at the wizard, both languages", () => {
        expect(card).toMatch(/href="\/parent\/setup"/);
        expect(card).not.toMatch(/href="\/parent\/starter-packs"/);
        expect(card).toContain("Configura tu familia en 2 minutos");
        expect(card).toContain("Set up your family in 2 minutes");
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$SP/e3jft.sh test/setup-page.test.ts`
Expected: FAIL on `href="/parent/setup"`.

- [ ] **Step 3: Swap the link**

In `SetupCard.astro` replace the anchor:

```astro
    <a href="/parent/setup"
        class="mt-3 flex items-center justify-between gap-3 rounded-xl bg-brand-sky-deep/10 border border-brand-sky-deep/30 px-3 py-2 text-sm font-semibold text-brand-ink hover:bg-brand-sky-deep/20 transition-colors">
        <span>✨ {es ? "Configura tu familia en 2 minutos" : "Set up your family in 2 minutes"}</span>
        <span class="text-brand-sky-text" aria-hidden="true">→</span>
    </a>
```

(Keep the exact class string the current anchor has — only `href` and the `<span>` text change.)

- [ ] **Step 4: Run the tests**

Run: `$SP/e3jft.sh test/setup-page.test.ts test/parent-hub.test.ts`
Expected: PASS (if `parent-hub.test.ts` asserted the old starter-packs link, update that assertion to `/parent/setup`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/home/SetupCard.astro frontend/test/setup-page.test.ts frontend/test/parent-hub.test.ts
git commit -m "feat(ux-e3): hub setup card opens the guided wizard

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Docs — user guides + CLAUDE.md

**Files:**
- Modify: `docs/USER_GUIDE_EN.md` (§1.3, before "### Invite by email"), `docs/USER_GUIDE_ES.md` (§1.3, before "### Invitar por correo electronico"), `CLAUDE.md` (after the "### Onboarding tours" block)

- [ ] **Step 1: Guides**

EN, insert after the line `Once registered, you can invite the rest of your family members.`:

```markdown
### Guided setup (2 minutes)

The parent hub's setup card opens **Set up your family** (`/parent/setup`): four short steps that end with a ready-to-create set of chores, rewards and gigs.

1. **Kids** — the kids who already joined are listed; add the ones who haven't (name + age band).
2. **What matters** — pick any of routines, school, home, kitchen, pets, self-care, and leave a note.
3. **Rewards & cash** — the reward styles you like, and whether you want a cash gig board.
4. **Review** — tick, edit and press **Create**. Nothing exists until you do.

On Plus/Pro the set is drafted by the AI from your answers; on the free plan it comes from the age starter packs, filtered by your answers. Either way you can still browse the packs yourself.

A kid who hasn't joined gets their chores in the **shared rotation** until they do — assign them from Tasks later — or create their account right there (email + password). After creating, **Refine with Jarvis** opens a chat prefilled with what you set up.
```

ES, insert after `Una vez registrado, puede invitar a los demas miembros de la familia.`:

```markdown
### Configuración guiada (2 minutos)

La tarjeta de configuración del inicio abre **Configura tu familia** (`/parent/setup`): cuatro pasos cortos que terminan con un conjunto de tareas, premios y chambitas listo para crear.

1. **Hijos** — los que ya se unieron aparecen; agrega a los que faltan (nombre + rango de edad).
2. **Qué es lo más importante** — rutinas, escuela, casa, cocina, mascotas, cuidado personal, y una nota.
3. **Premios y dinero** — los tipos de premio que te gustan y si quieres un tablero de chambitas con dinero.
4. **Revisar** — marca, edita y pulsa **Crear**. Nada existe hasta que lo hagas.

En Plus/Pro la IA arma el conjunto a partir de tus respuestas; en el plan gratis sale de los paquetes por edad, filtrados por tus respuestas. En ambos casos puedes ver los paquetes tú mismo.

Un hijo que aún no se ha unido recibe sus tareas en la **rotación compartida** hasta que entre — asígnalas desde Tareas después — o crea su cuenta ahí mismo (correo + contraseña). Al terminar, **Afinar con Jarvis** abre un chat con lo que configuraste.
```

- [ ] **Step 2: CLAUDE.md**

After the "### Onboarding tours" bullet list (before "### Per-family module registry"), add:

```markdown
### Guided setup (UX-E3)

`/parent/setup` is a four-step wizard (kids + age band → priorities → reward styles + cash toggle → review). `POST /api/families/onboarding/setup-draft` returns the draft and **stores nothing**; the page creates every ticked row through the ordinary create endpoints (E1 pattern: `createAll` in `lib/setupWizard.ts` with an injected `post`, errors kept on the row, retry re-posts only failed rows). The AI gate is **silent** — `family_tier_allows("ai_features")` + `LITELLM_API_KEY` decide; a free family gets `source: "pack"` (starter packs filtered by `CHORE_TAGS` priorities) with HTTP 200, and any AI failure degrades to the pack with `ai_failed: true`. Kid names bind to active+approved CHILD/TEEN members only (shared `name_match.py`, same rule as the chart scanner); an unbound kid's chores are created AUTO (shared rotation) and the review step shows the join code or creates the account via `POST /api/auth/register`. Copy lives only in `lib/setupWizard.ts`.
```

- [ ] **Step 3: Verify and commit**

Run: `$SP/e3jft.sh test/setup-page.test.ts` (unchanged, sanity) and `cd frontend && npx astro build 2>&1 | tail -2` (the guides are rendered at build).
Expected: PASS, build OK.

```bash
git add docs/USER_GUIDE_EN.md docs/USER_GUIDE_ES.md CLAUDE.md
git commit -m "docs(ux-e3): guided setup in the guides and CLAUDE.md

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Whole-branch verification (before the final review)

- Backend: `$SP/e3jpt.sh tests/test_setup_draft.py tests/test_starter_pack_tags.py tests/test_name_match.py tests/test_chart_scanner.py tests/test_ai_gating.py tests/test_starter_packs.py tests/test_onboarding.py` then the FULL suite in the background (`PT_TAIL=20 $SP/e3jpt.sh tests/ > $SP/e3-full.log 2>&1 &`, ~12 min) and `ruff check app`.
- Frontend: `$SP/e3jft.sh` (whole vitest), `npx astro check`, `npx astro build`.
- Mutation checks (each must turn a named test red): invert the tag filter in `pack_draft` (`or pool` → always `pool`); make `_KID_ROLES` include `"parent"`; flip `included: !duplicateOf` to `true`; make `createAll` skip the `status !== "done"` guard; return `[...TOGGLABLE_MODULES]` unfiltered from `modulesBodyWithoutGigs`.
