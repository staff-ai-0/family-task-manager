"""
Recurring Transaction routes

CRUD endpoints for recurring/scheduled transactions.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
from datetime import date

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.recurring_transaction_service import RecurringTransactionService
from app.schemas.budget import (
    RecurringTransactionCreate,
    RecurringTransactionUpdate,
    RecurringTransactionResponse,
    RecurringTransactionNextDate,
)
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[RecurringTransactionResponse])
async def list_recurring_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    account_id: Optional[UUID] = Query(None, description="Filter by account ID"),
    active_only: bool = Query(True, description="Only return active templates"),
):
    """List recurring transaction templates for the family"""
    family_id = to_uuid_required(current_user.family_id)
    
    if account_id:
        templates = await RecurringTransactionService.list_by_account(
            db, account_id, family_id, active_only=active_only
        )
    else:
        templates = await RecurringTransactionService.list_by_family(
            db, family_id
        ) if not active_only else [t for t in await RecurringTransactionService.list_by_family(db, family_id) if t.is_active]
    
    return templates


@router.post("/", response_model=RecurringTransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_recurring_transaction(
    data: RecurringTransactionCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new recurring transaction template (parent only)"""
    template = await RecurringTransactionService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return template


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
    
    is_expired = template.end_date and (as_of_date or date.today()) > template.end_date
    
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
    from app.schemas.budget import TransactionResponse
    
    transaction = await RecurringTransactionService.post_transaction(
        db,
        recurring_id,
        to_uuid_required(current_user.family_id),
        transaction_date=transaction_date,
    )
    return transaction
