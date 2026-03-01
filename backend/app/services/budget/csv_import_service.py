"""
CSV Import Service for Budget Transactions

Handles parsing and importing CSV files containing financial transactions.
Supports multiple CSV formats (bank exports, etc.) with configurable column mapping.
"""

import csv
from io import StringIO
from datetime import datetime, date
from typing import List, Optional, Dict, Tuple
from uuid import UUID
import re

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.budget import BudgetTransaction, BudgetPayee, BudgetAccount, BudgetCategory
from app.services.budget.transaction_service import TransactionService
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.schemas.budget import TransactionCreate
from app.core.type_utils import to_uuid_required


class CSVImportError(Exception):
    """Base exception for CSV import errors"""
    pass


class CSVImportValidationError(CSVImportError):
    """Validation error during CSV import"""
    pass


class CSVImportRow:
    """Represents a single row from the CSV being imported"""
    
    def __init__(self, row_number: int, data: Dict[str, str]):
        self.row_number = row_number
        self.data = data
        self.errors: List[str] = []
    
    def add_error(self, error: str):
        self.errors.append(error)
    
    def is_valid(self) -> bool:
        return len(self.errors) == 0


class CSVImportResult:
    """Results of a CSV import operation"""
    
    def __init__(self):
        self.total_rows = 0
        self.successful_imports = 0
        self.skipped_rows = 0
        self.failed_rows: List[Tuple[int, List[str]]] = []
        self.created_payees: List[str] = []
        self.duplicate_count = 0
        self.import_errors: List[str] = []
    
    def add_success(self):
        self.successful_imports += 1
    
    def add_skip(self):
        self.skipped_rows += 1
    
    def add_failed_row(self, row_number: int, errors: List[str]):
        self.failed_rows.append((row_number, errors))
    
    def add_import_error(self, error: str):
        self.import_errors.append(error)
    
    def to_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "successful_imports": self.successful_imports,
            "skipped_rows": self.skipped_rows,
            "failed_rows": self.failed_rows,
            "created_payees": self.created_payees,
            "duplicate_count": self.duplicate_count,
            "import_errors": self.import_errors,
        }


class CSVImportService:
    """Service for importing transactions from CSV files"""
    
    # Supported CSV formats with their field mappings
    FORMATS = {
        "generic": {
            "date": ["date", "transaction_date", "fecha"],
            "amount": ["amount", "value", "monto", "quantity"],
            "description": ["description", "memo", "payee", "descripcion"],
            "account": ["account", "cuenta"],
            "category": ["category", "categoría"],
            "notes": ["notes", "notas", "comments"],
        },
        "ofx": {
            "date": ["DTPOSTED"],
            "amount": ["TRNAMT"],
            "description": ["MEMO"],
        },
        "quickbooks": {
            "date": ["Transaction Date"],
            "amount": ["Amount"],
            "description": ["Memo"],
            "account": ["Account"],
        }
    }
    
    @staticmethod
    async def parse_csv(
        csv_content: str,
        delimiter: str = ",",
        skip_rows: int = 0,
    ) -> Tuple[List[Dict[str, str]], List[str]]:
        """
        Parse CSV content and return list of row dictionaries
        
        Args:
            csv_content: Raw CSV file content as string
            delimiter: CSV delimiter (default: comma)
            skip_rows: Number of header rows to skip
            
        Returns:
            Tuple of (parsed_rows, errors)
        """
        errors: List[str] = []
        rows: List[Dict[str, str]] = []
        
        try:
            reader = csv.DictReader(
                StringIO(csv_content),
                delimiter=delimiter
            )
            
            if not reader.fieldnames:
                errors.append("CSV file has no headers")
                return rows, errors
            
            # Skip specified number of rows
            for _ in range(skip_rows):
                next(reader, None)
            
            # Parse rows
            for row_num, row in enumerate(reader, start=skip_rows + 2):
                # Skip empty rows
                if not any(row.values()):
                    continue
                
                rows.append(dict(row))
        
        except Exception as e:
            errors.append(f"Failed to parse CSV: {str(e)}")
        
        return rows, errors
    
    @staticmethod
    def _normalize_field_name(field: str) -> str:
        """Normalize field names for matching"""
        return field.lower().strip()
    
    @classmethod
    def _find_column(cls, fieldnames: List[str], possible_names: List[str]) -> Optional[str]:
        """Find a column by trying multiple possible names"""
        normalized_possible = [cls._normalize_field_name(n) for n in possible_names]
        
        for field in fieldnames:
            if cls._normalize_field_name(field) in normalized_possible:
                return field
        
        return None
    
    @classmethod
    def _detect_format(cls, fieldnames: List[str]) -> str:
        """Detect CSV format based on field names"""
        fieldnames_lower = [f.lower() for f in fieldnames]
        
        # Check for OFX format
        if any("DTPOSTED" in f or "TRNAMT" in f for f in fieldnames):
            return "ofx"
        
        # Check for QuickBooks format
        if any("Transaction Date" in f or "Account" in f for f in fieldnames):
            return "quickbooks"
        
        return "generic"
    
    @classmethod
    def _parse_date(cls, date_str: str) -> Optional[date]:
        """Try to parse various date formats"""
        if not date_str or not isinstance(date_str, str):
            return None
        
        date_str = date_str.strip()
        
        # Try common date formats
        formats = [
            "%Y-%m-%d",     # 2024-01-15
            "%m/%d/%Y",     # 01/15/2024
            "%d/%m/%Y",     # 15/01/2024
            "%Y/%m/%d",     # 2024/01/15
            "%m-%d-%Y",     # 01-15-2024
            "%d-%m-%Y",     # 15-01-2024
            "%B %d, %Y",    # January 15, 2024
            "%b %d, %Y",    # Jan 15, 2024
            "%d %B %Y",     # 15 January 2024
            "%d %b %Y",     # 15 Jan 2024
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        return None
    
    @classmethod
    def _parse_amount(cls, amount_str: str) -> Optional[int]:
        """Parse amount string to cents (int)"""
        if not amount_str or not isinstance(amount_str, str):
            return None
        
        amount_str = amount_str.strip()
        
        # Remove common currency symbols
        amount_str = re.sub(r"[$€¥£₱₹]", "", amount_str)
        
        # Handle parentheses for negative amounts (accounting format)
        if amount_str.startswith("(") and amount_str.endswith(")"):
            amount_str = "-" + amount_str[1:-1]
        
        # Remove thousands separators
        amount_str = amount_str.replace(",", "")
        
        try:
            # Convert to cents (multiply by 100)
            amount_float = float(amount_str)
            return int(round(amount_float * 100))
        except ValueError:
            return None
    
    @classmethod
    async def import_csv(
        cls,
        db: AsyncSession,
        family_id: UUID,
        csv_content: str,
        account_id: UUID,
        column_mapping: Optional[Dict[str, str]] = None,
        delimiter: str = ",",
        skip_header_rows: int = 0,
        create_payees: bool = True,
        prevent_duplicates: bool = True,
    ) -> CSVImportResult:
        """
        Import transactions from CSV file
        
        Args:
            db: Database session
            family_id: Family UUID
            csv_content: CSV file content as string
            account_id: Account to import transactions into
            column_mapping: Custom mapping of column names (e.g., {"date": "Transaction Date"})
            delimiter: CSV delimiter
            skip_header_rows: Number of header rows to skip
            create_payees: Automatically create payees if they don't exist
            prevent_duplicates: Check imported_id to prevent duplicate imports
            
        Returns:
            CSVImportResult with import statistics
        """
        result = CSVImportResult()
        
        # Parse CSV
        rows, parse_errors = await cls.parse_csv(csv_content, delimiter, skip_header_rows)
        result.import_errors.extend(parse_errors)
        
        if not rows:
            return result
        
        result.total_rows = len(rows)
        
        # Detect format if column mapping not provided
        if not column_mapping:
            format_type = cls._detect_format(list(rows[0].keys()) if rows else [])
            column_mapping = {}
        
        # Build effective column names
        fieldnames = list(rows[0].keys()) if rows else []
        
        # Map required fields
        date_col = column_mapping.get("date") or cls._find_column(
            fieldnames, cls.FORMATS["generic"]["date"]
        )
        amount_col = column_mapping.get("amount") or cls._find_column(
            fieldnames, cls.FORMATS["generic"]["amount"]
        )
        description_col = column_mapping.get("description") or cls._find_column(
            fieldnames, cls.FORMATS["generic"]["description"]
        )
        
        category_col = column_mapping.get("category") or cls._find_column(
            fieldnames, cls.FORMATS["generic"]["category"]
        )
        notes_col = column_mapping.get("notes") or cls._find_column(
            fieldnames, cls.FORMATS["generic"]["notes"]
        )
        
        # Validate required columns exist
        if not date_col:
            result.add_import_error("Could not find date column")
            return result
        if not amount_col:
            result.add_import_error("Could not find amount column")
            return result
        
        # Process each row
        for row_data in rows:
            # Parse date
            date_val = cls._parse_date(row_data.get(date_col, ""))
            if not date_val:
                result.add_failed_row(
                    rows.index(row_data) + skip_header_rows + 2,
                    [f"Invalid date: {row_data.get(date_col, '')}"]
                )
                continue
            
            # Parse amount
            amount_val = cls._parse_amount(row_data.get(amount_col, ""))
            if amount_val is None:
                result.add_failed_row(
                    rows.index(row_data) + skip_header_rows + 2,
                    [f"Invalid amount: {row_data.get(amount_col, '')}"]
                )
                continue
            
            # Get description/payee
            description = ""
            if description_col:
                description = row_data.get(description_col, "").strip() or "Imported Transaction"
            else:
                description = "Imported Transaction"
            
            # Check for duplicates
            if prevent_duplicates and description:
                stmt = select(BudgetTransaction).where(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id == account_id,
                    BudgetTransaction.date == date_val,
                    BudgetTransaction.amount == amount_val,
                    BudgetTransaction.imported_id == description,
                )
                result_set = await db.execute(stmt)
                existing = result_set.scalars().first()
                if existing:
                    result.add_skip()
                    result.duplicate_count += 1
                    continue
            
            # Find or create payee
            payee_id: Optional[UUID] = None
            if description and create_payees:
                stmt = select(BudgetPayee).where(
                    BudgetPayee.family_id == family_id,
                    BudgetPayee.name == description,
                )
                payee_result = await db.execute(stmt)
                payee = payee_result.scalars().first()
                if payee:
                    payee_id = payee.id
                else:
                    # Create new payee
                    new_payee = BudgetPayee(
                        family_id=family_id,
                        name=description
                    )
                    db.add(new_payee)
                    await db.flush()
                    payee_id = new_payee.id
                    result.created_payees.append(description)
            
            # Get category if specified, or use auto-categorization
            category_id: Optional[UUID] = None
            if category_col and row_data.get(category_col):
                category_name = row_data.get(category_col, "").strip()
                if category_name:
                    stmt = select(BudgetCategory).where(
                        BudgetCategory.family_id == family_id,
                        BudgetCategory.name == category_name,
                    )
                    cat_result = await db.execute(stmt)
                    category = cat_result.scalars().first()
                    if category:
                        category_id = category.id
            
            # If no category found, try auto-categorization based on payee/description
            if not category_id:
                category_id = await CategorizationRuleService.suggest_category(
                    db,
                    family_id,
                    payee=description,  # Description is used as payee
                    description=None,  # We don't have a separate description field from CSV
                )
            
            # Get notes if specified
            notes = None
            if notes_col and row_data.get(notes_col):
                notes = row_data.get(notes_col, "").strip()
            
            # Create transaction
            try:
                transaction_data = TransactionCreate(
                    account_id=account_id,
                    date=date_val,
                    amount=amount_val,
                    payee_id=payee_id,
                    category_id=category_id,
                    notes=notes,
                    imported_id=description,
                    cleared=False,
                    reconciled=False,
                    parent_id=None,
                    is_parent=False,
                    transfer_account_id=None,
                )
                
                await TransactionService.create(db, family_id, transaction_data)
                result.add_success()
            
            except Exception as e:
                result.add_failed_row(
                    rows.index(row_data) + skip_header_rows + 2,
                    [f"Failed to create transaction: {str(e)}"]
                )
        
        await db.commit()
        return result
