"""
Recurring Transaction routes

CRUD endpoints for recurring/scheduled transactions.
"""

from fastapi import APIRouter, Depends, status, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
from datetime import date

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.core.premium import require_feature
from app.services.usage_service import UsageService
from app.services.budget.recurring_transaction_service import RecurringTransactionService
from app.services.budget.transaction_service import TransactionService
from app.schemas.budget import (
    RecurringTransactionCreate,
    RecurringTransactionUpdate,
    RecurringTransactionResponse,
    RecurringTransactionNextDate,
)
from app.models import User
from app.core.time_utils import utc_today

router = APIRouter()


class RecurringCandidate(BaseModel):
    """A detected recurring-charge series the user can promote to a template."""
    payee_id: UUID
    payee_name: str
    amount_cents: int
    cadence: str
    occurrences: int
    avg_interval_days: float
    last_date: date
    next_estimated_date: date
    account_id: Optional[UUID] = None
    category_id: Optional[UUID] = None


class RecurringCandidatesResponse(BaseModel):
    candidates: List[RecurringCandidate]


@router.get("/", response_model=List[RecurringTransactionResponse])
async def list_recurring_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    account_id: Optional[UUID] = Query(None, description="Filter by account ID"),
    active_only: bool = Query(True, description="Only return active templates"),
    limit: int = Query(200, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """List recurring transaction templates for the family"""
    family_id = to_uuid_required(current_user.family_id)

    if account_id:
        templates = await RecurringTransactionService.list_by_account(
            db, account_id, family_id,
            active_only=active_only, limit=limit, offset=offset,
        )
    else:
        templates = await RecurringTransactionService.list_by_family_filtered(
            db, family_id,
            active_only=active_only, limit=limit, offset=offset,
        )

    return templates


@router.post("/", response_model=RecurringTransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_recurring_transaction(
    data: RecurringTransactionCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new recurring transaction template (parent only)"""
    await require_feature("recurring_transaction", db, current_user)
    template = await RecurringTransactionService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    await UsageService.increment(db, current_user.family_id, "recurring_transaction")
    return template


@router.get("/detect-candidates", response_model=RecurringCandidatesResponse)
async def detect_recurring_candidates(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
    min_occurrences: int = Query(
        3, ge=2, le=24,
        description="Minimum repeating charges before a series is suggested",
    ),
):
    """Detect likely recurring charges from transaction history (parent only).

    Scans the family's transactions for repeating (payee, ~amount, ~regular
    cadence) series — forgotten subscriptions, monthly bills — and returns
    them as candidates the user can confirm into a recurring template. Payees
    already covered by an active template are excluded. Declared before
    ``/{recurring_id}`` so the literal path wins over the UUID path parameter.
    """
    family_id = to_uuid_required(current_user.family_id)
    candidates = await TransactionService.detect_recurring_candidates(
        db, family_id, min_occurrences=min_occurrences,
    )
    return RecurringCandidatesResponse(candidates=candidates)


@router.get("/{recurring_id}", response_model=RecurringTransactionResponse)
async def get_recurring_transaction(
    recurring_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific recurring transaction template"""
    template = await RecurringTransactionService.get_by_id(
        db, recurring_id, to_uuid_required(current_user.family_id)
    )
    return template


@router.put("/{recurring_id}", response_model=RecurringTransactionResponse)
async def update_recurring_transaction(
    recurring_id: UUID,
    data: RecurringTransactionUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a recurring transaction template (parent only)"""
    template = await RecurringTransactionService.update(
        db,
        recurring_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return template


@router.delete("/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring_transaction(
    recurring_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a recurring transaction template (parent only)"""
    await RecurringTransactionService.delete_by_id(
        db, recurring_id, to_uuid_required(current_user.family_id)
    )
    return None


@router.get("/{recurring_id}/next-date", response_model=RecurringTransactionNextDate)
async def get_next_occurrence(
    recurring_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    as_of_date: Optional[date] = Query(None, description="Calculate as of this date (defaults to today)"),
):
    """Get next scheduled occurrence for a recurring transaction"""
    template = await RecurringTransactionService.get_by_id(
        db, recurring_id, to_uuid_required(current_user.family_id)
    )
    
    next_due = RecurringTransactionService._calculate_next_occurrence(
        template.start_date,
        template.recurrence_type,
        template.recurrence_interval,
        template.recurrence_pattern,
        template.end_date,
        from_date=as_of_date,
    )
    
    is_expired = template.end_date and (as_of_date or utc_today()) > template.end_date
    
    return RecurringTransactionNextDate(
        next_due_date=next_due,
        is_expired=is_expired,
        occurrences_remaining=None,  # Could be calculated for finite templates
    )


@router.get("/due-for-posting/list", response_model=List[RecurringTransactionResponse])
async def list_due_for_posting(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    as_of_date: Optional[date] = Query(None, description="Check due as of this date (defaults to today)"),
):
    """List recurring transactions due for posting"""
    templates = await RecurringTransactionService.list_due_for_posting(
        db, to_uuid_required(current_user.family_id), as_of_date=as_of_date
    )
    return templates


@router.post("/{recurring_id}/post", status_code=status.HTTP_201_CREATED)
async def post_recurring_transaction(
    recurring_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
    transaction_date: Optional[date] = Query(None, description="Date to post transaction (defaults to today)"),
):
    """Post a transaction from a recurring template (parent only)"""
    
    transaction = await RecurringTransactionService.post_transaction(
        db,
        recurring_id,
        to_uuid_required(current_user.family_id),
        transaction_date=transaction_date,
        user_id=current_user.id,
    )
    return transaction
