"""
Transaction routes

CRUD endpoints for budget transactions.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.transaction_service import TransactionService
from app.schemas.budget import TransactionCreate, TransactionUpdate, TransactionResponse
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[TransactionResponse])
async def list_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    account_id: UUID = Query(None, description="Filter by account ID"),
    category_id: UUID = Query(None, description="Filter by category ID"),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    limit: int = Query(100, le=500, description="Limit results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List transactions with optional filters"""
    family_id = to_uuid_required(current_user.family_id)
    
    if account_id:
        transactions = await TransactionService.list_by_account(
            db, account_id, family_id, start_date, end_date, limit, offset
        )
    elif category_id:
        transactions = await TransactionService.list_by_category(
            db, category_id, family_id, start_date, end_date
        )
    else:
        transactions = await TransactionService.list_by_family(
            db, family_id, limit=limit, offset=offset
        )
    
    return transactions


@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    data: TransactionCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new transaction (parent only)"""
    transaction = await TransactionService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return transaction


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a transaction by ID"""
    transaction = await TransactionService.get_by_id(
        db,
        transaction_id,
        to_uuid_required(current_user.family_id),
    )
    return transaction


@router.put("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: UUID,
    data: TransactionUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a transaction (parent only)"""
    transaction = await TransactionService.update(
        db,
        transaction_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return transaction


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a transaction (parent only)"""
    await TransactionService.delete_by_id(
        db,
        transaction_id,
        to_uuid_required(current_user.family_id),
    )
