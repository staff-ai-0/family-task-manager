"""MCP ServiceAdapter subclasses for the pet domain.

Pet domain exposes:
  list     — all pets owned by users in this family (via family-scoped user join)
  get      — get one pet by pet.id
  feed     — custom op: calls PetService.feed(db, user_id); lowers hunger
  interact — custom op: calls PetService.play(db, user_id); boosts mood

No create/update/delete via MCP: pets are created via PetService.create_for_user
(UI flow) and are never deleted through Jarvis.

The feed and interact ops are custom (not in the standard list/get/create/update/delete
set); dispatch routes them through adapter.call_custom(op, ctx, args).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext


def _ser_pet(pet) -> dict:
    return {
        "id": str(pet.id),
        "user_id": str(pet.user_id),
        "name": pet.name,
        "species": pet.species,
        "mood": pet.mood,
        "hunger": pet.hunger,
        "xp": pet.xp,
        "level": pet.level,
        "status_label": pet.status_label,
        "last_decay_at": pet.last_decay_at.isoformat() if pet.last_decay_at else None,
        "created_at": pet.created_at.isoformat() if pet.created_at else None,
    }


class PetAdapter(ServiceAdapter):
    """Wraps PetService for list/get and custom feed/interact ops.

    Family scope: KidPet is user-scoped, not family-scoped. We join through
    users to restrict to this family.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.models.kid_pet import KidPet
        from app.models.user import User
        stmt = (
            select(KidPet)
            .join(User, User.id == KidPet.user_id)
            .where(User.family_id == ctx.family_id)
        )
        rows = list((await ctx.db.execute(stmt)).scalars().all())
        return [_ser_pet(p) for p in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.models.kid_pet import KidPet
        from app.models.user import User
        stmt = (
            select(KidPet)
            .join(User, User.id == KidPet.user_id)
            .where(KidPet.id == entity_id, User.family_id == ctx.family_id)
        )
        pet = (await ctx.db.execute(stmt)).scalar_one_or_none()
        if pet is None:
            raise ValueError("Pet not found")
        return _ser_pet(pet)

    async def call_custom(self, op: str, ctx: McpContext, args: dict) -> dict:
        """Handle non-standard ops: feed, interact."""
        from app.services.pet_service import PetService
        user_id = UUID(args["user_id"]) if isinstance(args.get("user_id"), str) else args["user_id"]

        # Verify the user belongs to this family before acting.
        from app.models.user import User
        from sqlalchemy import select as sa_select
        user_row = (await ctx.db.execute(
            sa_select(User).where(User.id == user_id, User.family_id == ctx.family_id)
        )).scalar_one_or_none()
        if user_row is None:
            raise ValueError("User not found in this family")

        if op == "feed":
            pet = await PetService.feed(ctx.db, user_id)
        elif op == "interact":
            pet = await PetService.play(ctx.db, user_id)
        else:
            raise ValueError(f"Unknown custom op: {op}")

        return _ser_pet(pet)
