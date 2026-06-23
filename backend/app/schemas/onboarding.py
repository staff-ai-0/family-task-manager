from typing import List, Optional

from pydantic import BaseModel, model_validator


class OnboardingState(BaseModel):
    child_invited: bool
    task_created: bool
    reward_created: bool
    points_awarded: bool
    dismissed: bool
    all_done: bool = False

    @model_validator(mode="after")
    def compute_all_done(self) -> "OnboardingState":
        self.all_done = all([
            self.child_invited,
            self.task_created,
            self.reward_created,
            self.points_awarded,
        ])
        return self

    model_config = {"from_attributes": True}


class OnboardingEventCreate(BaseModel):
    """Body for recording a welcome-tour funnel event."""
    event_type: str
    step_index: Optional[int] = None


class MemberOnboarding(BaseModel):
    user_id: str
    name: str
    role: str
    completed_welcome_tour: bool
    # completed | skipped | started | not_started — derived from events + flag.
    tour_status: str


class OnboardingAnalytics(BaseModel):
    """Parent-facing onboarding funnel for the family."""
    total_members: int
    tour_completed: int
    tour_skipped: int
    tour_started: int
    tour_not_started: int
    checklist: OnboardingState
    members: List[MemberOnboarding]
