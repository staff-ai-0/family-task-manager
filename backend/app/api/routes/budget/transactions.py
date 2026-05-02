"""
Transaction routes

CRUD endpoints for budget transactions.
"""

from fastapi import APIRouter, Body, Depends, status, Query, File, UploadFile, Form
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict
from datetime import date
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.core.premium import require_feature
from app.services.budget.transaction_service import TransactionService
from app.services.usage_service import UsageService
from app.services.budget.csv_import_service import CSVImportService
from app.services.budget.file_import_service import import_file_transactions
from app.services.budget.receipt_scanner_service import scan_and_create_transaction
from app.schemas.budget import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    SplitTransactionCreate,
    SplitTransactionUpdate,
    SplitTransactionResponse,
)
from app.models import User

router = APIRouter()


def _build_split_response(parent, children) -> SplitTransactionResponse:
    """Construct response with sum-of-children total; surfaces drift if data corrupt."""
    total = sum(c.amount for c in children)
    return SplitTransactionResponse(parent=parent, children=children, total=total)


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
    include_split_children: bool = Query(False, description="Include child legs of split parents"),
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

    if not include_split_children:
        transactions = [t for t in transactions if t.parent_id is None]

    return transactions


@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    data: TransactionCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new transaction (parent only)"""
    await require_feature("budget_transaction", db, current_user)
    transaction = await TransactionService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    await UsageService.increment(db, current_user.family_id, "budget_transaction")
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


class BulkUpdateRequest(BaseModel):
    transaction_ids: List[UUID]
    updates: Dict[str, object] = Field(..., description="Whitelist: cleared, reconciled, category_id, payee_id")


class BulkDeleteRequest(BaseModel):
    transaction_ids: List[UUID]


class FinishReconciliationRequest(BaseModel):
    account_id: UUID
    statement_balance: int
    transaction_ids: List[UUID]


@router.get("/search", response_model=List[TransactionResponse])
async def search_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    account_id: Optional[UUID] = Query(None),
    category_id: Optional[UUID] = Query(None),
    payee_id: Optional[UUID] = Query(None),
    cleared: Optional[bool] = Query(None),
    reconciled: Optional[bool] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    amount_min: Optional[int] = Query(None, description="Min amount in cents (inclusive)"),
    amount_max: Optional[int] = Query(None, description="Max amount in cents (inclusive)"),
    search: Optional[str] = Query(None, description="Substring match against notes (case-insensitive)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Filter transactions by any combination of criteria."""
    family_id = to_uuid_required(current_user.family_id)
    return await TransactionService.search_transactions(
        db, family_id,
        account_id=account_id, category_id=category_id, payee_id=payee_id,
        cleared=cleared, reconciled=reconciled,
        start_date=start_date, end_date=end_date,
        amount_min=amount_min, amount_max=amount_max,
        search=search, limit=limit, offset=offset,
    )


@router.post("/bulk-update")
async def bulk_update_transactions(
    data: BulkUpdateRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Bulk modify N transactions (parent only). Whitelist: cleared, reconciled, category_id, payee_id."""
    family_id = to_uuid_required(current_user.family_id)
    count = await TransactionService.bulk_update_transactions(
        db, family_id, data.transaction_ids, data.updates,
    )
    return {"updated_count": count}


@router.post("/bulk-delete")
async def bulk_delete_transactions(
    data: BulkDeleteRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Bulk delete N transactions (parent only)."""
    family_id = to_uuid_required(current_user.family_id)
    count = await TransactionService.bulk_delete_transactions(
        db, family_id, data.transaction_ids,
    )
    return {"deleted_count": count}


@router.post("/finish-reconciliation")
async def finish_reconciliation(
    data: FinishReconciliationRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Mark transactions as cleared+reconciled and create adjustment if balance differs (parent only)."""
    family_id = to_uuid_required(current_user.family_id)
    return await TransactionService.finish_reconciliation(
        db, family_id,
        account_id=data.account_id,
        statement_balance=data.statement_balance,
        transaction_ids=data.transaction_ids,
    )


@router.post("/split", response_model=SplitTransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_split_transaction(
    data: SplitTransactionCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a parent + N child split transaction (parent only)."""
    await require_feature("budget_transaction", db, current_user)
    family_id = to_uuid_required(current_user.family_id)
    parent = await TransactionService.create_split(
        db,
        family_id,
        account_id=data.account_id,
        txn_date=data.date,
        splits=data.splits,
        payee_id=data.payee_id,
        payee_name=data.payee_name,
        notes=data.notes,
        cleared=data.cleared,
        reconciled=data.reconciled,
    )
    await UsageService.increment(db, current_user.family_id, "budget_transaction")
    children = await TransactionService.get_split_children(db, parent.id, family_id)
    return _build_split_response(parent, children)


@router.get("/{transaction_id}/splits", response_model=SplitTransactionResponse)
async def get_split_transaction(
    transaction_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return parent split transaction with its child legs."""
    family_id = to_uuid_required(current_user.family_id)
    parent = await TransactionService.get_by_id(db, transaction_id, family_id)
    children = await TransactionService.get_split_children(db, transaction_id, family_id)
    return _build_split_response(parent, children)


@router.put("/{transaction_id}/splits", response_model=SplitTransactionResponse)
async def update_split_transaction(
    transaction_id: UUID,
    data: SplitTransactionUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Replace child legs of a split parent (parent only)."""
    family_id = to_uuid_required(current_user.family_id)
    parent = await TransactionService.replace_split_children(
        db, transaction_id, family_id, data.splits
    )
    children = await TransactionService.get_split_children(db, parent.id, family_id)
    return _build_split_response(parent, children)


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


@router.post("/import/file", status_code=status.HTTP_200_OK)
async def import_file_transactions_endpoint(
    file: UploadFile = File(..., description="OFX, QFX, QIF, or CAMT.053 XML file"),
    account_id: UUID = Form(..., description="Target account for import"),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Import transactions from an OFX/QFX, QIF, or CAMT.053 XML file (parent only).

    Automatically detects format, parses transactions, creates payees,
    applies categorization rules, and deduplicates via imported_id.

    Returns:
        {imported: int, skipped: int, errors: list}
    """
    try:
        # Validate account belongs to family
        from app.services.budget.account_service import AccountService
        await AccountService.get_by_id(
            db, account_id, to_uuid_required(current_user.family_id)
        )

        file_bytes = await file.read()
        result = await import_file_transactions(
            db=db,
            family_id=to_uuid_required(current_user.family_id),
            account_id=account_id,
            filename=file.filename or "unknown",
            file_bytes=file_bytes,
        )
        return result
    except Exception as e:
        return {"imported": 0, "skipped": 0, "errors": [str(e)]}


@router.post("/scan-receipt", status_code=status.HTTP_200_OK)
async def scan_receipt_endpoint(
    file: UploadFile = File(..., description="Receipt photo or scanned PDF (JPEG, PNG, WebP, GIF, PDF)"),
    account_id: UUID = Form(..., description="Target account for the transaction"),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Scan a receipt (image or PDF) and create a transaction (parent only, premium feature).

    Uses a vision model via the LiteLLM proxy to extract date, amount,
    payee, and line items from the receipt. PDF uploads are rasterized
    first-page-to-PNG in memory via PyMuPDF before the vision call — a
    single call to this endpoint therefore handles both phone photos
    and iOS "Scan Document" PDFs without the caller having to convert.

    Auto-creates the payee if new, applies categorization rules, and
    creates the transaction. Returns scanned data, confidence score,
    and the created transaction ID.
    """
    family_id = to_uuid_required(current_user.family_id)

    # Gate behind premium
    await require_feature("receipt_scan", db, current_user)

    # Track usage
    await UsageService.increment(db, family_id, "receipt_scan")

    # Validate account belongs to family
    from app.services.budget.account_service import AccountService
    await AccountService.get_by_id(db, account_id, family_id)

    # Validate file type. PDF is accepted — receipt_scanner_service
    # rasterizes the first page to PNG in memory before the vision call.
    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "application/pdf",
    }
    content_type = file.content_type or "image/jpeg"
    if content_type not in allowed_types:
        return {
            "success": False,
            "message": (
                f"Unsupported file type: {content_type}. "
                "Use JPEG, PNG, WebP, GIF, or PDF."
            ),
            "scanned_data": None,
            "transaction_id": None,
        }

    file_bytes = await file.read()

    # Max 10MB (applies to the raw upload; rasterized PNG will be smaller)
    if len(file_bytes) > 10 * 1024 * 1024:
        return {
            "success": False,
            "message": "File too large. Maximum size is 10MB.",
            "scanned_data": None,
            "transaction_id": None,
        }

    result = await scan_and_create_transaction(
        db=db,
        family_id=family_id,
        account_id=account_id,
        image_bytes=file_bytes,
        media_type=content_type,
    )
    return result

