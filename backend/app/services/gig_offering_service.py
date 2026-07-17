from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from app.models.gig import GigOffering, GigClaimStatus, GigOfferingStatus
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
)


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

        # Batch-load who currently holds an ACTIVE claim on each offering, so
        # the board can show "Ariana ya la está haciendo" before a sibling
        # claims (or gets blocked on) a single-slot gig.
        claimers_map: dict[UUID, list] = {}
        if offering_ids:
            from app.models.user import User
            rows = await db.execute(
                select(GigClaim.gig_id, User.name)
                .join(User, User.id == GigClaim.claimed_by)
                .where(
                    and_(
                        GigClaim.gig_id.in_(offering_ids),
                        GigClaim.status.in_(
                            [GigClaimStatus.CLAIMED, GigClaimStatus.COMPLETED]
                        ),
                    )
                )
            )
            for gid, name in rows.all():
                claimers_map.setdefault(gid, []).append(name)

        enriched = []
        for offering in offerings:
            claim = claim_map.get(offering.id)
            enriched.append({
                "offering": offering,
                "my_claim": claim,
                "active_claimers": claimers_map.get(offering.id, []),
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
        allow_multiple: bool = False,
        payout_cadence: str = "immediate",
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
            allow_multiple=allow_multiple,
            payout_cadence=payout_cadence,
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
        acting_user_id: Optional[UUID] = None,
        **fields,
    ) -> GigOffering:
        offering = await GigOfferingService.get_by_id(db, offering_id, family_id)

        # A parent flipping a pending/rejected kid proposal live via the
        # generic edit path is an IMPLICIT APPROVAL — without this, the gig
        # became claimable while the kid's "Mis propuestas" still showed it
        # as pending/rejected and no decision notification went out. Stamp
        # the review fields and notify the proposer, mirroring
        # review_proposal().
        implicit_approval = (
            fields.get("is_active") is True
            and offering.status != GigOfferingStatus.APPROVED.value
        )

        for key, value in fields.items():
            if hasattr(offering, key) and value is not None:
                setattr(offering, key, value)
        if implicit_approval:
            offering.status = GigOfferingStatus.APPROVED.value
            offering.reviewed_by = acting_user_id
            offering.reviewed_at = datetime.now(timezone.utc)
        offering.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(offering)

        if (
            implicit_approval
            and offering.created_by
            and offering.created_by != acting_user_id
        ):
            try:
                from app.models.user import User
                from app.services.notification_service import NotificationService

                kid = await db.get(User, offering.created_by)
                await NotificationService.create_localized(
                    db,
                    family_id=family_id,
                    key="gig_proposal_approved",
                    user_id=offering.created_by,
                    params={
                        "title": offering.title,
                        "pesos": offering.points,
                        "notes": "",
                    },
                    link="/gigs",
                    lang=getattr(kid, "preferred_lang", None) or "es",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "notify kid of implicit proposal approval failed",
                    exc_info=True,
                )
        return offering

    @staticmethod
    async def deactivate(db: AsyncSession, offering_id: UUID, family_id: UUID) -> GigOffering:
        offering = await GigOfferingService.get_by_id(db, offering_id, family_id)
        offering.is_active = False
        offering.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(offering)
        return offering

    # ── Kid-proposed gigs (W4.4) ────────────────────────────────────────

    @staticmethod
    async def propose(
        db: AsyncSession,
        family_id: UUID,
        created_by: UUID,
        title: str,
        points: int,
        description: Optional[str] = None,
        category: str = "other",
        difficulty: int = 1,
    ) -> GigOffering:
        """Create a DRAFT offering (status='pending', is_active=False) from a
        TEEN/CHILD and notify the parents. It never shows on the board and is
        never claimable until a parent approves it via review_proposal()."""
        offering = GigOffering(
            family_id=family_id,
            created_by=created_by,
            title=title,
            description=description,
            points=points,
            difficulty=difficulty,
            category=category,
            status=GigOfferingStatus.PENDING.value,
            is_active=False,
        )
        db.add(offering)
        await db.commit()
        await db.refresh(offering)

        # HITL heads-up to every active parent (mirrors GigClaimService's
        # pending-review pattern). Best-effort — a notification failure must
        # never lose the proposal.
        try:
            from app.models.user import User, UserRole
            from app.services.notification_service import NotificationService

            proposer = await db.get(User, created_by)
            parents = (
                await db.scalars(
                    select(User).where(
                        and_(
                            User.family_id == family_id,
                            User.role == UserRole.PARENT,
                            User.is_active.is_(True),
                        )
                    )
                )
            ).all()
            for parent in parents:
                await NotificationService.create_localized(
                    db,
                    family_id=family_id,
                    key="gig_proposal_pending",
                    user_id=parent.id,
                    params={
                        "child": proposer.name if proposer else "",
                        "title": title,
                        "pesos": points,
                    },
                    link="/parent/gigs",
                    lang=getattr(parent, "preferred_lang", None) or "es",
                )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "notify parents of gig proposal failed", exc_info=True
            )
        return offering

    @staticmethod
    async def list_my_proposals(
        db: AsyncSession, family_id: UUID, user_id: UUID
    ) -> List[GigOffering]:
        """The kid's own pending/rejected proposals (newest first). Approved
        ones are excluded — they already appear on the board itself."""
        result = await db.execute(
            select(GigOffering)
            .where(
                and_(
                    GigOffering.family_id == family_id,
                    GigOffering.created_by == user_id,
                    GigOffering.status != GigOfferingStatus.APPROVED.value,
                )
            )
            .order_by(GigOffering.created_at.desc())
            .limit(50)
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_pending_proposals(db: AsyncSession, family_id: UUID) -> List[dict]:
        """Pending kid proposals enriched with the proposer's name (parents'
        review queue)."""
        from app.models.user import User

        result = await db.execute(
            select(GigOffering, User.name)
            .join(User, User.id == GigOffering.created_by, isouter=True)
            .where(
                and_(
                    GigOffering.family_id == family_id,
                    GigOffering.status == GigOfferingStatus.PENDING.value,
                )
            )
            .order_by(GigOffering.created_at.asc())
        )
        return [
            {"offering": offering, "proposer_name": name or ""}
            for offering, name in result.all()
        ]

    @staticmethod
    async def review_proposal(
        db: AsyncSession,
        offering_id: UUID,
        family_id: UUID,
        reviewer_id: UUID,
        approve: bool,
        title: Optional[str] = None,
        description: Optional[str] = None,
        points: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> GigOffering:
        """Parent decision on a kid proposal. Approve (optionally editing
        title/description/points) puts it live on the board; reject archives
        it with the parent's note. Notifies the proposer either way."""
        offering = await GigOfferingService.get_by_id(db, offering_id, family_id)
        if offering.status != GigOfferingStatus.PENDING.value:
            raise ValidationException(
                f"Proposal already decided (status: {offering.status})"
            )

        if approve:
            if title:
                offering.title = title
            if description is not None:
                offering.description = description
            if points is not None:
                offering.points = points
            offering.status = GigOfferingStatus.APPROVED.value
            offering.is_active = True
        else:
            offering.status = GigOfferingStatus.REJECTED.value
            offering.is_active = False

        offering.review_notes = notes
        offering.reviewed_by = reviewer_id
        offering.reviewed_at = datetime.now(timezone.utc)
        offering.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(offering)

        # Tell the kid the outcome. Best-effort.
        if offering.created_by:
            try:
                from app.models.user import User
                from app.services.notification_service import NotificationService

                kid = await db.get(User, offering.created_by)
                await NotificationService.create_localized(
                    db,
                    family_id=family_id,
                    key=(
                        "gig_proposal_approved" if approve
                        else "gig_proposal_rejected"
                    ),
                    user_id=offering.created_by,
                    params={
                        "title": offering.title,
                        "pesos": offering.points,
                        "notes": notes or "",
                    },
                    link="/gigs",
                    lang=getattr(kid, "preferred_lang", None) or "es",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "notify kid of proposal decision failed", exc_info=True
                )
        return offering
