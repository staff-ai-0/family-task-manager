"""Rules acceptance API schemas. Ints are ints (strict mobile clients)."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class BonusTier(BaseModel):
    early_pct: int
    bonus_pct: int


class RulesSnapshot(BaseModel):
    version: int
    deadline: str
    cutoff: str
    grab_end: str
    alarm_1: str
    alarm_2: str
    streak_cents: int
    chore_bonus_pct: int
    floor_pct: int
    bonus_tiers: List[BonusTier]


class RulesStatus(BaseModel):
    required: bool
    version: int
    accepted_at: Optional[datetime] = None
    rules: RulesSnapshot


class AcceptRequest(BaseModel):
    version: int


class AcceptResponse(BaseModel):
    version: int
    accepted_at: datetime


class AcceptanceRow(BaseModel):
    user_id: UUID
    name: str
    role: str
    accepted_at: Optional[datetime] = None
