"""Coupon redemption.

The validation matrix collapses every "you cannot use this code" reason into
ONE exception on purpose. Distinguishing "no such code" from "expired" would
turn the redeem endpoint into an oracle that confirms which codes exist, and
launch codes are human-chosen and guessable by design (LANZAMIENTO, BETA2026).
Already-redeemed is the single exception: the family can observe that state
anyway, and a uniform error there reads as a bug to the user.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan_credit import Coupon, PlanCreditGrant
from app.services.plan_credit_service import PlanCreditService

logger = logging.getLogger(__name__)


class CouponInvalid(Exception):
    """The code cannot be redeemed. Reason deliberately not disclosed."""


class CouponAlreadyRedeemed(Exception):
    """This family already holds a grant from this coupon."""


class CouponService:
    """Redeem codes into plan credit grants."""

    @staticmethod
    def normalize_code(raw: str) -> str:
        """Upper-case, trimmed. The only writer of a stored coupon code."""
        code = (raw or "").strip().upper()
        if not code:
            raise CouponInvalid("empty code")
        return code

    @staticmethod
    async def _load_redeemable(
        db: AsyncSession, code: str
    ) -> Optional[Coupon]:
        """The coupon for *code*, if it exists and is within its window.

        Case-insensitive on the stored value too: codes are normalized on
        write, but a row seeded by hand should not be silently unredeemable.
        """
        now = datetime.now(timezone.utc)
        return (
            await db.execute(
                select(Coupon).where(
                    func.upper(Coupon.code) == code,
                    Coupon.is_active == True,  # noqa: E712
                    or_(Coupon.valid_from.is_(None), Coupon.valid_from <= now),
                    or_(Coupon.valid_until.is_(None), Coupon.valid_until > now),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def redeem(
        db: AsyncSession, *, family_id: UUID, code: str
    ) -> tuple[Coupon, PlanCreditGrant]:
        """Redeem *code* for *family_id*. Commits.

        Raises CouponInvalid for every unusable-code reason and
        CouponAlreadyRedeemed when this family already holds this coupon's
        grant.
        """
        normalized = CouponService.normalize_code(code)
        coupon = await CouponService._load_redeemable(db, normalized)
        if coupon is None:
            raise CouponInvalid("no redeemable coupon for this code")

        # Cheap pre-check for a clear error; the UNIQUE(family_id, coupon_id)
        # constraint below is the authoritative guard under concurrency.
        existing = (
            await db.execute(
                select(PlanCreditGrant.id).where(
                    PlanCreditGrant.family_id == family_id,
                    PlanCreditGrant.coupon_id == coupon.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise CouponAlreadyRedeemed(str(coupon.id))

        # Race-free cap: the UPDATE takes the row lock and re-checks the
        # predicate atomically, so two concurrent redeems of a
        # max_redemptions=1 coupon cannot both succeed. A 0-row result means
        # somebody else took the last seat.
        bumped = await db.execute(
            update(Coupon)
            .where(
                Coupon.id == coupon.id,
                or_(
                    Coupon.max_redemptions.is_(None),
                    Coupon.redemption_count < Coupon.max_redemptions,
                ),
            )
            .values(redemption_count=Coupon.redemption_count + 1)
        )
        if bumped.rowcount == 0:
            await db.rollback()
            raise CouponInvalid("coupon exhausted")

        # Both the grant's own INSERT (inside PlanCreditService.grant's
        # flush) and this commit() are candidates for the race: under
        # Postgres READ COMMITTED, a concurrent INSERT that conflicts on
        # UNIQUE(family_id, coupon_id) blocks until the other transaction
        # ends, then raises the violation immediately upon unblocking — at
        # the INSERT itself, not deferred to COMMIT. So the try must wrap
        # grant() too, not just commit(), or the loser's IntegrityError
        # would escape uncaught.
        try:
            grant = await PlanCreditService.grant(
                db,
                family_id=family_id,
                source="coupon",
                tier=coupon.tier,
                duration_days=coupon.duration_days,
                coupon_id=coupon.id,
                reason=f"coupon {coupon.code}",
            )
            await db.commit()
        except IntegrityError:
            # Lost the concurrent race on UNIQUE(family_id, coupon_id). The
            # counter increment rolls back with it — same transaction — so no
            # seat is burned.
            await db.rollback()
            logger.info(
                "coupon %s redeemed concurrently by family %s",
                coupon.code,
                family_id,
            )
            raise CouponAlreadyRedeemed(str(coupon.id)) from None

        await db.refresh(coupon)
        return coupon, grant
