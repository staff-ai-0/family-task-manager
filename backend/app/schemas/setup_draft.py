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
