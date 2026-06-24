"""MCP create/update schemas for the calendar domain."""

from typing import Optional

from pydantic import BaseModel


class EventCreate(BaseModel):
    title: str
    start_iso: str
    all_day: bool = False
    location: Optional[str] = None


class EventUpdate(BaseModel):
    title: Optional[str] = None
    location: Optional[str] = None
