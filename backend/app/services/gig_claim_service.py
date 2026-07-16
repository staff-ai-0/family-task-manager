from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID
from datetime import date, datetime, timezone

from app.models.gig import GigClaim, GigClaimStatus, GigOffering
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

        # Single-slot gigs (the default): first come, first serve — block a
        # second kid from claiming a gig someone else is already doing, so two
        # siblings can't both do the work and expect double pay.
        if not offering.allow_multiple:
            from app.models.user import User as _User
            taken_by = (
                await db.execute(
                    select(_User.name)
                    .join(GigClaim, GigClaim.claimed_by == _User.id)
                    .where(
                        and_(
                            GigClaim.gig_id == gig_id,
                            GigClaim.claimed_by != user_id,
                            GigClaim.status.in_(
                                [GigClaimStatus.CLAIMED, GigClaimStatus.COMPLETED]
                            ),
                        )
                    )
                )
            ).scalars().first()
            if taken_by:
                raise ValidationException(f"{taken_by} ya está haciendo esta gig")

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
        """Submit proof. Auto-approves for trusted kids; otherwise moves to
        COMPLETED and notifies parents that a gig awaits review."""
        from app.core.config import settings

        # Lock the row: two concurrent proof submissions on the same claim must
        # not both reach the auto-approve branch and double-award points.
        result = await db.execute(
            select(GigClaim)
            .where(and_(GigClaim.id == claim_id, GigClaim.claimed_by == user_id))
            .with_for_update()
        )
        claim = result.scalar_one_or_none()
        if not claim:
            raise NotFoundException(f"Claim {claim_id} not found")
        if claim.status != GigClaimStatus.CLAIMED:
            raise ValidationException(f"Claim is {claim.status.value}, expected claimed")

        claim.proof_text = proof_text
        claim.proof_image_url = proof_image_url
        claim.completed_at = datetime.now(timezone.utc)

        claimer = await _get_user(db, claim.claimed_by)
        offering = await db.get(GigOffering, claim.gig_id)

        threshold = max(1, settings.GIG_AUTO_APPROVE_STREAK)
        if claimer.gig_trust_streak >= threshold:
            # Trusted kid — auto-approve on submission, award CASH immediately.
            # Gigs pay money (1 pt = $1 MXN = 100 centavos), not privilege points.
            from app.services.cash_service import CashService
            pesos = offering.points if offering else 0
            await CashService.award_gig_cash(
                db, claim.claimed_by, claim.family_id, None, pesos * 100,
                description=f"Gig: {offering.title if offering else 'Gig'}",
                gig_claim_id=claim.id,
            )
            claimer.gig_trust_streak += 1
            claim.points_awarded = pesos
            claim.status = GigClaimStatus.APPROVED
            claim.approved_at = datetime.now(timezone.utc)
            released = await GigClaimService._release_other_claims(
                db, offering, claim, claimer.name
            )
            await db.commit()
            await db.refresh(claim)
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(claim.family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            await GigClaimService._notify_claimer_approved(
                db, claim, offering, pesos, auto=True
            )
            await GigClaimService._notify_released(db, released, offering, claimer.name)
            return claim

        # Normal path — awaits parent review.
        claim.status = GigClaimStatus.COMPLETED
        await db.commit()
        await db.refresh(claim)
        await GigClaimService._notify_parents_pending(db, claim, offering, claimer)
        return claim

    @staticmethod
    async def _release_other_claims(db, offering, winning_claim, winner_name) -> list:
        """Single-slot gigs: the first APPROVED claim closes the offering and
        releases every other active claim, so the family never pays twice for
        the same job (2026-07-16 double-pay incident). Released kids keep their
        trust streak — it's not their fault. Caller commits + notifies after."""
        if not offering or offering.allow_multiple:
            return []
        offering.is_active = False
        result = await db.execute(
            select(GigClaim)
            .where(
                and_(
                    GigClaim.gig_id == offering.id,
                    GigClaim.id != winning_claim.id,
                    GigClaim.status.in_(
                        [GigClaimStatus.CLAIMED, GigClaimStatus.COMPLETED]
                    ),
                )
            )
            .with_for_update()
        )
        released = list(result.scalars().all())
        for other in released:
            other.status = GigClaimStatus.REJECTED
            other.approval_notes = f"Auto: {winner_name} completó esta gig primero"
        return released

    @staticmethod
    async def _notify_released(db, released, offering, winner_name) -> None:
        """Best-effort in-app notice to kids whose claims were auto-released."""
        if not released:
            return
        try:
            from app.services.notification_service import NotificationService

            for other in released:
                await NotificationService.create_localized(
                    db,
                    family_id=other.family_id,
                    key="gig_claim_released",
                    user_id=other.claimed_by,
                    params={
                        "title": offering.title if offering else "Gig",
                        "winner": winner_name,
                    },
                    link="/gigs",
                )
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "gig release notification failed", exc_info=True
            )

    @staticmethod
    async def _notify_parents_pending(db, claim, offering, claimer) -> None:
        """In-app + push to every parent that a gig awaits review."""
        try:
            from app.services.notification_service import NotificationService
            from app.models.user import User, UserRole

            parents = (
                await db.scalars(
                    select(User).where(
                        and_(
                            User.family_id == claim.family_id,
                            User.role == UserRole.PARENT,
                            User.is_active.is_(True),
                        )
                    )
                )
            ).all()
            title = offering.title if offering else "Gig"
            for parent in parents:
                await NotificationService.create_localized(
                    db,
                    family_id=claim.family_id,
                    key="gig_claim_pending",
                    user_id=parent.id,
                    params={"claimer": claimer.name, "title": title},
                    link="/parent/approvals",
                    lang=getattr(parent, "preferred_lang", None) or "es",
                )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "notify parents of pending gig failed", exc_info=True
            )

    @staticmethod
    async def _notify_claimer_approved(db, claim, offering, pesos, auto=False) -> None:
        try:
            from app.services.notification_service import NotificationService

            title = offering.title if offering else "Gig"
            await NotificationService.create_localized(
                db,
                family_id=claim.family_id,
                key="gig_claim_approved_auto" if auto else "gig_claim_approved",
                user_id=claim.claimed_by,
                params={"pesos": pesos, "title": title},
                link="/gigs/my-gigs",
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "notify claimer of gig approval failed", exc_info=True
            )

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

    # ------------------------------------------------------------------
    # MCP / Jarvis helpers — family-scoped, suitable for parent oversight
    # ------------------------------------------------------------------

    @staticmethod
    async def list_all_claims(
        db: AsyncSession,
        family_id: UUID,
        limit: int = 100,
    ) -> List[GigClaim]:
        """Return all claims for the family (newest first).  Used by ClaimAdapter."""
        result = await db.execute(
            select(GigClaim)
            .where(GigClaim.family_id == family_id)
            .order_by(GigClaim.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_claim(
        db: AsyncSession,
        claim_id: UUID,
        family_id: UUID,
    ) -> GigClaim:
        """Fetch a single claim with family-scope guard.  Raises NotFoundException."""
        result = await db.execute(
            select(GigClaim).where(
                and_(GigClaim.id == claim_id, GigClaim.family_id == family_id)
            )
        )
        claim = result.scalar_one_or_none()
        if not claim:
            raise NotFoundException(f"Claim {claim_id} not found")
        return claim

    @staticmethod
    async def patch_claim(
        db: AsyncSession,
        claim_id: UUID,
        family_id: UUID,
        proof_text: Optional[str] = None,
        approval_notes: Optional[str] = None,
    ) -> GigClaim:
        """Patch proof_text / approval_notes on a claim (parent oversight).
        Only the fields explicitly passed (not None) are written."""
        claim = await GigClaimService.get_claim(db, claim_id, family_id)

        if proof_text is not None:
            claim.proof_text = proof_text
        if approval_notes is not None:
            claim.approval_notes = approval_notes

        await db.commit()
        await db.refresh(claim)
        return claim

    @staticmethod
    async def hard_delete_claim(
        db: AsyncSession,
        claim_id: UUID,
        family_id: UUID,
    ) -> None:
        """Hard-delete a claim (parent override).  Raises NotFoundException if absent."""
        claim = await GigClaimService.get_claim(db, claim_id, family_id)
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

        # Duplicate-pay guardrail: if any of these gigs already has an APPROVED
        # claim, surface who got paid so the approving parent sees a warning
        # ("ya le pagaste esto a Ariana") instead of blind-approving a dup.
        awarded_map: dict = {}
        gig_ids = {c.gig_id for c in claims}
        if gig_ids:
            rows = await db.execute(
                select(GigClaim.gig_id, User.name)
                .join(User, User.id == GigClaim.claimed_by)
                .where(
                    and_(
                        GigClaim.gig_id.in_(gig_ids),
                        GigClaim.status == GigClaimStatus.APPROVED,
                    )
                )
            )
            for gid, name in rows.all():
                awarded_map.setdefault(gid, name)

        return [
            {
                "claim": c,
                "claimer_name": c.claimer.name if c.claimer else str(c.claimed_by),
                "gig_title": c.offering.title if c.offering else "—",
                "gig_points": c.offering.points if c.offering else 0,
                "already_awarded_to": awarded_map.get(c.gig_id),
            }
            for c in claims
        ]

    @staticmethod
    async def list_family_claims(
        db: AsyncSession,
        family_id: UUID,
        on: Optional[date] = None,
    ) -> List[dict]:
        """Every claim in the family (parent oversight / per-day review),
        optionally narrowed to one UTC day — matched on the claim's most
        meaningful timestamp: approved_at → completed_at → created_at."""
        from sqlalchemy import func as sa_func
        from sqlalchemy.orm import joinedload

        stmt = (
            select(GigClaim)
            .options(
                joinedload(GigClaim.offering),
                joinedload(GigClaim.claimer),
            )
            .where(GigClaim.family_id == family_id)
        )
        if on is not None:
            stamp = sa_func.coalesce(
                GigClaim.approved_at, GigClaim.completed_at, GigClaim.created_at
            )
            stmt = stmt.where(sa_func.date(stamp) == on)
        stmt = stmt.order_by(GigClaim.created_at.desc()).limit(200)

        result = await db.execute(stmt)
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

        # Lock the row: two concurrent approvals of the same claim must not
        # both pass the status check and double-award points.
        result = await db.execute(
            select(GigClaim)
            .where(and_(GigClaim.id == claim_id, GigClaim.family_id == family_id))
            .with_for_update()
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

        offering = await db.get(GigOffering, claim.gig_id)
        claimer = await _get_user(db, claim.claimed_by)

        if approved:
            # Gigs pay CASH (1 pt = $1 MXN = 100 centavos), not privilege points.
            from app.services.cash_service import CashService
            pesos = offering.points if offering else 0
            await CashService.award_gig_cash(
                db, claim.claimed_by, family_id, None, pesos * 100,
                description=f"Gig: {offering.title if offering else 'Gig'}",
                gig_claim_id=claim.id,
            )
            # Build trust toward auto-approval on future gigs.
            claimer.gig_trust_streak += 1
            claim.points_awarded = pesos
            claim.status = GigClaimStatus.APPROVED
            released = await GigClaimService._release_other_claims(
                db, offering, claim, claimer.name
            )
            await db.commit()
            await db.refresh(claim)
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(claim.family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            await GigClaimService._notify_claimer_approved(
                db, claim, offering, pesos, auto=False
            )
            await GigClaimService._notify_released(db, released, offering, claimer.name)
            return claim
        else:
            # Rejection breaks the trust streak.
            claimer.gig_trust_streak = 0
            claim.status = GigClaimStatus.REJECTED
            await db.commit()
            await db.refresh(claim)
            try:
                from app.services.notification_service import NotificationService
                await NotificationService.create_localized(
                    db,
                    family_id=family_id,
                    key="gig_claim_rejected",
                    user_id=claim.claimed_by,
                    params={
                        "reason": notes
                        or (offering.title if offering else "Tu gig"),
                    },
                    link="/gigs/my-gigs",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "notify claimer of gig rejection failed", exc_info=True
                )
            return claim
