"""Family Bank routes — kid jar view, parent config, jar transfers, requests.

Basic ledger (balances, manual transfers, jar payouts, requests) is FREE.
Automation (allowance, %-split, interest, match) is Plus-gated at settings-time
via require_feature and re-checked credit-time by CashService (spec §10). All
queries are multi-tenant: kid endpoints act on current_user; parent endpoints
verify the target kid shares the parent's family_id.
"""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.premium import require_feature
from app.core.type_utils import to_uuid_required
from app.models import User
from app.models.user import UserRole
from app.schemas.bank import (
    BankRequestResponse,
    BankSettingsUpdate,
    BankTransferRequest,
    JarBalances,
    KidBankView,
    PayoutRequestBody,
    SaveWithdrawalRequest,
)
from app.services.bank_service import BankService
from app.services.base_service import verify_user_in_family

router = APIRouter()

# Kid-only transfer directions that are self-serve (spec §D6 / §5). save→spend
# is conditionally allowed depending on the approval toggle (checked below).
_KID_SELF_SERVE = {("spend", "save"), ("spend", "share")}


def _payload_enables_automation(data: dict) -> bool:
    """True when a settings payload turns ON any automation lever (allowance,
    non-100/0/0 split, interest, or match). Resetting to defaults never gates."""
    if data.get("allowance_cents"):
        return True
    if data.get("interest_rate_bps"):
        return True
    if data.get("match_pct"):
        return True
    if data.get("split_save_pct") or data.get("split_share_pct"):
        return True
    spend = data.get("split_spend_pct")
    if spend is not None and spend != 100:
        return True
    return False


def _require_kid(user: User) -> None:
    if user.role not in (UserRole.CHILD, UserRole.TEEN):
        raise HTTPException(status_code=403, detail="Only kids have a Family Bank")


@router.get("/me", response_model=KidBankView)
async def my_bank(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kid's own jars + split config + payday countdown + pending-match preview."""
    if current_user.role == UserRole.PARENT:
        raise HTTPException(
            status_code=400,
            detail="Parents manage jars via GET /api/bank/family",
        )
    view = await BankService.get_kid_bank(db, current_user)
    return KidBankView(**view)


@router.get("/family", response_model=List[KidBankView])
async def family_bank(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent view: every kid's jar balances + settings summary."""
    rows = await BankService.get_family_bank(db, current_user)
    return [KidBankView(**r) for r in rows]


@router.put("/settings/{user_id}", response_model=KidBankView)
async def update_settings(
    user_id: UUID,
    body: BankSettingsUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Upsert per-kid config. Premium-gated ONLY when the payload enables
    automation; resetting to defaults is always allowed."""
    fam = to_uuid_required(current_user.family_id)
    target = await verify_user_in_family(db, user_id, fam)
    if target.role not in (UserRole.CHILD, UserRole.TEEN):
        raise HTTPException(
            status_code=400, detail="Bank settings apply to CHILD/TEEN members only"
        )
    data = body.model_dump(exclude_unset=True)
    if _payload_enables_automation(data):
        await require_feature("family_bank_automation", db, current_user)
    await BankService.upsert_settings(db, target, fam, data)
    view = await BankService.get_kid_bank(db, target)
    return KidBankView(**view)


@router.post("/transfer", response_model=JarBalances)
async def transfer(
    body: BankTransferRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move money between jars. Kid: spend→save/share anytime; save→spend
    depends on the approval toggle. Parent: any direction, any kid in-family."""
    fam = to_uuid_required(current_user.family_id)
    if current_user.role == UserRole.PARENT:
        await verify_user_in_family(db, body.user_id, fam)
    else:
        if body.user_id != to_uuid_required(current_user.id):
            raise HTTPException(
                status_code=403, detail="Kids can only move their own money"
            )
        pair = (body.from_jar, body.to_jar)
        if pair in _KID_SELF_SERVE:
            pass
        elif pair == ("save", "spend"):
            acct = await BankService.ensure_account(db, current_user)
            if acct.save_withdrawal_requires_approval:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "approval_required",
                        "message": "Save withdrawals need a parent's approval.",
                    },
                )
        else:
            raise HTTPException(
                status_code=403,
                detail={"code": "parent_only", "message": "Only a parent can do that transfer."},
            )
    acct = await BankService.execute_transfer(
        db, body.user_id, fam, body.from_jar, body.to_jar, body.amount_cents,
        to_uuid_required(current_user.id),
    )
    return JarBalances(
        user_id=body.user_id,
        spend_cents=acct.spend_cents,
        save_cents=acct.save_cents,
        share_cents=acct.share_cents,
        total_cents=acct.spend_cents + acct.save_cents + acct.share_cents,
    )


@router.post("/requests/save-withdrawal", response_model=BankRequestResponse)
async def request_save_withdrawal(
    body: SaveWithdrawalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kid asks a parent to approve a Save withdrawal (stateless notification)."""
    _require_kid(current_user)
    n = await BankService.request_save_withdrawal(
        db, current_user, body.amount_cents, body.reason
    )
    return BankRequestResponse(success=True, notified_parents=n)


@router.post("/requests/payout", response_model=BankRequestResponse)
async def request_payout(
    body: PayoutRequestBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kid asks to be paid out (stateless notification to all parents)."""
    _require_kid(current_user)
    amount = body.amount_cents
    if not amount:
        acct = await BankService.ensure_account(db, current_user)
        amount = acct.spend_cents
    n = await BankService.request_payout(db, current_user, amount)
    return BankRequestResponse(success=True, notified_parents=n)
