"""Operator coupon catalog writes.

Follows AdminActionService's audit contract: the audit row is staged on the
SAME session as the mutation, so a rolled-back write can never leave an "ok"
audit row behind.
"""
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.models.plan_credit import Coupon, PlanCreditGrant
from app.models.user import User
from app.schemas.coupon import CreateCouponRequest, UpdateCouponRequest
from app.services.admin.operator_audit_service import OperatorAuditService
from app.services.coupon_service import CouponService
from app.services.plan_credit_service import PlanCreditService

# The one IntegrityError create() is entitled to reinterpret as "duplicate
# code". Same asyncpg introspection shape as coupon_service's
# _is_duplicate_redemption: sqlstate lives on IntegrityError.orig, the
# constraint name one level deeper on the driver's UniqueViolationError
# (IntegrityError.orig.__cause__). The unique index on coupons.code is named
# ix_coupons_code (see the plan_credit_tables migration).
_DUPLICATE_CODE_SQLSTATE = "23505"
_DUPLICATE_CODE_CONSTRAINT = "ix_coupons_code"


def _is_duplicate_code(exc: IntegrityError) -> bool:
    """True only for the unique violation on coupons.code.

    A blanket ``except IntegrityError`` would relabel ANY constraint
    violation flushed by this commit as "code already exists" and discard
    its real cause — gate on both the sqlstate AND the constraint name.
    """
    orig = exc.orig
    if getattr(orig, "sqlstate", None) != _DUPLICATE_CODE_SQLSTATE:
        return False
    cause = getattr(orig, "__cause__", None)
    return getattr(cause, "constraint_name", None) == _DUPLICATE_CODE_CONSTRAINT


class AdminCouponService:
    """Create, list, amend and revoke — all audited."""

    @staticmethod
    async def list_coupons(
        db: AsyncSession,
        *,
        is_active: Optional[bool] = None,
        kind: Optional[str] = None,
        campaign: Optional[str] = None,
    ) -> list[Coupon]:
        query = select(Coupon)
        if is_active is not None:
            query = query.where(Coupon.is_active == is_active)
        if kind:
            query = query.where(Coupon.kind == kind)
        if campaign:
            query = query.where(Coupon.campaign == campaign)
        rows = (
            await db.execute(query.order_by(Coupon.created_at.desc()))
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def create(
        db: AsyncSession, *, operator: User, payload: CreateCouponRequest
    ) -> Coupon:
        code = CouponService.normalize_code(payload.code)
        coupon = Coupon(
            code=code,
            kind=payload.kind,
            tier=payload.tier,
            duration_days=payload.duration_days,
            max_redemptions=payload.max_redemptions,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
            campaign=payload.campaign,
            notes=payload.notes,
            created_by_user_id=operator.id,
        )
        db.add(coupon)
        OperatorAuditService.record(
            db,
            actor=operator,
            action="coupon.create",
            params={
                "code": code,
                "kind": payload.kind,
                "tier": payload.tier,
                "duration_days": payload.duration_days,
                "max_redemptions": payload.max_redemptions,
            },
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            # The rollback discards the staged "ok" audit row together with
            # the row that failed — nothing to unpick. `code` is a local
            # str on purpose: no ORM attribute reads after a failed flush.
            await db.rollback()
            if not _is_duplicate_code(exc):
                raise
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Coupon code {code} already exists"
            ) from None
        await db.refresh(coupon)
        return coupon

    @staticmethod
    async def update(
        db: AsyncSession,
        *,
        operator: User,
        coupon_id: UUID,
        payload: UpdateCouponRequest,
    ) -> Coupon:
        coupon = (
            await db.execute(select(Coupon).where(Coupon.id == coupon_id))
        ).scalar_one_or_none()
        if coupon is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Coupon not found")

        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(coupon, key, value)

        OperatorAuditService.record(
            db,
            actor=operator,
            action="coupon.update",
            params={
                "code": coupon.code,
                # mode="json" — `changes` may carry a datetime (valid_until)
                # and the audit params column is JSONB with no custom
                # serializer on the engine.
                "changes": payload.model_dump(exclude_unset=True, mode="json"),
            },
        )
        await db.commit()
        await db.refresh(coupon)
        return coupon

    @staticmethod
    async def redemptions(db: AsyncSession, *, coupon_id: UUID) -> dict:
        """Grants issued by this coupon.

        ``count`` is computed from the grant rows, NOT from
        coupons.redemption_count — the counter is a denormalized display
        value, and reading the authoritative count here is what makes a
        drifted counter visible instead of trusted.
        """
        rows = (
            await db.execute(
                select(PlanCreditGrant, Family.name)
                .join(Family, Family.id == PlanCreditGrant.family_id)
                .where(PlanCreditGrant.coupon_id == coupon_id)
                .order_by(PlanCreditGrant.created_at.desc())
            )
        ).all()
        count = (
            await db.execute(
                select(func.count(PlanCreditGrant.id)).where(
                    PlanCreditGrant.coupon_id == coupon_id
                )
            )
        ).scalar_one()
        return {
            "count": int(count),
            "redemptions": [
                {
                    "grant_id": str(g.id),
                    "family_id": str(g.family_id),
                    "family_name": family_name,
                    "tier": g.tier,
                    "starts_at": g.starts_at.isoformat(),
                    "ends_at": g.ends_at.isoformat() if g.ends_at else None,
                    "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
                }
                for g, family_name in rows
            ],
        }

    @staticmethod
    async def revoke_grant(
        db: AsyncSession, *, operator: User, grant_id: UUID, reason: str
    ) -> dict:
        """Soft-revoke one grant, audited. 404 unknown, 409 already revoked.

        The already-revoked pre-check matters because PlanCreditService.revoke
        is deliberately idempotent (a second call returns the row unchanged):
        without it, re-revoking would 200 and stage a second audit row for a
        revocation that never happened.
        """
        already = (
            await db.execute(
                select(PlanCreditGrant.revoked_at).where(
                    PlanCreditGrant.id == grant_id
                )
            )
        ).one_or_none()
        if already is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Credit grant not found")
        if already[0] is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Credit grant already revoked"
            )

        row = await PlanCreditService.revoke(db, grant_id=grant_id)
        if row is None:  # deleted between the check and the revoke
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Credit grant not found")

        # Snapshot before commit — never read ORM attributes on a path that
        # can follow a rollback (established admin-service pattern).
        family_id = row.family_id
        revoked_at = row.revoked_at
        OperatorAuditService.record(
            db,
            actor=operator,
            action="family.revoke_credit",
            target_family_id=family_id,
            params={"grant_id": str(grant_id), "reason": reason},
        )
        await db.commit()
        return {"grant_id": str(grant_id), "revoked_at": revoked_at.isoformat()}
