"""Kiosk request/response schemas (W3.3, P1-KIOSK)."""

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ─── Device management ────────────────────────────────────────────────


class DeviceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class DeviceOut(BaseModel):
    id: UUID
    name: str
    token: str
    is_active: bool
    last_seen: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Member prefs: color + kiosk PIN ──────────────────────────────────


class MemberPrefOut(BaseModel):
    user_id: UUID
    name: str
    role: str
    color: str  # palette name, e.g. "sky"
    color_hex: str  # e.g. "#4FB8E6"
    has_pin: bool


class MemberPrefUpdate(BaseModel):
    # Palette NAME from MEMBER_COLORS (not a hex) — validated in the service.
    color: Optional[str] = None
    # "1234" sets, "" clears, omitted leaves untouched.
    pin: Optional[str] = Field(None, max_length=8)


# ─── Per-kid PIN view ──────────────────────────────────────────────────


class PinViewRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=64)
    user_id: UUID
    pin: str = Field(..., min_length=4, max_length=4)


class KidChore(BaseModel):
    title: str
    title_es: Optional[str] = None
    points: int
    is_done: bool
    is_bonus: bool


class KidView(BaseModel):
    user_id: UUID
    name: str
    color_hex: str
    points: int
    cash_cents: int
    chores: List[KidChore]
    chores_done: int
    gigs_open: int
    # Prior-day mandatory chores still open (PENDING/OVERDUE). They keep
    # bonus/gigs locked, so hiding them made the kiosk celebrate "No chores
    # today!" while the kid was actually blocked.
    overdue_chores: List[KidChore] = []
    # Star Mode (P2): when true the kiosk renders points as big stars and hides
    # the peso/cash amount for this (young) kid. Pure presentation over points.
    star_mode: bool = False


# ─── Snapshot ────────────────────────────────────────────────────────


class KioskMember(BaseModel):
    id: UUID
    name: str
    role: str
    tasks_today: int
    tasks_done: int
    color_hex: str
    has_pin: bool


class KioskTask(BaseModel):
    title: str
    user_name: str
    user_color: str
    is_done: bool
    is_bonus: bool


class KioskLeaderboardEntry(BaseModel):
    user_id: UUID
    name: str
    color_hex: str
    points_week: int


class KioskEvent(BaseModel):
    title: str
    start_ts: datetime
    location: Optional[str] = None
    all_day: bool


class KioskShoppingList(BaseModel):
    name: str
    pending: int


class KioskBoss(BaseModel):
    # Cooperative weekly boss battle (see FamilyCupService.boss_battle).
    # Display-only — derived from assigned mandatory task points; never
    # punishes a member. Rendered as an HP progress bar on the wall display.
    key: str
    name_es: str
    name_en: str
    emoji: str
    max_hp: int
    current_hp: int
    damage: int
    percent_defeated: int
    defeated: bool
    active: bool


class KioskSnapshot(BaseModel):
    family_name: str
    now_utc: datetime
    members: List[KioskMember]
    tasks: List[KioskTask]
    events_today: List[KioskEvent]
    events_tomorrow: List[KioskEvent]
    shopping: List[KioskShoppingList]
    # Weekly points leaderboard (Mon 00:00 family-tz → now). Display-only —
    # positive point_transactions summed per member; no new economy.
    leaderboard: List[KioskLeaderboardEntry]
    # Cooperative weekly boss battle for the same week.
    boss: KioskBoss
    week_start: date
