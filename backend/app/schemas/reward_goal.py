from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class GoalSet(BaseModel):
    reward_id: UUID


class GoalProgress(BaseModel):
    reward_id: UUID
    reward_title: str
    reward_icon: Optional[str] = None
    points_cost: int
    balance: int
    progress_pct: int   # 0–100
    pts_to_go: int
    affordable: bool
    set_at: datetime

    model_config = {"from_attributes": True}
