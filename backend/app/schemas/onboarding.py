from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class OnboardingState(BaseModel):
    child_invited: bool
    task_created: bool
    reward_created: bool
    points_awarded: bool
    dismissed: bool
    # Optional extra step (P1-KIOSK): derived from calendar_events with
    # source='ocr_flyer' — no family column needed. NOT part of all_done so
    # existing families' completed checklists don't regress.
    flyer_scanned: bool = False
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


# ── Age-preset starter packs (P1-W3) ─────────────────────────────────────────

class StarterChore(BaseModel):
    """A pack chore → becomes a TaskTemplate (earns POINTS)."""
    id: str
    title_es: str
    title_en: str
    points: int
    interval_days: int  # 1=daily … 7=weekly


class StarterGig(BaseModel):
    """A pack gig → becomes a GigOffering (points = $MXN cash value)."""
    id: str
    title_es: str
    title_en: str
    points: int  # 1 point = $1 MXN on the gig board
    difficulty: int  # 1=easy 2=medium 3=hard
    category: str


class StarterReward(BaseModel):
    """A pack reward → becomes a Reward redeemable with points."""
    id: str
    title_es: str
    title_en: str
    points_cost: int
    category: str
    icon: Optional[str] = None
    requires_approval: bool = False


class StarterPack(BaseModel):
    age_band: str
    label_es: str
    label_en: str
    tagline_es: str
    tagline_en: str
    chores: List[StarterChore]
    gigs: List[StarterGig]
    rewards: List[StarterReward]


class StarterPackList(BaseModel):
    packs: List[StarterPack]


class StarterPackApplyRequest(BaseModel):
    """Apply (a subset of) one age band's pack to the family.

    Omitting an ids list applies EVERY item of that kind; sending an empty
    list applies none (the preview UI always sends explicit selections).
    """
    age_band: str
    chore_ids: Optional[List[str]] = None
    gig_ids: Optional[List[str]] = None
    reward_ids: Optional[List[str]] = None
    # Single-title models (gigs, rewards) are created in this language.
    lang: Literal["es", "en"] = "es"


class StarterPackApplyCounts(BaseModel):
    chores: int = 0
    gigs: int = 0
    rewards: int = 0


class StarterPackApplyResult(BaseModel):
    """Created vs skipped (already-existing identical titles) per kind."""
    age_band: str
    created: StarterPackApplyCounts = Field(default_factory=StarterPackApplyCounts)
    skipped: StarterPackApplyCounts = Field(default_factory=StarterPackApplyCounts)
    skipped_titles: List[str] = Field(default_factory=list)
