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

# The one IntegrityError redeem() is entitled to reinterpret as "already
# redeemed". Checked empirically against this app's asyncpg dialect: the
# wrapped driver exception (IntegrityError.orig) carries `.sqlstate`
# directly, but the constraint name is one level deeper, on the underlying
# asyncpg UniqueViolationError (`IntegrityError.orig.__cause__`).
_DUPLICATE_REDEMPTION_SQLSTATE = "23505"
_DUPLICATE_REDEMPTION_CONSTRAINT = "uq_plan_credit_grants_family_coupon"


class CouponInvalid(Exception):
    """The code cannot be redeemed. Reason deliberately not disclosed."""


class CouponAlreadyRedeemed(Exception):
    """This family already holds a grant from this coupon."""


def _is_duplicate_redemption(exc: IntegrityError) -> bool:
    """True only for the specific UNIQUE(family_id, coupon_id) violation.

    db.commit() flushes the whole session, so a blanket ``except
    IntegrityError`` would relabel ANY unrelated constraint violation (e.g.
    a future non-route caller's own unrelated dirty rows) as "already
    redeemed" and discard its real cause. Gate on both the sqlstate AND the
    constraint name, not just the sqlstate — 23505 is "unique_violation" in
    general, not specific to this constraint.
    """
    orig = exc.orig
    if getattr(orig, "sqlstate", None) != _DUPLICATE_REDEMPTION_SQLSTATE:
        return False
    cause = getattr(orig, "__cause__", None)
    return getattr(cause, "constraint_name", None) == _DUPLICATE_REDEMPTION_CONSTRAINT


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

        # Snapshot every field this method needs, right now, while `coupon`
        # is freshly loaded. From here on the transaction can fail (a lost
        # race) and a failed flush taints the WHOLE session immediately —
        # before we even get a chance to call rollback() ourselves — so any
        # later plain `coupon.<attr>` read risks either PendingRollbackError
        # (session already tainted, not yet rolled back) or MissingGreenlet
        # (post-rollback: the attribute is expired and a reload is
        # synchronous-looking IO outside any await). Working only off local
        # variables from here sidesteps that whole class of bug.
        coupon_id = coupon.id
        coupon_code = coupon.code
        coupon_tier = coupon.tier
        coupon_duration_days = coupon.duration_days

        # Cheap pre-check for a clear error; the UNIQUE(family_id, coupon_id)
        # constraint below is the authoritative guard under concurrency.
        existing = (
            await db.execute(
                select(PlanCreditGrant.id).where(
                    PlanCreditGrant.family_id == family_id,
                    PlanCreditGrant.coupon_id == coupon_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise CouponAlreadyRedeemed(str(coupon_id))

        # Race-free cap: the UPDATE takes the row lock and re-checks the
        # predicate atomically, so two concurrent redeems of a
        # max_redemptions=1 coupon cannot both succeed. A 0-row result means
        # somebody else took the last seat.
        bumped = await db.execute(
            update(Coupon)
            .where(
                Coupon.id == coupon_id,
                or_(
                    Coupon.max_redemptions.is_(None),
                    Coupon.redemption_count < Coupon.max_redemptions,
                ),
            )
            .values(redemption_count=Coupon.redemption_count + 1)
        )
        if bumped.rowcount == 0:
            # Roll back explicitly here (unlike the earlier raises above,
            # which leave cleanup to get_db) to release the coupon row's
            # tuple lock immediately: this UPDATE re-evaluates its WHERE
            # predicate against the pre-image (EvalPlanQual) once it gets
            # the row, so holding the lock open on a hot, already-exhausted
            # coupon would needlessly serialize every other rejected
            # redeemer behind this transaction's eventual commit/timeout.
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
                tier=coupon_tier,
                duration_days=coupon_duration_days,
                coupon_id=coupon_id,
                reason=f"coupon {coupon_code}",
            )
            await db.commit()
        except IntegrityError as exc:
            if not _is_duplicate_redemption(exc):
                # Not our race: some other constraint on this transaction's
                # dirty rows. Re-raise unchanged rather than mislabeling a
                # real error as "already redeemed" and swallowing its cause.
                raise
            # Lost the concurrent race on UNIQUE(family_id, coupon_id). The
            # counter increment rolls back with it — same transaction — so no
            # seat is burned.
            await db.rollback()
            logger.info(
                "coupon %s redeemed concurrently by family %s",
                coupon_code,
                family_id,
            )
            raise CouponAlreadyRedeemed(str(coupon_id)) from exc

        await db.refresh(coupon)
        return coupon, grant
