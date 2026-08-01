"""Referral program service.

Owns the give-a-month/get-a-month growth loop:

- Stable per-family referral codes (generated on demand, unique).
- Recording a referral when a new family registers with ``?ref=CODE``.
- Granting BOTH families a 30-day Plus reward as an INTERNAL credit only,
  never a PayPal charge. The credit is a ``PlanCreditGrant`` row (source=
  "referral") — see ``app/services/plan_credit_service.py``, which owns all
  the window math: credits stack additively (a prolific referrer accumulates
  days across many successful referrals) and, for a payer, begin AFTER their
  already-paid period so the reward is genuinely additive rather than spent
  in parallel with time already bought. Nothing here ever mutates a
  PayPal-linked column, so the nightly PayPal reconcile sweep
  (``subscription_sweep.reconcile_with_paypal``, which overwrites
  ``current_period_end`` from PayPal's ``next_billing_at``) can never erase
  the reward, and a live paying subscription is left completely untouched
  (no clobbered period, no severed linkage).

Guards (a family can be referred only once, no self-referral, code must
exist) are enforced here and, for the once-only rule, by the
``uq_referrals_referred_family`` unique constraint.
"""
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.models.referral import Referral

logger = logging.getLogger(__name__)

# Give-a-month / get-a-month: each side of a successful referral gets 30 days.
REFERRAL_REWARD_DAYS = 30

# Referral codes: 8 chars, uppercase alphanumeric, ambiguous chars removed
# (same alphabet as join codes but longer, so the two are visually distinct
# and collisions are astronomically unlikely).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def generate_referral_code(length: int = _CODE_LENGTH) -> str:
    """Generate a short, human-readable, unambiguous referral code."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


class ReferralService:
    """Referral code management, recording, and reward application."""

    # ------------------------------------------------------------------
    # Codes
    # ------------------------------------------------------------------
    @staticmethod
    async def get_or_create_referral_code(
        db: AsyncSession, family_id: UUID
    ) -> Optional[str]:
        """Return the family's referral code, generating + persisting one on
        first use. Retries on the (astronomically unlikely) unique collision.
        Returns None only if the family row does not exist.
        """
        family = (
            await db.execute(select(Family).where(Family.id == family_id))
        ).scalar_one_or_none()
        if family is None:
            return None
        if family.referral_code:
            return family.referral_code

        # Generate a unique code, committing with a retry on the rare collision.
        # The commit is intentional: this is called from GET /api/referrals/me,
        # whose handler has no other pending writes, so persisting the freshly
        # generated code on this GET is the whole point (the code must be
        # stable across views). If a future caller batches other mutations
        # into the same session before this runs, give it a dedicated session.
        for _ in range(6):
            code = generate_referral_code()
            family.referral_code = code
            try:
                await db.commit()
                await db.refresh(family)
                return family.referral_code
            except IntegrityError:
                await db.rollback()
                # Reload — another request may have set it concurrently.
                family = (
                    await db.execute(
                        select(Family).where(Family.id == family_id)
                    )
                ).scalar_one_or_none()
                if family is None:
                    return None
                if family.referral_code:
                    return family.referral_code
        logger.error(
            "Could not generate a unique referral code for family %s", family_id
        )
        return None

    @staticmethod
    async def get_family_by_referral_code(
        db: AsyncSession, code: str
    ) -> Optional[Family]:
        """Resolve the family that owns *code* (case-insensitive), if any.

        Soft-deleted families are excluded — a closed family cannot refer.
        """
        if not code:
            return None
        normalized = code.strip().upper()
        if not normalized:
            return None
        return (
            await db.execute(
                select(Family).where(
                    func.upper(Family.referral_code) == normalized,
                    Family.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Recording + reward
    # ------------------------------------------------------------------
    @staticmethod
    async def record_referral_and_reward(
        db: AsyncSession,
        referrer_family_id: UUID,
        referred_family_id: UUID,
    ) -> Optional[Referral]:
        """Record a referral and credit BOTH families 30 days of Plus.

        Idempotent + guarded:
        - self-referral (referrer == referred) → returns None, no changes.
        - referred family already referred once → returns None, no changes.
        Both the Referral row and the two subscription credits commit in a
        single transaction, so a family is never credited without the row
        (and vice versa). Returns the created Referral, or None if guarded.
        """
        # Self-referral guard.
        if referrer_family_id == referred_family_id:
            logger.info(
                "Referral rejected: self-referral for family %s",
                referrer_family_id,
            )
            return None

        # Double-referral guard (pre-check; the unique constraint is the
        # authoritative backstop against a concurrent race below).
        existing = (
            await db.execute(
                select(Referral).where(
                    Referral.referred_family_id == referred_family_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "Referral rejected: family %s already referred",
                referred_family_id,
            )
            return None

        referral = Referral(
            referrer_family_id=referrer_family_id,
            referred_family_id=referred_family_id,
        )
        db.add(referral)

        # Credit both sides (no commit inside — single atomic commit below).
        # PlanCreditService.grant() takes a per-family advisory xact lock
        # before computing each family's window (see its docstring), and
        # this call grants to TWO different families in one transaction. The
        # acquisition order therefore matters for deadlock avoidance: if we
        # always locked referrer-then-referred, two REVERSED concurrent
        # referrals (X refers Y in one transaction while Y refers X in
        # another) would lock in opposite order — txn1 holds lock(X), wants
        # lock(Y); txn2 holds lock(Y), wants lock(X) — a classic lock-order
        # cycle that Postgres would abort one side of with
        # deadlock_detected. Sorting the two ids first gives every
        # transaction the SAME acquisition order regardless of which family
        # is "referrer" vs "referred", which makes that cycle impossible (at
        # most one shared id contends, and contention alone — one txn
        # waiting for the other to finish — is not a cycle).
        for family_id in sorted((referrer_family_id, referred_family_id)):
            await ReferralService._grant_referral_month(db, family_id)
        referral.reward_granted_at = datetime.now(timezone.utc)

        try:
            await db.commit()
        except IntegrityError:
            # Lost a concurrent race — the other writer inserted the unique
            # referred_family_id first. Roll back cleanly; no double credit.
            await db.rollback()
            logger.info(
                "Referral race: family %s referred concurrently — skipping",
                referred_family_id,
            )
            return None

        await db.refresh(referral)
        return referral

    @staticmethod
    async def _grant_referral_month(
        db: AsyncSession, family_id: UUID
    ) -> None:
        """Credit *family_id* with 30 days of Plus. No commit.

        Writes a PlanCreditGrant (source='referral'). PlanCreditService owns
        the window math — credits stack additively and a payer's free month
        begins after the period they already paid for. We never mutate a
        PayPal-linked column, so a live paying subscription is untouched.

        Concurrency: PlanCreditService.grant() takes a per-family advisory
        xact lock before computing the window — see its docstring. Nothing
        to do here; see record_referral_and_reward for the lock-ORDERING
        concern specific to this call site (it grants to two families).
        """
        from app.services.plan_credit_service import PlanCreditService

        await PlanCreditService.grant(
            db,
            family_id=family_id,
            source="referral",
            tier="plus",
            duration_days=REFERRAL_REWARD_DAYS,
            reason="referral reward",
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    @staticmethod
    async def count_successful_referrals(
        db: AsyncSession, family_id: UUID
    ) -> int:
        """How many families joined via this family's code (and were rewarded)."""
        return int(
            (
                await db.execute(
                    select(func.count(Referral.id)).where(
                        Referral.referrer_family_id == family_id,
                        Referral.reward_granted_at.is_not(None),
                    )
                )
            ).scalar_one()
        )
