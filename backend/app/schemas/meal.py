"""Meal planning schemas (W7.2)."""

from datetime import date as date_t
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.meal import VALID_MEAL_TYPES
from app.schemas.base import FamilyEntityResponse


class RecipeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    ingredients_text: Optional[str] = Field(None, max_length=4000)
    prep_minutes: Optional[int] = Field(None, ge=1, le=600)
    source_url: Optional[str] = Field(None, max_length=512)


class RecipeCreate(RecipeBase):
    pass


class RecipeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    ingredients_text: Optional[str] = Field(None, max_length=4000)
    prep_minutes: Optional[int] = Field(None, ge=1, le=600)
    source_url: Optional[str] = Field(None, max_length=512)


class RecipeResponse(FamilyEntityResponse):
    name: str
    description: Optional[str] = None
    ingredients_text: Optional[str] = None
    prep_minutes: Optional[int] = None
    source_url: Optional[str] = None
    created_by: Optional[UUID] = None


class MealPlanEntryBase(BaseModel):
    plan_date: date_t
    meal_type: str = Field(..., max_length=16)
    title: str = Field(..., min_length=1, max_length=200)
    recipe_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("meal_type")
    @classmethod
    def _check_meal_type(cls, v: str) -> str:
        if v not in VALID_MEAL_TYPES:
            raise ValueError(f"meal_type must be one of {sorted(VALID_MEAL_TYPES)}")
        return v


class MealPlanEntryCreate(MealPlanEntryBase):
    pass


class MealPlanEntryUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    recipe_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=2000)


class MealPlanEntryResponse(FamilyEntityResponse):
    plan_date: date_t
    meal_type: str
    title: str
    recipe_id: Optional[UUID] = None
    notes: Optional[str] = None
