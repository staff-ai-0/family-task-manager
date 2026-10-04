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
