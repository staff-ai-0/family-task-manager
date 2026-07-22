"""Family Bank routes — kid jar view, parent config, jar transfers, requests.

Basic ledger (balances, manual transfers, jar payouts, requests) is FREE.
Automation (allowance, %-split, interest, match) is Plus-gated at settings-time
via require_feature and re-checked credit-time by CashService (spec §10). All
queries are multi-tenant: kid endpoints act on current_user; parent endpoints
verify the target kid shares the parent's family_id.
"""
from typing import List, Optional
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
    ChorePaycheckOutstandingResponse,
    ChorePaycheckPreview,
    ChorePaycheckReleaseBody,
    ChorePaycheckReleaseResult,
    JarBalances,
    KidBankView,
    PayoutHistoryResponse,
    PayoutRequestBody,
    PayoutSummary,
    SaveWithdrawalRequest,
)
from app.schemas.envelope import KidEnvelopesView
from app.schemas.savings_goal import SavingsGoalCreate, SavingsGoalProgress
from app.services.bank_service import BankService
from app.services.base_service import verify_user_in_family
from app.services.envelope_service import EnvelopeService
from app.services.savings_goal_service import SavingsGoalService

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


@router.get("/payout-summary", response_model=PayoutSummary)
async def payout_summary(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Everything the parent currently owes the kids: gig cash awaiting payout
    + this week's chore paychecks awaiting release. Feeds the parent home card
    and the payouts dashboard."""
    return await BankService.payout_summary(
        db, to_uuid_required(current_user.family_id)
    )


# ── Kid budget-envelopes (thin projection over jars + savings goal) ──────────
#
# A read-only "envelopes" view of each kid's Family Bank jars (Spend/Save/Share)
# fed by chores/gigs cash, plus their named savings goal overlaid on Save. Free
# (no premium gate — it projects the free ledger). Family-scoped: a kid sees
# ONLY their own envelopes; a parent sees every kid's. NOTE: the static routes
# (/envelopes/me, /envelopes/family) MUST precede /envelopes/{user_id} so
# "me"/"family" are not parsed as a UUID path param.


@router.get("/envelopes/me", response_model=KidEnvelopesView)
async def my_envelopes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The kid's own budget envelopes (their three jars + savings goal)."""
    if current_user.role == UserRole.PARENT:
        raise HTTPException(
            status_code=400,
            detail="Parents view kids' envelopes via GET /api/bank/envelopes/family",
        )
    view = await EnvelopeService.get_kid_envelopes(db, current_user)
    return KidEnvelopesView(**view)


@router.get("/envelopes/family", response_model=List[KidEnvelopesView])
async def family_envelopes(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent overview: every kid's envelopes in the parent's family."""
    rows = await EnvelopeService.get_family_envelopes(db, current_user)
    return [KidEnvelopesView(**r) for r in rows]


@router.get("/envelopes/{user_id}", response_model=KidEnvelopesView)
async def kid_envelopes(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A specific kid's envelopes. Parent: any kid in-family (404 otherwise).
    Kid: only their own (403 on a sibling / anyone else)."""
    fam = to_uuid_required(current_user.family_id)
    if current_user.role == UserRole.PARENT:
        kid = await verify_user_in_family(db, user_id, fam)  # 404 if outside family
    else:
        if user_id != to_uuid_required(current_user.id):
            raise HTTPException(
                status_code=403, detail="Kids can only see their own envelopes"
            )
        kid = current_user
    if kid.role not in (UserRole.CHILD, UserRole.TEEN):
        raise HTTPException(
            status_code=400, detail="Envelopes apply to CHILD/TEEN members only"
        )
    view = await EnvelopeService.get_kid_envelopes(db, kid)
    return KidEnvelopesView(**view)


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


@router.get("/chore-paycheck/{user_id}", response_model=ChorePaycheckPreview)
async def chore_paycheck_preview(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Projected weekly chore paycheck. Parent: any kid in-family. Kid: own only.
    No premium gate — it's a read-only projection of the free ledger."""
    fam = to_uuid_required(current_user.family_id)
    if current_user.role == UserRole.PARENT:
        kid = await verify_user_in_family(db, user_id, fam)
    else:
        if user_id != to_uuid_required(current_user.id):
            raise HTTPException(status_code=403, detail="Kids see only their own paycheck")
        kid = current_user
    if kid.role not in (UserRole.CHILD, UserRole.TEEN):
        raise HTTPException(
            status_code=400, detail="Chore paycheck applies to CHILD/TEEN members only"
        )
    return ChorePaycheckPreview(**await BankService.chore_paycheck_preview(db, kid, fam))


@router.post(
    "/chore-paycheck/{user_id}/release", response_model=ChorePaycheckReleaseResult
)
async def release_chore_paycheck(
    user_id: UUID,
    body: Optional[ChorePaycheckReleaseBody] = None,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent releases a teen's chore paycheck for a given (family-local)
    week — defaults to the current week when week_of is omitted, so any
    existing caller is unaffected. Credits allowance_cents × completion (±
    optional adjustment), split into jars. Premium-gated (Family-Bank
    automation); idempotent per (kid, week)."""
    fam = to_uuid_required(current_user.family_id)
    target = await verify_user_in_family(db, user_id, fam)
    if target.role not in (UserRole.CHILD, UserRole.TEEN):
        raise HTTPException(
            status_code=400, detail="Chore paycheck applies to CHILD/TEEN members only"
        )
    await require_feature("family_bank_automation", db, current_user)
    today = await BankService._family_local_today(db, fam)
    week_of = (body.week_of if body and body.week_of else None) or today
    week_monday = BankService._week_monday(week_of)
    if week_monday > BankService._week_monday(today):
        raise HTTPException(status_code=422, detail="week_of cannot be in the future")
    result = await BankService.release_chore_paycheck(
        db, target, fam, week_monday, entitled=True,
        adjustment_cents=(body.adjustment_cents if body else 0),
        released_by=to_uuid_required(current_user.id),
    )
    return ChorePaycheckReleaseResult(**result)


@router.get(
    "/chore-paycheck/{user_id}/history", response_model=PayoutHistoryResponse
)
async def chore_paycheck_history(
    user_id: UUID,
    limit: int = 12,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Past released chore-paycheck weeks for a kid — amount, when, and the
    per-task breakdown behind it. Parent only, read-only (no premium gate:
    it's history of ledger rows that already exist)."""
    fam = to_uuid_required(current_user.family_id)
    target = await verify_user_in_family(db, user_id, fam)
    return PayoutHistoryResponse(
        **await BankService.chore_paycheck_history(db, target, fam, limit=limit)
    )


@router.get(
    "/chore-paycheck/{user_id}/outstanding", response_model=ChorePaycheckOutstandingResponse
)
async def chore_paycheck_outstanding(
    user_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Every unreleased chore-paycheck week for a kid (oldest first),
    including the current in-progress week. Parent only, read-only."""
    fam = to_uuid_required(current_user.family_id)
    target = await verify_user_in_family(db, user_id, fam)
    if target.role not in (UserRole.CHILD, UserRole.TEEN):
        raise HTTPException(
            status_code=400, detail="Chore paycheck applies to CHILD/TEEN members only"
        )
    weeks = await BankService.list_outstanding_weeks(db, target, fam)
    return ChorePaycheckOutstandingResponse(weeks=weeks)


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


# ── Savings goals (P2 — CASH ledger, Save jar) ──────────────────────────────
#
# A kid saves toward ONE named goal, tracked against their Save jar. Free basic
# feature (no premium gate) — it's a presentation layer over the existing Family
# Bank cash balance, with zero coupling to points. Parents set/approve goals.


@router.get("/goals/me", response_model=Optional[SavingsGoalProgress])
async def my_goal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The kid's own active/pending savings goal + live progress (null if none).

    Fires the one-time 'goal reached' celebration when the Save jar first crosses
    target. Parents have no personal goal → always null."""
    if current_user.role == UserRole.PARENT:
        return None
    goal = await SavingsGoalService.get_active(db, current_user, notify=True)
    return SavingsGoalProgress(**goal) if goal else None


@router.get("/goals/family", response_model=List[SavingsGoalProgress])
async def family_goals(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent view: every kid's open savings goal + progress."""
    rows = await SavingsGoalService.get_family(db, current_user)
    return [SavingsGoalProgress(**r) for r in rows]


@router.post("/goals", response_model=SavingsGoalProgress, status_code=201)
async def create_goal(
    body: SavingsGoalCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a savings goal. A PARENT sets one for a kid (body.user_id, created
    active). A KID proposes one for themselves (created pending until approved)."""
    if current_user.role == UserRole.PARENT:
        if body.user_id is None:
            raise HTTPException(
                status_code=422, detail="user_id is required when a parent sets a goal"
            )
        kid = await verify_user_in_family(
            db, body.user_id, to_uuid_required(current_user.family_id)
        )
        if kid.role not in (UserRole.CHILD, UserRole.TEEN):
            raise HTTPException(
                status_code=400, detail="Savings goals apply to CHILD/TEEN members only"
            )
    else:
        if current_user.role not in (UserRole.CHILD, UserRole.TEEN):
            raise HTTPException(status_code=403, detail="Only kids have a savings goal")
        if body.user_id is not None and body.user_id != to_uuid_required(current_user.id):
            raise HTTPException(
                status_code=403, detail="Kids can only set their own goal"
            )
        kid = current_user
    result = await SavingsGoalService.create_goal(
        db,
        current_user,
        kid=kid,
        name=body.name,
        target_cents=body.target_cents,
        emoji=body.emoji,
    )
    return SavingsGoalProgress(**result)


@router.post("/goals/{goal_id}/approve", response_model=SavingsGoalProgress)
async def approve_goal(
    goal_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent approves a kid's pending goal (pending → active)."""
    result = await SavingsGoalService.approve_goal(db, current_user, goal_id)
    return SavingsGoalProgress(**result)


@router.delete("/goals/{goal_id}", status_code=204)
async def cancel_goal(
    goal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a goal. A kid may cancel only their own; a parent any kid's."""
    await SavingsGoalService.cancel_goal(db, current_user, goal_id)
    return None
