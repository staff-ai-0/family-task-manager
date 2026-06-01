from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from app.models.gig import GigOffering, GigClaimStatus
from app.core.exceptions import NotFoundException, ForbiddenException


class GigOfferingService:

    @staticmethod
    async def list_for_family(
        db: AsyncSession,
        family_id: UUID,
        requesting_user_id: UUID,
        include_inactive: bool = False,
    ) -> List[dict]:
        """List offerings enriched with the requesting user's active claim status."""
        from app.models.gig import GigClaim

        stmt = select(GigOffering).where(
            GigOffering.family_id == family_id,
        )
        if not include_inactive:
            stmt = stmt.where(GigOffering.is_active == True)
        stmt = stmt.order_by(GigOffering.created_at.desc())

        result = await db.execute(stmt)
        offerings = result.scalars().all()

        # Batch-load the requesting user's non-rejected claims for these offerings
        offering_ids = [o.id for o in offerings]
        claim_map: dict[UUID, GigClaim] = {}
        if offering_ids:
            claim_stmt = select(GigClaim).where(
                and_(
                    GigClaim.gig_id.in_(offering_ids),
                    GigClaim.claimed_by == requesting_user_id,
                    GigClaim.status != GigClaimStatus.REJECTED,
                )
            )
            claim_result = await db.execute(claim_stmt)
            for claim in claim_result.scalars():
                claim_map[claim.gig_id] = claim

        enriched = []
        for offering in offerings:
            claim = claim_map.get(offering.id)
            enriched.append({
                "offering": offering,
                "my_claim": claim,
            })
        return enriched

    @staticmethod
    async def get_by_id(db: AsyncSession, offering_id: UUID, family_id: UUID) -> GigOffering:
        result = await db.execute(
            select(GigOffering).where(
                and_(GigOffering.id == offering_id, GigOffering.family_id == family_id)
            )
        )
        offering = result.scalar_one_or_none()
        if not offering:
            raise NotFoundException(f"Gig offering {offering_id} not found")
        return offering

    @staticmethod
    async def create(
        db: AsyncSession,
        family_id: UUID,
        created_by: UUID,
        title: str,
        points: int,
        difficulty: int = 1,
        category: str = "other",
        description: Optional[str] = None,
        allowed_roles: Optional[list] = None,
    ) -> GigOffering:
        offering = GigOffering(
            family_id=family_id,
            created_by=created_by,
            title=title,
            description=description,
            points=points,
            difficulty=difficulty,
            category=category,
            allowed_roles=allowed_roles,
        )
        db.add(offering)
        await db.commit()
        await db.refresh(offering)
        return offering

    @staticmethod
    async def update(
        db: AsyncSession,
        offering_id: UUID,
        family_id: UUID,
        **fields,
    ) -> GigOffering:
        offering = await GigOfferingService.get_by_id(db, offering_id, family_id)
        for key, value in fields.items():
            if hasattr(offering, key) and value is not None:
                setattr(offering, key, value)
        offering.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(offering)
        return offering

    @staticmethod
    async def deactivate(db: AsyncSession, offering_id: UUID, family_id: UUID) -> GigOffering:
        offering = await GigOfferingService.get_by_id(db, offering_id, family_id)
        offering.is_active = False
        offering.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(offering)
        return offering
