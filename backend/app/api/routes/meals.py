"""Meal planning routes (W7.2)."""

from datetime import date as date_t
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ValidationError
from app.core.type_utils import to_uuid_required
from app.models import User
from app.schemas.meal import (
    MealPlanEntryCreate,
    MealPlanEntryResponse,
    MealPlanEntryUpdate,
    RecipeCreate,
    RecipeResponse,
    RecipeUpdate,
)
from app.services.meal_service import MealService
from app.services.recipe_importer import import_recipe_from_url


router = APIRouter()


# ─── Recipes ──────────────────────────────────────────────────────


@router.get("/recipes", response_model=List[RecipeResponse])
async def list_recipes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await MealService.list_recipes(
        db, to_uuid_required(current_user.family_id)
    )


@router.post(
    "/recipes",
    response_model=RecipeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recipe(
    data: RecipeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await MealService.create_recipe(
        db,
        data,
        to_uuid_required(current_user.family_id),
        to_uuid_required(current_user.id),
    )


@router.get("/recipes/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(
    recipe_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await MealService.get_recipe(
        db, recipe_id, to_uuid_required(current_user.family_id)
    )


@router.patch("/recipes/{recipe_id}", response_model=RecipeResponse)
async def update_recipe(
    recipe_id: UUID,
    data: RecipeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await MealService.update_recipe(
        db, recipe_id, data, to_uuid_required(current_user.family_id)
    )


@router.delete("/recipes/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe(
    recipe_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await MealService.delete_recipe(
        db, recipe_id, to_uuid_required(current_user.family_id)
    )
    return None


class RecipeImportRequest(BaseModel):
    url: str = Field(..., min_length=10, max_length=2000)


class RecipeImportResponse(BaseModel):
    name: str
    description: Optional[str] = None
    ingredients_text: Optional[str] = None
    prep_minutes: Optional[int] = None
    source_url: str
    confidence: float


@router.post("/recipes/import", response_model=RecipeImportResponse)
async def import_recipe(
    data: RecipeImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch recipe URL, parse via LLM, return fields without saving.
    Frontend reviews then POSTs to /recipes to persist."""
    try:
        r = await import_recipe_from_url(data.url)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return RecipeImportResponse(
        name=r.name,
        description=r.description,
        ingredients_text=r.ingredients_text,
        prep_minutes=r.prep_minutes,
        source_url=r.source_url,
        confidence=r.confidence,
    )


# ─── Plan entries ────────────────────────────────────────────────


@router.get("/plan", response_model=List[MealPlanEntryResponse])
async def list_plan(
    start: date_t = Query(...),
    end: date_t = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await MealService.list_plan(
        db, to_uuid_required(current_user.family_id), start, end
    )


@router.post(
    "/plan",
    response_model=MealPlanEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_entry(
    data: MealPlanEntryCreate,
    auto_shop: bool = Query(
        False,
        description="If true and entry has a recipe, push its ingredients to the active shopping list.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await MealService.add_entry(
        db,
        data,
        to_uuid_required(current_user.family_id),
        auto_shop=auto_shop,
        added_by=to_uuid_required(current_user.id),
    )


@router.patch("/plan/{entry_id}", response_model=MealPlanEntryResponse)
async def update_entry(
    entry_id: UUID,
    data: MealPlanEntryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await MealService.update_entry(
        db, entry_id, data, to_uuid_required(current_user.family_id)
    )


@router.delete("/plan/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await MealService.delete_entry(
        db, entry_id, to_uuid_required(current_user.family_id)
    )
    return None
