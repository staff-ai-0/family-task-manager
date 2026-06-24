"""MCP pydantic schemas for pet-domain entities.

The pet domain exposes list/get (read-only CRUD) plus two custom ops:
  feed     — calls PetService.feed(db, user_id); lowers hunger.
  interact — calls PetService.play(db, user_id); boosts mood.

No create/update/delete via MCP: pets are created through the UI flow
(PetService.create_for_user) and are never deleted through Jarvis.
"""
from uuid import UUID

from pydantic import BaseModel


class PetFeed(BaseModel):
    """Arguments for the pet_pet_feed custom op."""
    user_id: UUID


class PetInteract(BaseModel):
    """Arguments for the pet_pet_interact custom op."""
    user_id: UUID
