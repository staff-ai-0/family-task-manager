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
