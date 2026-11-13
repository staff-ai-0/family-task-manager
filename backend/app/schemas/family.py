"""
Family Pydantic schemas

Request and response models for family-related operations.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_serializer, field_validator
from typing import Literal, Optional, List
from uuid import UUID

from app.schemas.user import UserResponse
from app.schemas.base import EntityResponse


def _parse_deadline(value):
    """Accept "HH:MM" (or a time) between 07:00 and 22:00, on a 5-minute step."""
    if value is None or isinstance(value, time):
        parsed = value
    else:
        try:
            hh, mm = str(value).split(":")[:2]
            parsed = time(int(hh), int(mm))
        except (ValueError, TypeError):
            raise ValueError("early_bird_deadline must be HH:MM")
    if parsed is None:
        return parsed
    if parsed.minute % 5 != 0 or parsed.second or not time(7, 0) <= parsed <= time(22, 0):
        raise ValueError("early_bird_deadline must be 07:00-22:00 in 5-minute steps")
    return parsed.replace(second=0, microsecond=0)


def _parse_clock(value, name, lo, hi):
    """Accept "HH:MM" (or a time) within [lo, hi], on a 5-minute step."""
    if value is None or isinstance(value, time):
        parsed = value
    else:
        try:
            hh, mm = str(value).split(":")[:2]
            parsed = time(int(hh), int(mm))
        except (ValueError, TypeError):
            raise ValueError(f"{name} must be HH:MM")
    if parsed is None:
        return parsed
    if parsed.minute % 5 != 0 or parsed.second or not lo <= parsed <= hi:
        raise ValueError(
            f"{name} must be {lo.strftime('%H:%M')}-{hi.strftime('%H:%M')} in 5-minute steps"
        )
    return parsed.replace(second=0, microsecond=0)


def _validate_iana_tz(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {value}") from exc
    return value


# Base schemas
class FamilyBase(BaseModel):
    """Base family schema with common fields"""

    name: str = Field(..., min_length=1, max_length=100)


# Request schemas
class FamilyCreate(FamilyBase):
    """Schema for creating a new family"""

    pass


class FamilyUpdate(BaseModel):
    """Schema for updating family details"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    timezone: Optional[str] = Field(None, max_length=64)
    # Parental opt-in for AI processing of kid-generated content (proof
    # photos, family chat). Service stamps ai_processing_consent_at on change.
    ai_processing_consent: Optional[bool] = None
    # User-visible term for the gig board, per family. DB/routes stay "gig".
    gig_term: Optional[Literal["gig", "chamba"]] = None
    # Value of one point in centavos for the points_rate paycheck (100 = $1 MXN).
    point_value_cents: Optional[int] = Field(None, ge=1, le=100_000)
    # UX-D3 weekly quest bonus in points; 0 switches weekly quests off.
    quest_bonus_points: Optional[int] = Field(None, ge=0, le=500)
    # UX-D4a evening smart reminders for kids. None = leave as-is on PATCH.
    smart_reminders_enabled: Optional[bool] = None
    # Jarvis teen check-in: true = on, false = off, null = back to undecided.
    teen_checkin_enabled: Optional[bool] = None
    # UX-D4b mystery box points maximum; 0 switches boxes off.
    mystery_box_points: Optional[int] = Field(None, ge=0, le=500)
    # Early Bird. Deadline is "HH:MM" (07:00-22:00, 5-min steps). Days are
    # weekdays 0=Mon..6=Sun, distinct, non-empty; an explicit null = every day.
    early_bird_enabled: Optional[bool] = None
    early_bird_deadline: Optional[time] = None
    early_bird_days: Optional[List[int]] = None
    early_bird_bonus_pct: Optional[int] = Field(None, ge=0, le=100)
    early_bird_week_pct: Optional[int] = Field(None, ge=0, le=50)
    early_bird_streak_cents: Optional[int] = Field(None, ge=0, le=1_000_000)
    # Chore rules v2 (cross-field order is checked in FamilyService).
    chore_cutoff: Optional[time] = None
    grab_window_end: Optional[time] = None
    teen_alarm_1: Optional[time] = None
    teen_alarm_2: Optional[time] = None
    # Module registry: list of ENABLED togglable modules. None = leave as-is
    # on PATCH; stored NULL = all on. Must be a subset of TOGGLABLE_MODULES.
    enabled_modules: Optional[List[str]] = None

    @field_validator("early_bird_deadline", mode="before")
    @classmethod
    def _check_deadline(cls, v):
        return _parse_deadline(v)

    @field_validator("chore_cutoff", mode="before")
    @classmethod
    def _check_cutoff(cls, v):
        return _parse_clock(v, "chore_cutoff", time(17, 0), time(23, 0))

    @field_validator("grab_window_end", mode="before")
    @classmethod
    def _check_grab_end(cls, v):
        return _parse_clock(v, "grab_window_end", time(0, 0), time(23, 30))

    @field_validator("teen_alarm_1", "teen_alarm_2", mode="before")
    @classmethod
    def _check_alarm(cls, v):
        return _parse_clock(v, "teen alarm", time(6, 0), time(23, 0))

    @field_validator("early_bird_days")
    @classmethod
    def _check_days(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return v
        if not v or any(d < 0 or d > 6 for d in v):
            raise ValueError("early_bird_days must be a non-empty list of weekdays 0-6")
        return sorted(set(v))

    @field_validator("enabled_modules")
    @classmethod
    def _check_modules(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        from app.core.modules import TOGGLABLE_MODULES

        unknown = sorted(set(v) - TOGGLABLE_MODULES)
        if unknown:
            raise ValueError(f"unknown modules: {', '.join(unknown)}")
        return sorted(set(v))

    @field_validator("timezone")
    @classmethod
    def _check_tz(cls, v: Optional[str]) -> Optional[str]:
        return _validate_iana_tz(v)


class FamilyDeleteRequest(BaseModel):
    """Re-auth payload for permanent family deletion (parent only).

    Password accounts must send ``password``. Google-only accounts (no
    password hash) must send ``confirm_name`` matching the family name.
    """

    password: Optional[str] = None
    confirm_name: Optional[str] = Field(None, max_length=100)


# Response schemas
class FamilyResponse(EntityResponse):
    """Schema for family response"""

    name: str = Field(..., min_length=1, max_length=100)
    created_by: Optional[UUID] = None  # Optional for legacy data
    is_active: bool
    timezone: str = "UTC"
    # AI opt-in state: consent_at is NULL until a parent decides either way
    # (dashboard shows a one-time prompt banner while NULL).
    ai_processing_consent: bool = False
    ai_processing_consent_at: Optional[datetime] = None
    # User-visible term for the gig board, per family. DB/routes stay "gig".
    gig_term: str = "gig"
    point_value_cents: int = 100
    # UX-D3 weekly quest bonus: NULL = not decided yet (quests off, parent hub
    # shows a one-time opt-in card), 0 = off by choice, > 0 = on.
    quest_bonus_points: Optional[int] = None
    # UX-D4a: evening smart reminders for kids (on by default).
    smart_reminders_enabled: bool = True
    # Jarvis teen check-in: NULL = undecided (off + one-time parent-hub card).
    teen_checkin_enabled: Optional[bool] = None
    teen_checkin_decided_at: Optional[datetime] = None
    # UX-D4b: NULL = undecided (boxes off + one-time parent-hub card).
    mystery_box_points: Optional[int] = None
    early_bird_enabled: bool = False
    early_bird_enabled_at: Optional[datetime] = None
    early_bird_deadline: time = time(11, 0)
    early_bird_days: Optional[List[int]] = None  # NULL = every day
    early_bird_bonus_pct: int = 20
    early_bird_week_pct: int = 5
    early_bird_streak_cents: int = 38000
    chore_cutoff: time = time(20, 30)
    grab_window_end: time = time(22, 30)
    teen_alarm_1: time = time(15, 0)
    teen_alarm_2: time = time(19, 0)
    rules_version: int = 1
    # Stored value: NULL = all modules on. Clients resolve via the same rule.
    enabled_modules: Optional[List[str]] = None


    @field_serializer(
        "early_bird_deadline", "chore_cutoff", "grab_window_end",
        "teen_alarm_1", "teen_alarm_2",
    )
    def _ser_deadline(self, v: time) -> str:
        return v.strftime("%H:%M")


class FamilyWithMembers(FamilyResponse):
    """Family response with member list"""

    members: List[UserResponse] = []


class FamilyStats(BaseModel):
    """Family statistics"""

    total_members: int
    total_tasks: int
    completed_tasks: int
    pending_tasks: int
    total_rewards: int
    active_consequences: int
