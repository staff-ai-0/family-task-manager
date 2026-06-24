"""
MCP ServiceAdapter subclasses for rewards-domain entities:
  reward (LGCUD), redemption (LC).

Family scope comes from McpContext; never from adapter arguments.
RewardService subclasses BaseFamilyService[Reward] so get/delete use
the inherited family-scoped classmethods. create/update/list use the
explicit RewardService static methods.
"""
from __future__ import annotations

from uuid import UUID

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext


# ── serializers ────────────────────────────────────────────────────────────

def _ser_reward(r) -> dict:
    return {
        "id": str(r.id),
        "title": r.title,
        "description": r.description,
        "points_cost": r.points_cost,
        "category": r.category.value if hasattr(r.category, "value") else str(r.category),
        "icon": r.icon,
        "is_active": r.is_active,
        "is_default": r.is_default,
        "requires_parent_approval": r.requires_parent_approval,
        "family_id": str(r.family_id),
    }


def _ser_redemption(t) -> dict:
    """Serialize a PointTransaction from a reward redemption."""
    return {
        "id": str(t.id),
        "type": t.type.value if hasattr(t.type, "value") else str(t.type),
        "points": t.points,
        "description": t.description,
        "user_id": str(t.user_id),
        "reward_id": str(t.reward_id) if t.reward_id else None,
        "balance_before": t.balance_before,
        "balance_after": t.balance_after,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


# ── reward ─────────────────────────────────────────────────────────────────

class RewardAdapter(ServiceAdapter):
    """Wraps RewardService (BaseFamilyService[Reward]).

    list / get / create / update / delete.
    delete is the only destructive_op (per the entity table).
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.reward_service import RewardService
        rows = await RewardService.list_rewards(ctx.db, ctx.family_id, is_active=None)
        return [_ser_reward(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.reward_service import RewardService
        return _ser_reward(await RewardService.get_reward(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.reward_service import RewardService
        from app.schemas.reward import RewardCreate
        r = await RewardService.create_reward(ctx.db, RewardCreate(**data), ctx.family_id)
        return _ser_reward(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.reward_service import RewardService
        from app.schemas.reward import RewardUpdate
        r = await RewardService.update_reward(ctx.db, entity_id, RewardUpdate(**data), ctx.family_id)
        return _ser_reward(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.reward_service import RewardService
        await RewardService.delete_reward(ctx.db, entity_id, ctx.family_id)


# ── redemption ─────────────────────────────────────────────────────────────

class RedemptionAdapter(ServiceAdapter):
    """Wraps RewardService.redeem_reward.

    list — returns PointTransaction rows of type REWARD_REDEEMED for this family.
    create — redeems a reward (money-moving op; gated in destructive_ops).
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from sqlalchemy import select
        from app.models import PointTransaction, User
        from app.models.point_transaction import TransactionType
        stmt = (
            select(PointTransaction)
            .join(User, User.id == PointTransaction.user_id)
            .where(
                User.family_id == ctx.family_id,
                PointTransaction.type == TransactionType.REWARD_REDEEMED,
            )
            .order_by(PointTransaction.created_at.desc())
            .limit(200)
        )
        result = await ctx.db.execute(stmt)
        rows = list(result.scalars().all())
        return [_ser_redemption(r) for r in rows]

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.reward_service import RewardService
        payload = dict(data)
        reward_id = UUID(payload["reward_id"]) if isinstance(payload.get("reward_id"), str) else payload["reward_id"]
        user_id = UUID(payload["user_id"]) if isinstance(payload.get("user_id"), str) else payload["user_id"]
        txn = await RewardService.redeem_reward(
            db=ctx.db,
            reward_id=reward_id,
            user_id=user_id,
            family_id=ctx.family_id,
        )
        return _ser_redemption(txn)
