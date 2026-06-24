"""MCP adapters for the gigs domain (offerings + claims).

- OfferingAdapter — LGCUD over GigOffering via GigOfferingService.
- ClaimAdapter    — LGUD over GigClaim (no create; claims are initiated by
                    GigClaimService.claim which requires active user context).

Destructive ops per plan table:
  gigs.offering: delete
  gigs.claim:    delete
"""

from uuid import UUID

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.models.gig import GigClaim, GigOffering


def _ser_offering(o: GigOffering) -> dict:
    return {
        "id": str(o.id),
        "title": o.title,
        "description": o.description,
        "points": o.points,
        "difficulty": o.difficulty,
        "category": o.category.value if hasattr(o.category, "value") else str(o.category),
        "is_active": o.is_active,
        "allowed_roles": o.allowed_roles,
    }


def _ser_claim(c: GigClaim) -> dict:
    return {
        "id": str(c.id),
        "gig_id": str(c.gig_id),
        "family_id": str(c.family_id),
        "claimed_by": str(c.claimed_by),
        "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        "proof_text": c.proof_text,
        "proof_image_url": c.proof_image_url,
        "points_awarded": c.points_awarded,
        "approval_notes": c.approval_notes,
    }


class OfferingAdapter(ServiceAdapter):
    """Binds LGCUD to GigOfferingService."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.gig_offering_service import GigOfferingService
        # include_inactive=True so Jarvis can see all offerings
        enriched = await GigOfferingService.list_for_family(
            ctx.db,
            family_id=ctx.family_id,
            requesting_user_id=ctx.user_id,
            include_inactive=True,
        )
        return [_ser_offering(row["offering"]) for row in enriched]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.gig_offering_service import GigOfferingService
        return _ser_offering(
            await GigOfferingService.get_by_id(ctx.db, entity_id, ctx.family_id)
        )

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.gig_offering_service import GigOfferingService
        offering = await GigOfferingService.create(
            ctx.db,
            family_id=ctx.family_id,
            created_by=ctx.user_id,
            title=str(data["title"])[:200],
            points=int(data["points"]),
            difficulty=int(data.get("difficulty", 1)),
            category=str(data.get("category", "other")),
            description=data.get("description"),
            allowed_roles=data.get("allowed_roles"),
        )
        return _ser_offering(offering)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.gig_offering_service import GigOfferingService
        offering = await GigOfferingService.update(
            ctx.db,
            offering_id=entity_id,
            family_id=ctx.family_id,
            **{k: v for k, v in data.items() if v is not None},
        )
        return _ser_offering(offering)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        """Deactivate the offering (soft-delete) to preserve existing claims."""
        from app.services.gig_offering_service import GigOfferingService
        await GigOfferingService.deactivate(ctx.db, entity_id, ctx.family_id)


class ClaimAdapter(ServiceAdapter):
    """LGUD adapter for GigClaim (no create — claims go through GigClaimService.claim).

    All four ops delegate to GigClaimService so that family-isolation logic,
    NotFoundException handling, and future business rules remain in one place.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.gig_claim_service import GigClaimService
        claims = await GigClaimService.list_all_claims(ctx.db, family_id=ctx.family_id)
        return [_ser_claim(c) for c in claims]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.gig_claim_service import GigClaimService
        return _ser_claim(
            await GigClaimService.get_claim(ctx.db, entity_id, ctx.family_id)
        )

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        """Patch proof_text / approval_notes on a claim (parent oversight only)."""
        from app.services.gig_claim_service import GigClaimService
        claim = await GigClaimService.patch_claim(
            ctx.db,
            claim_id=entity_id,
            family_id=ctx.family_id,
            proof_text=data.get("proof_text"),
            approval_notes=data.get("approval_notes"),
        )
        return _ser_claim(claim)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        """Hard-delete a claim (parent override — use sparingly)."""
        from app.services.gig_claim_service import GigClaimService
        await GigClaimService.hard_delete_claim(ctx.db, entity_id, ctx.family_id)
