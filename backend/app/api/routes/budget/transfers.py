"""
Transfer routes

Endpoints for transferring money between accounts and categories.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.transfer_service import TransferService
from app.schemas.budget import TransactionResponse
from app.models import User

router = APIRouter()


class AccountTransferRequest(BaseModel):
    """Request to transfer money between accounts"""
    from_account_id: UUID = Field(..., description="Source account ID")
    to_account_id: UUID = Field(..., description="Destination account ID")
    amount: int = Field(..., gt=0, description="Amount to transfer in cents")
    date: str = Field(..., description="Transfer date (YYYY-MM-DD)")
    notes: str | None = Field(None, description="Optional notes")


class CategoryTransferRequest(BaseModel):
    """Request to transfer budgeted money between categories"""
    from_category_id: UUID = Field(..., description="Source category ID")
    to_category_id: UUID = Field(..., description="Destination category ID")
    amount: int = Field(..., gt=0, description="Amount to transfer in cents")
    month: str = Field(..., description="Month for transfer (YYYY-MM-DD, first day of month)")
    notes: str | None = Field(None, description="Optional notes")


class CoverOverspendingRequest(BaseModel):
    """Request to cover overspending in a category"""
    category_id: UUID = Field(..., description="Overspent category to cover")
    source_category_id: UUID = Field(..., description="Category to take money from")
    month: str = Field(..., description="Month (YYYY-MM-DD, first day of month)")


@router.post("/accounts", response_model=list[TransactionResponse], status_code=status.HTTP_201_CREATED)
async def transfer_between_accounts(
    transfer: AccountTransferRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Transfer money between accounts (parent only)
    
    Creates two linked transactions:
    - Negative transaction in source account
    - Positive transaction in destination account
    """
    transactions = await TransferService.transfer_between_accounts(
        db=db,
        family_id=to_uuid_required(current_user.family_id),
        from_account_id=transfer.from_account_id,
        to_account_id=transfer.to_account_id,
        amount=transfer.amount,
        date=transfer.date,
        notes=transfer.notes,
    )
    return transactions


@router.post("/categories", status_code=status.HTTP_200_OK)
async def transfer_between_categories(
    transfer: CategoryTransferRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Transfer budgeted money between categories (parent only)
    
    This moves allocated budget from one category to another within the same month.
    Does not create transactions, only adjusts budget allocations.
    """
    result = await TransferService.transfer_between_categories(
        db=db,
        family_id=to_uuid_required(current_user.family_id),
        from_category_id=transfer.from_category_id,
        to_category_id=transfer.to_category_id,
        amount=transfer.amount,
        month=transfer.month,
        notes=transfer.notes,
    )
    return result


@router.post("/cover-overspending", status_code=status.HTTP_200_OK)
async def cover_overspending(
    request: CoverOverspendingRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Cover overspending in a category by pulling from another category (parent only)
    
    Automatically calculates the overspent amount and transfers just enough
    to bring the category back to zero.
    """
    result = await TransferService.cover_overspending(
        db=db,
        family_id=to_uuid_required(current_user.family_id),
        overspent_category_id=request.category_id,
        source_category_id=request.source_category_id,
        month=request.month,
    )
    return result
