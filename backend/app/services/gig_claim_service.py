from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from app.models.gig import GigClaim, GigClaimStatus, GigOffering
from app.models.point_transaction import PointTransaction
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)


async def _get_user(db: AsyncSession, user_id: UUID):
    from app.models.user import User
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundException(f"User {user_id} not found")
    return user


class GigClaimService:

    @staticmethod
    async def claim(
        db: AsyncSession,
        gig_id: UUID,
        user_id: UUID,
        family_id: UUID,
    ) -> GigClaim:
        """Create a new claim. Raises 409-like ValidationException if active claim exists."""
        # Verify offering exists and is active
        result = await db.execute(
            select(GigOffering).where(
                and_(
                    GigOffering.id == gig_id,
                    GigOffering.family_id == family_id,
                    GigOffering.is_active == True,
                )
            )
        )
        offering = result.scalar_one_or_none()
        if not offering:
            raise NotFoundException(f"Gig offering {gig_id} not found or not active")

        # Check allowed_roles
        user = await _get_user(db, user_id)
        if offering.allowed_roles and user.role.value not in offering.allowed_roles:
            raise ForbiddenException("Tu rol no puede reclamar esta gig")

        # Check no active (non-rejected) claim already exists for this user+gig
        existing = await db.execute(
            select(GigClaim).where(
                and_(
                    GigClaim.gig_id == gig_id,
                    GigClaim.claimed_by == user_id,
                    GigClaim.status != GigClaimStatus.REJECTED,
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValidationException("Ya tienes un reclamo activo para esta gig")

        claim = GigClaim(
            gig_id=gig_id,
            family_id=family_id,
            claimed_by=user_id,
            status=GigClaimStatus.CLAIMED,
        )
        db.add(claim)
        await db.commit()
        await db.refresh(claim)
        return claim

    @staticmethod
    async def complete(
        db: AsyncSession,
        claim_id: UUID,
        user_id: UUID,
        proof_text: Optional[str] = None,
        proof_image_url: Optional[str] = None,
    ) -> GigClaim:
        """Submit proof and move claim to COMPLETED."""
        result = await db.execute(
            select(GigClaim).where(
                and_(GigClaim.id == claim_id, GigClaim.claimed_by == user_id)
            )
        )
        claim = result.scalar_one_or_none()
        if not claim:
            raise NotFoundException(f"Claim {claim_id} not found")
        if claim.status != GigClaimStatus.CLAIMED:
            raise ValidationException(f"Claim is {claim.status.value}, expected claimed")

        claim.proof_text = proof_text
        claim.proof_image_url = proof_image_url
        claim.status = GigClaimStatus.COMPLETED
        claim.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(claim)
        return claim

    @staticmethod
    async def unclaim(
        db: AsyncSession,
        claim_id: UUID,
        user_id: UUID,
    ) -> None:
        """Delete a CLAIMED (not yet submitted) claim."""
        result = await db.execute(
            select(GigClaim).where(
                and_(GigClaim.id == claim_id, GigClaim.claimed_by == user_id)
            )
        )
        claim = result.scalar_one_or_none()
        if not claim:
            raise NotFoundException(f"Claim {claim_id} not found")
        if claim.status != GigClaimStatus.CLAIMED:
            raise ValidationException("Only CLAIMED (not yet submitted) claims can be unclaimed")

        await db.delete(claim)
        await db.commit()

    @staticmethod
    async def get_my_claims(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
    ) -> List[GigClaim]:
        result = await db.execute(
            select(GigClaim).where(
                and_(
                    GigClaim.claimed_by == user_id,
                    GigClaim.family_id == family_id,
                )
            ).order_by(GigClaim.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def get_pending_approvals(
        db: AsyncSession,
        family_id: UUID,
    ) -> List[dict]:
        """Return COMPLETED claims enriched with claimer name and gig title."""
        from app.models.user import User
        from sqlalchemy.orm import joinedload

        result = await db.execute(
            select(GigClaim)
            .options(
                joinedload(GigClaim.offering),
                joinedload(GigClaim.claimer),
            )
            .where(
                and_(
                    GigClaim.family_id == family_id,
                    GigClaim.status == GigClaimStatus.COMPLETED,
                )
            ).order_by(GigClaim.completed_at.asc())
        )
        claims = result.unique().scalars().all()
        return [
            {
                "claim": c,
                "claimer_name": c.claimer.name if c.claimer else str(c.claimed_by),
                "gig_title": c.offering.title if c.offering else "—",
                "gig_points": c.offering.points if c.offering else 0,
            }
            for c in claims
        ]

    @staticmethod
    async def get_my_claims_enriched(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
    ) -> List[dict]:
        """Return the user's claims enriched with the offering title and points."""
        from sqlalchemy.orm import joinedload

        result = await db.execute(
            select(GigClaim)
            .options(joinedload(GigClaim.offering))
            .where(
                and_(
                    GigClaim.claimed_by == user_id,
                    GigClaim.family_id == family_id,
                )
            ).order_by(GigClaim.created_at.desc())
        )
        claims = result.unique().scalars().all()
        return [
            {
                "claim": c,
                "gig_title": c.offering.title if c.offering else "—",
                "gig_points": c.offering.points if c.offering else 0,
            }
            for c in claims
        ]

    @staticmethod
    async def approve(
        db: AsyncSession,
        claim_id: UUID,
        approver_id: UUID,
        family_id: UUID,
        approved: bool,
        notes: Optional[str] = None,
    ) -> GigClaim:
        from app.models.user import UserRole

        approver = await _get_user(db, approver_id)
        if approver.family_id != family_id or approver.role != UserRole.PARENT:
            raise ForbiddenException("Solo padres pueden aprobar gigs")

        result = await db.execute(
            select(GigClaim).where(
                and_(GigClaim.id == claim_id, GigClaim.family_id == family_id)
            )
        )
        claim = result.scalar_one_or_none()
        if not claim:
            raise NotFoundException(f"Claim {claim_id} not found")
        if claim.status != GigClaimStatus.COMPLETED:
            raise ValidationException(
                f"Claim is {claim.status.value}, expected completed"
            )

        claim.approved_by = approver_id
        claim.approved_at = datetime.now(timezone.utc)
        claim.approval_notes = notes

        if approved:
            # Load offering for points value
            offering = await db.get(GigOffering, claim.gig_id)
            points = offering.points

            claimer = await _get_user(db, claim.claimed_by)
            txn = PointTransaction.create_gig_claim_approval(
                user_id=claim.claimed_by,
                gig_claim_id=claim.id,
                points=points,
                balance_before=claimer.points,
            )
            claimer.points += points
            claim.points_awarded = points
            claim.status = GigClaimStatus.APPROVED
            db.add(txn)

            # Push notification
            try:
                from app.services.notification_service import NotificationService
                from app.models.notification import NotificationType as NT
                await db.commit()
                await NotificationService.create(
                    db,
                    family_id=family_id,
                    user_id=claim.claimed_by,
                    type=NT.GIG_APPROVED,
                    title=f"✅ +{points} pts / ${points} MXN",
                    body=f"'{offering.title}' aprobada por tu padre/madre.",
                    link="/gigs/my-gigs",
                )
            except Exception:
                pass
        else:
            claim.status = GigClaimStatus.REJECTED

        await db.commit()
        await db.refresh(claim)
        return claim
