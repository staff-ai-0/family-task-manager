"""
Account routes

CRUD endpoints for budget accounts.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.account_service import AccountService
from app.schemas.budget import AccountCreate, AccountUpdate, AccountResponse
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[AccountResponse])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    account_type: str = Query(None, description="Filter by account type"),
    include_closed: bool = Query(False, description="Include closed accounts"),
    budget_only: bool = Query(False, description="Only on-budget accounts"),
):
    """List all accounts"""
    family_id = to_uuid_required(current_user.family_id)
    
    if budget_only:
        accounts = await AccountService.list_budget_accounts(
            db, family_id, include_closed=include_closed
        )
    elif account_type:
        accounts = await AccountService.list_by_type(
            db, family_id, account_type, include_closed=include_closed
        )
    else:
        accounts = await AccountService.list_by_family(db, family_id)
        if not include_closed:
            accounts = [a for a in accounts if not a.closed]
    
    return accounts


@router.post("/", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    data: AccountCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new account (parent only)"""
    account = await AccountService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return account


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get an account by ID"""
    account = await AccountService.get_by_id(
        db,
        account_id,
        to_uuid_required(current_user.family_id),
    )
    return account


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: UUID,
    data: AccountUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update an account (parent only)"""
    account = await AccountService.update(
        db,
        account_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete an account (parent only)"""
    await AccountService.delete_by_id(
        db,
        account_id,
        to_uuid_required(current_user.family_id),
    )


@router.get("/{account_id}/balance")
async def get_account_balance(
    account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    as_of_date: str = Query(None, description="Calculate balance as of date (YYYY-MM-DD)"),
):
    """
    Get account balance.
    
    Returns total balance, cleared balance, and uncleared balance (all in cents).
    """
    from datetime import date as date_type
    
    family_id = to_uuid_required(current_user.family_id)
    
    # Parse date if provided
    as_of = None
    if as_of_date:
        as_of = date_type.fromisoformat(as_of_date)
    
    balance_info = await AccountService.get_balance(
        db, account_id, family_id, as_of_date=as_of
    )
    
    # Convert cents to currency for response
    return {
        "account_id": str(account_id),
        "balance": balance_info["balance"] / 100,
        "balance_cents": balance_info["balance"],
        "cleared_balance": balance_info["cleared_balance"] / 100,
        "cleared_balance_cents": balance_info["cleared_balance"],
        "uncleared_balance": balance_info["uncleared_balance"] / 100,
        "uncleared_balance_cents": balance_info["uncleared_balance"],
        "as_of_date": as_of_date,
    }


@router.post("/{account_id}/reconcile")
async def bulk_reconcile_account(
    account_id: UUID,
    transaction_ids: List[UUID],
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Reconcile multiple transactions for an account (parent only).
    
    This is typically used after reconciling an account statement.
    """
    from app.services.budget.transaction_service import TransactionService
    
    count = await TransactionService.bulk_reconcile_account(
        db,
        account_id,
        to_uuid_required(current_user.family_id),
        transaction_ids,
    )
    
    return {
        "account_id": str(account_id),
        "reconciled_count": count,
        "message": f"Successfully reconciled {count} transactions",
    }
