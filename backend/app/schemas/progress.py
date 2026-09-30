"""UX-D1 progress (streak + rank) API shapes. All numbers are plain ints."""
from datetime import date
from typing import Optional

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
