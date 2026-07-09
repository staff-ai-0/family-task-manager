"""Virtual pet routes (W4.3 · quest/evolution loop 2026-07-09).

Endpoints under /api/pet. A kid acts only on their OWN pet; a parent may VIEW
a kid's pet (?user_id=) but not act on it — enforced by
PetService.resolve_target. All care / cosmetics purchases spend POINTS (the
privileges currency) — never cash.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.models import User
from app.models.kid_pet import VALID_SPECIES
from app.services.pet_service import CARE_ACTIONS, PetService, TREATS


router = APIRouter()


class PetOut(BaseModel):
    id: UUID
    name: str
    species: str
    mood: int
    hunger: int
    xp: int
    level: int
    xp_to_next_level: int
    evolution_stage: int
    evolution_stage_name: str
    xp_to_next_stage: Optional[int] = None
    status_label: str

    model_config = {"from_attributes": True}


class PetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    species: str = Field("cat", max_length=24)


def _to_out(pet) -> PetOut:
    return PetOut(
        id=pet.id,
        name=pet.name,
        species=pet.species,
        mood=pet.mood,
        hunger=pet.hunger,
        xp=pet.xp,
        level=pet.level,
        xp_to_next_level=pet.xp_to_next_level,
        evolution_stage=pet.evolution_stage,
        evolution_stage_name=pet.evolution_stage_name,
        xp_to_next_stage=pet.xp_to_next_stage,
        status_label=pet.status_label,
    )


@router.get("/", response_model=Optional[PetOut])
async def get_pet(
    user_id: Optional[UUID] = Query(
        None, description="View another family member's pet (parent only)."
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await PetService.resolve_target(db, current_user, user_id, action=False)
    pet = await PetService.get_for_user(db, target)
    if not pet:
        return None
    PetService.apply_decay_in_place(pet)
    PetService._sync_progression(pet)
    await db.commit()
    await db.refresh(pet)
    return _to_out(pet)


@router.get("/species", response_model=list[str])
async def list_species(current_user: User = Depends(get_current_user)):
    return sorted(VALID_SPECIES)


@router.post("/", response_model=PetOut, status_code=status.HTTP_201_CREATED)
async def create_pet(
    data: PetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pet = await PetService.create_for_user(
        db, to_uuid_required(current_user.id), data.name, data.species
    )
    return _to_out(pet)


# ─── Care economy (feed / wash / play — costs POINTS) ────────────────


@router.get("/care-actions")
async def list_care_actions(current_user: User = Depends(get_current_user)):
    return [
        {
            "action": k,
            "cost": v["cost"],
            "hunger": v["hunger"],
            "mood": v["mood"],
            "label": v["label"],
        }
        for k, v in CARE_ACTIONS.items()
    ]


class CareRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=24)
    user_id: Optional[UUID] = None


@router.post("/care", response_model=PetOut)
async def care_pet(
    data: CareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await PetService.resolve_target(
        db, current_user, data.user_id, action=True
    )
    pet = await PetService.care(db, target, data.action)
    return _to_out(pet)


@router.post("/feed", response_model=PetOut)
async def feed_pet(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pet = await PetService.feed(db, to_uuid_required(current_user.id))
    return _to_out(pet)


@router.post("/play", response_model=PetOut)
async def play_pet(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pet = await PetService.play(db, to_uuid_required(current_user.id))
    return _to_out(pet)


# ─── Treats (existing catalog — kept working) ────────────────────────


class TreatRequest(BaseModel):
    treat_type: str = Field(..., min_length=1, max_length=24)


@router.get("/treats")
async def list_treats(current_user: User = Depends(get_current_user)):
    return [{"type": k, **v} for k, v in TREATS.items()]


@router.post("/treat", response_model=PetOut)
async def give_treat(
    data: TreatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pet = await PetService.give_treat(
        db, to_uuid_required(current_user.id), data.treat_type
    )
    return _to_out(pet)


# ─── Cosmetics (points sink · stage-gated) ───────────────────────────


class CosmeticRequest(BaseModel):
    cosmetic_key: str = Field(..., min_length=1, max_length=48)
    user_id: Optional[UUID] = None


@router.get("/cosmetics")
async def list_cosmetics(
    user_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await PetService.resolve_target(db, current_user, user_id, action=False)
    return await PetService.list_cosmetics(db, target)


@router.post("/cosmetics/buy")
async def buy_cosmetic(
    data: CosmeticRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await PetService.resolve_target(
        db, current_user, data.user_id, action=True
    )
    rec = await PetService.buy_cosmetic(db, target, data.cosmetic_key)
    return {"cosmetic_key": rec.cosmetic_key, "owned": True, "equipped": rec.equipped}


@router.post("/cosmetics/equip")
async def equip_cosmetic(
    data: CosmeticRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await PetService.resolve_target(
        db, current_user, data.user_id, action=True
    )
    rec = await PetService.equip_cosmetic(db, target, data.cosmetic_key, equip=True)
    return {"cosmetic_key": rec.cosmetic_key, "equipped": rec.equipped}


@router.post("/cosmetics/unequip")
async def unequip_cosmetic(
    data: CosmeticRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await PetService.resolve_target(
        db, current_user, data.user_id, action=True
    )
    rec = await PetService.equip_cosmetic(db, target, data.cosmetic_key, equip=False)
    return {"cosmetic_key": rec.cosmetic_key, "equipped": rec.equipped}


# ─── Quest view (read-only kid UI payload) ───────────────────────────


@router.get("/quest-view")
async def quest_view(
    user_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await PetService.resolve_target(db, current_user, user_id, action=False)
    return await PetService.quest_view(db, target, current_user.family_id)
