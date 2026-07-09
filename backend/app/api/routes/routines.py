"""Routine routes — icon tap-through routines for pre-readers.

Endpoints under ``/api/routines``.

- Parent authoring (create/update/delete routines + steps, assign to a kid or
  the whole family) requires PARENT role.
- Kid runner (``GET /today``, ``POST /{id}/steps/{sid}/complete``) is for the
  kid completing their OWN routine — completing every step awards POINTS
  (privileges — never cash) and feeds the pet.

Everything is family-scoped via ``current_user.family_id`` (multi-tenant).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.models import User
from app.models.routine import TIME_OF_DAY_LABELS
from app.services.routine_service import RoutineService

router = APIRouter()


# ─── Schemas ─────────────────────────────────────────────────────────


class StepIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    label_es: Optional[str] = Field(None, max_length=120)
    icon: Optional[str] = Field(None, max_length=16)
    sort_order: Optional[int] = None


class RoutineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    name_es: Optional[str] = Field(None, max_length=120)
    icon: Optional[str] = Field(None, max_length=16)
    color: Optional[str] = Field(None, max_length=9)
    time_of_day: str = Field("morning", max_length=16)
    assigned_user_id: Optional[UUID] = None
    points_reward: int = Field(10, ge=0, le=1000)
    sort_order: int = 0
    steps: list[StepIn] = Field(default_factory=list)


class RoutineUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    name_es: Optional[str] = Field(None, max_length=120)
    icon: Optional[str] = Field(None, max_length=16)
    color: Optional[str] = Field(None, max_length=9)
    time_of_day: Optional[str] = Field(None, max_length=16)
    assigned_user_id: Optional[UUID] = None
    points_reward: Optional[int] = Field(None, ge=0, le=1000)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

    model_config = {"extra": "ignore"}


class StepUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    label_es: Optional[str] = Field(None, max_length=120)
    icon: Optional[str] = Field(None, max_length=16)
    sort_order: Optional[int] = None


class ReorderIn(BaseModel):
    step_ids: list[UUID]


def _routine_out(routine, lang: str) -> dict:
    return RoutineService._serialize_routine(routine, lang, None)


# ─── Meta ────────────────────────────────────────────────────────────


@router.get("/time-of-day")
async def list_time_of_day(current_user: User = Depends(get_current_user)):
    """The time-of-day windows a routine can belong to (bilingual labels)."""
    return [
        {"value": k, "label": v} for k, v in TIME_OF_DAY_LABELS.items()
    ]


# ─── Kid / kiosk runner ──────────────────────────────────────────────


@router.get("/today")
async def routines_today(
    user_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Active routines the kid runs today with steps + today's progress.

    A PARENT may pass ``?user_id=`` to preview a kid's board (kiosk / config);
    everyone else sees only their own.
    """
    return await RoutineService.today_for_user(
        db, current_user, target_user_id=user_id
    )


@router.post("/{routine_id}/steps/{step_id}/complete")
async def complete_step(
    routine_id: UUID,
    step_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark one step done for the current kid today. When the LAST step is
    tapped the routine awards POINTS + feeds the pet (once per day)."""
    return await RoutineService.complete_step(
        db, current_user, routine_id, step_id
    )


# ─── Parent authoring (CRUD) ─────────────────────────────────────────


@router.get("/")
async def list_routines(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List routines. Parents see all family routines; kids/teens see only the
    ones they run (assigned to them or family-wide)."""
    from app.models.user import UserRole

    for_user = None if current_user.role == UserRole.PARENT else current_user
    routines = await RoutineService.list_routines(
        db,
        current_user.family_id,
        for_user=for_user,
        active_only=for_user is not None,
    )
    lang = getattr(current_user, "preferred_lang", None) or "es"
    return [_routine_out(r, lang) for r in routines]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_routine(
    data: RoutineCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    routine = await RoutineService.create_routine(
        db,
        family_id=current_user.family_id,
        created_by=current_user.id,
        name=data.name,
        name_es=data.name_es,
        icon=data.icon,
        color=data.color,
        time_of_day=data.time_of_day,
        assigned_user_id=data.assigned_user_id,
        points_reward=data.points_reward,
        sort_order=data.sort_order,
        steps=[s.model_dump() for s in data.steps],
    )
    lang = getattr(current_user, "preferred_lang", None) or "es"
    return _routine_out(routine, lang)


@router.get("/{routine_id}")
async def get_routine(
    routine_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine = await RoutineService.get_routine_or_404(
        db, current_user.family_id, routine_id
    )
    lang = getattr(current_user, "preferred_lang", None) or "es"
    return _routine_out(routine, lang)


@router.put("/{routine_id}")
async def update_routine(
    routine_id: UUID,
    data: RoutineUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    routine = await RoutineService.update_routine(
        db,
        current_user.family_id,
        routine_id,
        fields=data.model_dump(exclude_unset=True),
    )
    lang = getattr(current_user, "preferred_lang", None) or "es"
    return _routine_out(routine, lang)


@router.delete("/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routine(
    routine_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    await RoutineService.delete_routine(db, current_user.family_id, routine_id)
    return None


@router.post("/{routine_id}/steps", status_code=status.HTTP_201_CREATED)
async def add_step(
    routine_id: UUID,
    data: StepIn,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    step = await RoutineService.add_step(
        db,
        current_user.family_id,
        routine_id,
        label=data.label,
        label_es=data.label_es,
        icon=data.icon,
        sort_order=data.sort_order,
    )
    return {
        "id": str(step.id),
        "label": step.label,
        "label_es": step.label_es,
        "icon": step.icon,
        "sort_order": step.sort_order,
    }


@router.put("/{routine_id}/steps/{step_id}")
async def update_step(
    routine_id: UUID,
    step_id: UUID,
    data: StepUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    step = await RoutineService.update_step(
        db,
        current_user.family_id,
        routine_id,
        step_id,
        fields=data.model_dump(exclude_unset=True),
    )
    return {
        "id": str(step.id),
        "label": step.label,
        "label_es": step.label_es,
        "icon": step.icon,
        "sort_order": step.sort_order,
    }


@router.delete(
    "/{routine_id}/steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_step(
    routine_id: UUID,
    step_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    await RoutineService.delete_step(
        db, current_user.family_id, routine_id, step_id
    )
    return None


@router.put("/{routine_id}/steps-order")
async def reorder_steps(
    routine_id: UUID,
    data: ReorderIn,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    routine = await RoutineService.reorder_steps(
        db, current_user.family_id, routine_id, data.step_ids
    )
    lang = getattr(current_user, "preferred_lang", None) or "es"
    return _routine_out(routine, lang)
