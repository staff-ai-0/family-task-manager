"""Early Bird API schemas. Ints are ints (strict mobile clients)."""
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

DayState = Literal["early", "pending", "open", "missed", "neutral"]


class WeekDay(BaseModel):
    date: date
    state: Literal["early", "pending", "open", "missed", "neutral", "future"]


class GrabItem(BaseModel):
    assignment_id: UUID
    title: str
    points: int
    owner_name: str


class EarlyBirdMe(BaseModel):
    enabled: bool
    applies: bool
    deadline: str
    cutoff_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    today: Optional[DayState] = None
    week: list[WeekDay]
    week_result: str
    run_weeks: int
    streak_weeks: int
    streak_cents: int
    week_pct: int
    bonus_pct: int
    grabs: list[GrabItem]
    take_block: Optional[str] = None
    open_today: int = 0


class FamilyTeen(BaseModel):
    user_id: UUID
    name: str
    today: Optional[DayState] = None
    week: list[WeekDay]
    week_result: str
    run_weeks: int
