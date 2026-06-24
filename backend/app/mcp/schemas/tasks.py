"""MCP create/update schemas for the tasks domain.

These mirror the LLM-facing argument shape of the legacy ``jarvis_tools``
handlers so the migration preserves behavior (e.g. mandatory chores clamp
points to 0 in the adapter).
"""

from typing import Optional

from pydantic import BaseModel


class TemplateCreate(BaseModel):
    title: str
    is_bonus: bool
    points: int = 0
    interval_days: int = 1
    effort_level: int = 1


class TemplateUpdate(BaseModel):
    title: Optional[str] = None
    points: Optional[int] = None
    interval_days: Optional[int] = None
    effort_level: Optional[int] = None
