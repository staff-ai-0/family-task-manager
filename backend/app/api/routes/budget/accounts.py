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
