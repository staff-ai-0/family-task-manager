"""Chore baseline API schemas."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    template_id: UUID
    image_url: str
    caption: Optional[str] = None
    position: int
    created_at: datetime


class BaselineStatusRow(BaseModel):
    template_id: UUID
    title: str
    baseline_count: int
    last_baseline_at: Optional[datetime] = None
    due: bool


class RecommendationsOut(BaseModel):
    suggestions: List[str]
    ai_failed: bool
