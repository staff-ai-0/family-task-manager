"""MCP create/update schemas for the meals domain."""

from typing import Optional

from pydantic import BaseModel


class RecipeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    ingredients_text: Optional[str] = None
    prep_minutes: Optional[int] = None
    source_url: Optional[str] = None


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ingredients_text: Optional[str] = None
    prep_minutes: Optional[int] = None
    source_url: Optional[str] = None


class PlanEntryCreate(BaseModel):
    plan_date: str
    meal_type: str
    title: str
    recipe_id: Optional[str] = None
    notes: Optional[str] = None


class PlanEntryUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
