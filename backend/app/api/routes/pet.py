"""Virtual pet routes (W4.3)."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.models import User
from app.models.kid_pet import VALID_SPECIES
from app.services.pet_service import PetService, TREATS


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
        status_label=pet.status_label,
    )


@router.get("/", response_model=Optional[PetOut])
async def get_pet(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pet = await PetService.get_for_user(db, to_uuid_required(current_user.id))
    if not pet:
        return None
    PetService.apply_decay_in_place(pet)
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


class TreatRequest(BaseModel):
    treat_type: str = Field(..., min_length=1, max_length=24)


@router.get("/treats")
async def list_treats(current_user: User = Depends(get_current_user)):
    return [
        {"type": k, **v} for k, v in TREATS.items()
    ]


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
