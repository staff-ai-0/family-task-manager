"""Cash currency routes — kid balance/history + parent payouts.

Cash is earned on the /gigs board and paid out by parents. Separate from
privilege points (rewards). See the two-currency-economy design spec.
"""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.core.exceptions import ValidationException
from app.models import User
from app.models.user import UserRole
from app.services.cash_service import CashService
from app.services.base_service import verify_user_in_family
from app.schemas.cash import (
    CashSummary, CashTxn, PayoutRequest, AdjustRequest, PayoutResponse,
)

router = APIRouter()


@router.get("/balance", response_model=CashSummary)
async def my_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current user's cash summary (earned / paid / pending)."""
    uid = to_uuid_required(current_user.id)
    s = await CashService.get_summary(db, uid)
    return CashSummary(
        user_id=current_user.id, name=current_user.name,
        current_balance_cents=s["current_balance"],
        total_earned_cents=s["total_earned"],
        total_paid_cents=s["total_paid"],
    )


@router.get("/history", response_model=List[CashTxn])
async def my_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await CashService.get_history(db, to_uuid_required(current_user.id))
    return [CashTxn.model_validate(r) for r in rows]


@router.get("/family", response_model=List[CashSummary])
async def family_cash(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent view: every kid's cash summary."""
    fam = to_uuid_required(current_user.family_id)
    kids = (await db.execute(
        select(User).where(
            User.family_id == fam,
            User.role.in_([UserRole.CHILD, UserRole.TEEN]),
        )
    )).scalars().all()
    out: List[CashSummary] = []
    for k in kids:
        s = await CashService.get_summary(db, k.id)
        out.append(CashSummary(
            user_id=k.id, name=k.name,
            current_balance_cents=s["current_balance"],
            total_earned_cents=s["total_earned"],
            total_paid_cents=s["total_paid"],
        ))
    return out


@router.post("/{user_id}/payout", response_model=PayoutResponse)
async def payout(
    user_id: UUID,
    body: PayoutRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent records a payout (full or partial). Debits the kid's cash."""
    fam = to_uuid_required(current_user.family_id)
    await verify_user_in_family(db, user_id, fam)
    try:
        tx = await CashService.record_payout(
            db, user_id, fam, body.amount_cents, to_uuid_required(current_user.id)
        )
    except ValidationException as e:
        raise HTTPException(status_code=400, detail=str(e))
    bal = await CashService.get_balance(db, user_id)
    return PayoutResponse(success=True, new_balance_cents=bal, transaction_id=tx.id)


@router.post("/{user_id}/adjust", response_model=PayoutResponse)
async def adjust(
    user_id: UUID,
    body: AdjustRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent manual cash adjustment (signed)."""
    fam = to_uuid_required(current_user.family_id)
    await verify_user_in_family(db, user_id, fam)
    tx = await CashService.adjust(
        db, user_id, fam, body.amount_cents, body.reason,
        to_uuid_required(current_user.id),
    )
    bal = await CashService.get_balance(db, user_id)
    return PayoutResponse(success=True, new_balance_cents=bal, transaction_id=tx.id)
