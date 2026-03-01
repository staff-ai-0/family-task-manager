"""
Transaction routes

CRUD endpoints for budget transactions.
"""

from fastapi import APIRouter, Depends, status, Query, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict
from datetime import date
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.transaction_service import TransactionService
from app.services.budget.csv_import_service import CSVImportService
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


@router.put("/{transaction_id}/reconcile", response_model=TransactionResponse)
async def reconcile_transaction(
    transaction_id: UUID,
    reconciled: bool = Query(True, description="Mark as reconciled (true) or unreconciled (false)"),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a transaction as reconciled or unreconciled (parent only).
    
    Reconciled transactions are locked and cannot be edited except by parents.
    """
    transaction = await TransactionService.reconcile_transaction(
        db,
        transaction_id,
        to_uuid_required(current_user.family_id),
        reconciled=reconciled,
    )
    return transaction


@router.post("/import/csv", status_code=status.HTTP_200_OK)
async def import_csv_transactions(
    file: UploadFile = File(..., description="CSV file containing transactions"),
    account_id: UUID = Query(..., description="Target account for import"),
    delimiter: str = Query(",", description="CSV delimiter (comma, semicolon, tab, etc.)"),
    skip_header_rows: int = Query(0, ge=0, description="Number of header rows to skip"),
    create_payees: bool = Query(True, description="Automatically create payees"),
    prevent_duplicates: bool = Query(True, description="Prevent duplicate imports"),
    column_mapping: Optional[str] = Query(None, description="JSON string with custom column mapping"),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Import transactions from a CSV file.
    
    Supports multiple CSV formats with automatic column detection.
    
    Query parameters:
    - account_id: UUID of the account to import into
    - delimiter: CSV field delimiter (default: comma)
    - skip_header_rows: Number of header rows to skip (default: 0)
    - create_payees: Create missing payees automatically (default: true)
    - prevent_duplicates: Check for duplicates using imported_id (default: true)
    - column_mapping: JSON mapping of field names, e.g. {"date":"Transaction Date","amount":"Value"}
    
    Returns import statistics and detailed error information.
    """
    try:
        # Read CSV file content
        csv_content = await file.read()
        csv_text = csv_content.decode('utf-8')
        
        # Parse column mapping if provided
        parsed_mapping: Optional[Dict[str, str]] = None
        if column_mapping:
            import json
            try:
                parsed_mapping = json.loads(column_mapping)
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "error": "Invalid column_mapping JSON",
                    "result": None
                }
        
        # Validate account belongs to family
        from app.services.budget.account_service import AccountService
        account = await AccountService.get_by_id(
            db,
            account_id,
            to_uuid_required(current_user.family_id),
        )
        if not account:
            return {
                "success": False,
                "error": f"Account not found: {account_id}",
                "result": None
            }
        
        # Run import
        result = await CSVImportService.import_csv(
            db=db,
            family_id=to_uuid_required(current_user.family_id),
            csv_content=csv_text,
            account_id=account_id,
            column_mapping=parsed_mapping,
            delimiter=delimiter,
            skip_header_rows=skip_header_rows,
            create_payees=create_payees,
            prevent_duplicates=prevent_duplicates,
        )
        
        return {
            "success": len(result.import_errors) == 0,
            "result": result.to_dict()
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "result": None
        }

