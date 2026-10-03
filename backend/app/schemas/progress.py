"""UX-D1 progress (streak + rank), UX-D2 badges, and UX-D3 weekly quest API
shapes. All numbers are plain ints."""
from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DayEntry(BaseModel):
    date: date
    state: str  # none | done | missed | shield | today | future


class ProgressResponse(BaseModel):
    applies: bool
    xp: int = 0
    rank: int = 1
    rank_floor_xp: int = 0
    next_rank_xp: Optional[int] = None
    streak_days: int = 0
    week: list[DayEntry] = Field(default_factory=list)
    shield_used: bool = False
    celebrate_rank: Optional[int] = None


class AckRankRequest(BaseModel):
    rank: int = Field(ge=1, le=10)


class BadgeProgress(BaseModel):
    badge: str                         # catalog key
    count: int = 0                     # derived now; can drop after a parent correction
    tier: int = 0                      # highest EARNED tier (0 = none); never drops
    next_target: Optional[int] = None  # count needed for the next tier; None at gold
    earned_at: Optional[datetime] = None  # when the highest earned tier was recorded


class UnseenBadge(BaseModel):
    id: UUID
    badge: str
    tier: int


class BadgesResponse(BaseModel):
    applies: bool
    badges: list[BadgeProgress] = Field(default_factory=list)
    unseen: list[UnseenBadge] = Field(default_factory=list)
    earned_total: int = 0


class AckBadgesRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=24)


class QuestProgress(BaseModel):
    id: UUID
    quest: str                 # catalog key
    target: int
    progress: int              # capped at target; equals target once paid
    bonus_points: int
    week_start: date
    days_left: int             # counts today (Sunday = 1)
    completed: bool            # the bonus was paid


class QuestCelebrate(BaseModel):
    id: UUID
    quest: str
    target: int
    bonus_points: int
    last_week: bool


class QuestResponse(BaseModel):
    applies: bool
    gig_term: str = "gig"      # the family's word for a gig (go_getter copy)
    quest: Optional[QuestProgress] = None
    celebrate: Optional[QuestCelebrate] = None


class AckQuestRequest(BaseModel):
    id: UUID


# ── UX-D4b mystery box ─────────────────────────────────────────────────
class MysteryBoxView(BaseModel):
    id: UUID
    day: date
    opened: bool
    kind: Optional[str] = None            # surprise | points once opened
    surprise_title: Optional[str] = None
    surprise_emoji: Optional[str] = None
    points: int = 0


class MysteryResponse(BaseModel):
    applies: bool
    enabled: bool = False                 # the family's boxes are on
    unopened: List[MysteryBoxView] = []   # oldest first
    opened_today: Optional[MysteryBoxView] = None


class DeliveryView(BaseModel):
    id: UUID
    kid_name: str
    surprise_title: str
    surprise_emoji: Optional[str] = None
    day: date
    opened_at: datetime


class SurpriseView(BaseModel):
    id: UUID
    title: str
    emoji: Optional[str] = None


class SurpriseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)   # trimmed and bounded to 60 by the service
    emoji: Optional[str] = Field(None, max_length=8)
