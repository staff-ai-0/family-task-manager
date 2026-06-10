# backend/app/schemas/oversight.py
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class KidGoal(BaseModel):
    reward_title: str
    reward_icon: Optional[str] = None
    progress_pct: int
    pts_to_go: int
    affordable: bool


class KidSummary(BaseModel):
    user_id: UUID
    name: str
    role: str  # serialized UserRole value (lowercase, e.g. "child")
    points: int
    gig_trust_streak: int
    auto_approve_active: bool
    goal: Optional[KidGoal] = None
    pending_approvals: int  # this kid's items across BOTH queues
    open_today: int  # PENDING assignments dated family-local today
    active_consequences: int


class PendingCounts(BaseModel):
    tasks: int
    gig_claims: int
    total: int


class OversightSummary(BaseModel):
    members: list[KidSummary]
    pending_counts: PendingCounts


class PendingApprovalItem(BaseModel):
    kind: Literal["task", "gig_claim"]
    id: UUID  # assignment_id or claim_id
    title: str
    kid_id: UUID
    kid_name: str
    points: int
    completed_at: Optional[datetime] = None
    proof_text: Optional[str] = None
    proof_image_url: Optional[str] = None
    ai_score: Optional[float] = None  # tasks only; gig claims have no AI validation
