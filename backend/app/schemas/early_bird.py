"""Early Bird API schemas. Ints are ints (strict mobile clients)."""
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

DayState = Literal["early", "pending", "open", "missed", "neutral"]


class WeekDay(BaseModel):
    date: date
    state: Literal["early", "pending", "open", "missed", "neutral", "future"]


class WeekLadder(BaseModel):
    completed_pct: int
    early_pct: int
    tier: str
    bonus_pct: int
    final: bool


class EarlyBirdMe(BaseModel):
    enabled: bool
    applies: bool
    deadline: str
    # End of the day (next family-local midnight): the kid can report until then.
    cutoff_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    rules_version: int = 1
    teen_alarm_1: str = "15:00"
    teen_alarm_2: str = "19:00"
    week_ladder: WeekLadder
    today: Optional[DayState] = None
    week: list[WeekDay]
    week_result: str
    run_weeks: int
    weeks_to_payout: int
    streak_weeks: int
    streak_cents: int
    bonus_pct: int
    open_today: int = 0


class FamilyTeen(BaseModel):
    user_id: UUID
    name: str
    today: Optional[DayState] = None
    week: list[WeekDay]
    week_result: str
    run_weeks: int
    weeks_to_payout: int
    streak_weeks: int
    week_ladder: WeekLadder
