"""Calendar event Pydantic schemas (W2.1)."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.calendar_event import VALID_SOURCES
from app.schemas.base import FamilyEntityResponse


class CalendarEventBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    location: Optional[str] = Field(None, max_length=200)
    start_ts: datetime
    end_ts: Optional[datetime] = None
    all_day: bool = False
    attendees: Optional[List[UUID]] = None
    color: Optional[str] = Field(None, max_length=24)
    source: str = Field("manual", max_length=24)
    source_doc_url: Optional[str] = Field(None, max_length=512)
    recurrence_rule: Optional[str] = Field(
        None,
        max_length=256,
        description="RRULE string, e.g. FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=12",
    )

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        if v not in VALID_SOURCES:
            raise ValueError(
                f"source must be one of {sorted(VALID_SOURCES)}; got {v!r}"
            )
        return v


class CalendarEventCreate(CalendarEventBase):
    pass


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    location: Optional[str] = Field(None, max_length=200)
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    all_day: Optional[bool] = None
    attendees: Optional[List[UUID]] = None
    color: Optional[str] = Field(None, max_length=24)


class CalendarEventResponse(FamilyEntityResponse):
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_ts: datetime
    end_ts: Optional[datetime] = None
    all_day: bool
    attendees: Optional[List[UUID]] = None
    color: Optional[str] = None
    source: str
    source_doc_url: Optional[str] = None
    created_by: Optional[UUID] = None
    recurrence_rule: Optional[str] = None
    recurrence_parent_id: Optional[UUID] = None
