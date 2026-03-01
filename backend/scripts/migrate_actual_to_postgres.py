#!/usr/bin/env python3
"""
Migrate data from Actual Budget to PostgreSQL Budget System

This script migrates all budget data from Actual Budget to the Family Task Manager's
internal PostgreSQL budget system using the Actual Python library.

Usage:
    python migrate_actual_to_postgres.py --family-id <UUID> --budget-file-id <ID> [--dry-run]
    
Example:
    python migrate_actual_to_postgres.py \
        --family-id ce875133-1b85-4bfc-8e61-b52309381f0b \
        --budget-file-id be31aae9-7308-4623-9a94-d1ea5c58b381 \
        --dry-run
"""

import argparse
import asyncio
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.budget import (
    BudgetAccount,
    BudgetAllocation,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetPayee,
    BudgetTransaction,
)

# Import Actual Budget library
try:
    from actual import Actual
    from actual.queries import (
        get_accounts,
        get_transactions,
        get_category_groups,
        get_categories,
        get_payees,
    )
except ImportError:
    print("❌ Error: 'actual' library not installed. Install with: pip install actualpy")
    sys.exit(1)


class ActualBudgetMigration:
    """Migrates data from Actual Budget to PostgreSQL"""
    
    def __init__(
        self,
        budget_file_id: str,
        family_id: UUID,
        dry_run: bool = False,
        verbose: bool = True
    ):
        self.budget_file_id = budget_file_id
        self.family_id = family_id
        self.dry_run = dry_run
        self.verbose = verbose
        
        # Actual Budget server configuration
        self.actual_server_url = os.getenv("ACTUAL_SERVER_URL", "http://localhost:5006")
        self.actual_password = os.getenv("ACTUAL_PASSWORD", "jc")
        
        # Track migration mappings (actual_id -> postgres_id)
        self.category_group_map: Dict[str, UUID] = {}
        self.category_map: Dict[str, UUID] = {}
        self.account_map: Dict[str, UUID] = {}
        self.payee_map: Dict[str, UUID] = {}
        
        # Track errors and skipped records
        self.errors: List[Dict[str, str]] = []
        self.skipped: Dict[str, List[str]] = {
            "category_groups": [],
            "categories": [],
            "accounts": [],
            "payees": [],
            "transactions": [],
            "allocations": [],
        }
        
        # Statistics
        self.stats = {
            "category_groups": 0,
            "categories": 0,
            "accounts": 0,
            "payees": 0,
            "transactions": 0,
            "allocations": 0,
            "skipped_duplicates": 0,
            "skipped_validation": 0,
            "errors": 0,
        }
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message"""
        if self.verbose:
            prefix = "🔍 DRY RUN" if self.dry_run else "✅"
            print(f"{prefix} [{level}] {message}")
    
    def add_error(self, entity_type: str, entity_id: str, reason: str):
        """Track migration errors"""
        error = {
            "entity": entity_type,
            "id": entity_id,
            "reason": reason
        }
        self.errors.append(error)
        self.stats["errors"] += 1
        self.log(f"  ❌ ERROR: {entity_type} {entity_id}: {reason}", "ERROR")
    
    def add_skip(self, entity_type: str, entity_id: str, reason: str = ""):
        """Track skipped records with reasons"""
        skip_msg = f"{entity_id}"
        if reason:
            skip_msg += f" ({reason})"
        self.skipped[entity_type].append(skip_msg)
        self.stats["skipped_validation"] += 1
        if self.verbose and self.stats["skipped_validation"] % 10 == 0:
            self.log(f"  ... {self.stats['skipped_validation']} records skipped so far")
    
    def validate_string(self, value: Optional[str], field_name: str, max_length: int = 255) -> Optional[str]:
        """Validate and clean string fields"""
        if not value:
            return None
        value_str = str(value).strip()
        if len(value_str) > max_length:
            value_str = value_str[:max_length]
        return value_str if value_str else None
    
    def validate_amount(self, amount: Optional[int], field_name: str) -> Optional[int]:
        """Validate amount field (should be integer cents)"""
        if amount is None:
            return 0
        try:
            return int(amount)
        except (ValueError, TypeError) as e:
            self.log(f"  ⚠️ Invalid amount for {field_name}: {amount} -> using 0", "WARN")
            return 0
    
    def validate_sort_order(self, sort_order: Optional[int]) -> int:
        """Validate and default sort order"""
        if sort_order is None:
            return 0
        try:
            return int(sort_order)
        except (ValueError, TypeError):
            return 0
    
    async def migrate_category_groups(self, db: AsyncSession, actual: Actual):
        """Migrate category groups from Actual Budget"""
        self.log("Migrating category groups...")
        
        try:
            groups = get_category_groups(actual.session)
        except Exception as e:
            self.add_error("category_groups", "all", f"Failed to fetch: {e}")
            return
        
        if not groups:
            self.log("  ℹ️ No category groups found in Actual Budget")
            return
        
        for group in groups:
            try:
                # Skip internal/hidden groups
                if group.hidden or not group.name:
                    self.add_skip("category_groups", getattr(group, "id", "unknown"), "hidden or no name")
                    continue
                
                # Validate name
                group_name = self.validate_string(group.name, "name", 100)
                if not group_name:
                    self.add_skip("category_groups", getattr(group, "id", "unknown"), "empty name after validation")
                    continue
                
                group_id = uuid4()
                self.category_group_map[str(group.id)] = group_id
                
                budget_group = BudgetCategoryGroup(
                    id=group_id,
                    family_id=self.family_id,
                    name=group_name,
                    is_income=getattr(group, "is_income", False) or False,
                    sort_order=self.validate_sort_order(getattr(group, "sort_order", 0)),
                )
                
                if not self.dry_run:
                    db.add(budget_group)
                
                self.stats["category_groups"] += 1
                self.log(f"  ✓ Category group: {group_name} (income={group.is_income})")
            
            except Exception as e:
                self.add_error("category_groups", getattr(group, "id", "unknown"), str(e))
                continue
        
        if not self.dry_run:
            await db.flush()
    
    async def migrate_categories(self, db: AsyncSession, actual: Actual):
        """Migrate categories from Actual Budget"""
        self.log("Migrating categories...")
        
        try:
            categories = get_categories(actual.session)
        except Exception as e:
            self.add_error("categories", "all", f"Failed to fetch: {e}")
            return
        
        if not categories:
            self.log("  ℹ️ No categories found in Actual Budget")
            return
        
        for category in categories:
            try:
                # Skip hidden/deleted categories
                if category.hidden or category.tombstone or not category.name:
                    self.add_skip("categories", getattr(category, "id", "unknown"), "hidden, deleted, or no name")
                    continue
                
                # Validate name
                category_name = self.validate_string(category.name, "name", 100)
                if not category_name:
                    self.add_skip("categories", getattr(category, "id", "unknown"), "empty name after validation")
                    continue
                
                # Map to category group
                group_uuid = self.category_group_map.get(str(category.cat_group))
                if not group_uuid:
                    self.add_skip("categories", getattr(category, "id", "unknown"), f"group {category.cat_group} not found")
                    continue
                
                category_id = uuid4()
                self.category_map[str(category.id)] = category_id
                
                budget_category = BudgetCategory(
                    id=category_id,
                    family_id=self.family_id,
                    group_id=group_uuid,
                    name=category_name,
                    sort_order=self.validate_sort_order(getattr(category, "sort_order", 0)),
                    hidden=False,
                    rollover_enabled=True,
                    goal_amount=0,
                )
                
                if not self.dry_run:
                    db.add(budget_category)
                
                self.stats["categories"] += 1
                self.log(f"  ✓ Category: {category_name}")
            
            except Exception as e:
                self.add_error("categories", getattr(category, "id", "unknown"), str(e))
                continue
        
        if not self.dry_run:
            await db.flush()
    
    async def migrate_accounts(self, db: AsyncSession, actual: Actual):
        """Migrate accounts from Actual Budget"""
        self.log("Migrating accounts...")
        
        try:
            accounts = get_accounts(actual.session)
        except Exception as e:
            self.add_error("accounts", "all", f"Failed to fetch: {e}")
            return
        
        if not accounts:
            self.log("  ℹ️ No accounts found in Actual Budget")
            return
        
        for account in accounts:
            try:
                # Skip closed/deleted accounts
                if account.closed or account.tombstone or not account.name:
                    self.add_skip("accounts", getattr(account, "id", "unknown"), "closed, deleted, or no name")
                    continue
                
                # Validate name
                account_name = self.validate_string(account.name, "name", 200)
                if not account_name:
                    self.add_skip("accounts", getattr(account, "id", "unknown"), "empty name after validation")
                    continue
                
                account_id = uuid4()
                self.account_map[str(account.id)] = account_id
                
                # Determine account type based on name
                account_type = "checking"
                name_lower = account_name.lower()
                if "savings" in name_lower or "ahorros" in name_lower:
                    account_type = "savings"
                elif "credit" in name_lower or "crédito" in name_lower or "cc" in name_lower:
                    account_type = "credit_card"
                elif "cash" in name_lower or "efectivo" in name_lower:
                    account_type = "cash"
                elif "investment" in name_lower or "inversión" in name_lower:
                    account_type = "investment"
                
                budget_account = BudgetAccount(
                    id=account_id,
                    family_id=self.family_id,
                    name=account_name,
                    type=account_type,
                    offbudget=getattr(account, "offbudget", False) or False,
                    closed=False,
                    sort_order=0,
                )
                
                if not self.dry_run:
                    db.add(budget_account)
                
                self.stats["accounts"] += 1
                self.log(f"  ✓ Account: {account_name} ({account_type})")
            
            except Exception as e:
                self.add_error("accounts", getattr(account, "id", "unknown"), str(e))
                continue
        
        if not self.dry_run:
            await db.flush()
    
    async def migrate_payees(self, db: AsyncSession, actual: Actual):
        """Migrate payees from Actual Budget"""
        self.log("Migrating payees...")
        
        try:
            payees = get_payees(actual.session)
        except Exception as e:
            self.log(f"⚠️ Could not fetch payees: {e}. Skipping payee migration.", "WARN")
            return
        
        if not payees:
            self.log("  ℹ️ No payees found in Actual Budget")
            return
        
        for payee in payees:
            try:
                # Skip deleted payees
                if payee.tombstone or not payee.name:
                    self.add_skip("payees", getattr(payee, "id", "unknown"), "deleted or no name")
                    continue
                
                # Validate name
                payee_name = self.validate_string(payee.name, "name", 200)
                if not payee_name:
                    self.add_skip("payees", getattr(payee, "id", "unknown"), "empty name after validation")
                    continue
                
                payee_id = uuid4()
                self.payee_map[str(payee.id)] = payee_id
                
                budget_payee = BudgetPayee(
                    id=payee_id,
                    family_id=self.family_id,
                    name=payee_name,
                )
                
                if not self.dry_run:
                    db.add(budget_payee)
                
                self.stats["payees"] += 1
                self.log(f"  ✓ Payee: {payee_name}")
            
            except Exception as e:
                self.add_error("payees", getattr(payee, "id", "unknown"), str(e))
                continue
        
        if not self.dry_run:
            await db.flush()
    
    async def migrate_transactions(self, db: AsyncSession, actual: Actual):
        """Migrate transactions from Actual Budget"""
        self.log("Migrating transactions...")
        
        try:
            transactions = get_transactions(actual.session)
        except Exception as e:
            self.add_error("transactions", "all", f"Failed to fetch: {e}")
            return
        
        if not transactions:
            self.log("  ℹ️ No transactions found in Actual Budget")
            return
        
        for tx in transactions:
            try:
                # Skip deleted transactions or parent transfers
                if tx.tombstone or tx.isParent:
                    self.add_skip("transactions", getattr(tx, "id", "unknown"), "deleted or parent transaction")
                    continue
                
                # Map account
                account_uuid = self.account_map.get(str(tx.acct))
                if not account_uuid:
                    self.add_skip("transactions", getattr(tx, "id", "unknown"), f"account {tx.acct} not found")
                    continue
                
                # Map category (optional)
                category_uuid = None
                if hasattr(tx, "category") and tx.category:
                    category_uuid = self.category_map.get(str(tx.category))
                
                # Map payee (optional)
                payee_uuid = None
                if hasattr(tx, "payee") and tx.payee:
                    payee_uuid = self.payee_map.get(str(tx.payee))
                
                # Check for duplicate by imported_id
                if hasattr(tx, "imported_id") and tx.imported_id:
                    existing_query = select(BudgetTransaction).where(
                        and_(
                            BudgetTransaction.family_id == self.family_id,
                            BudgetTransaction.imported_id == tx.imported_id
                        )
                    )
                    existing = await db.execute(existing_query)
                    if existing.scalar_one_or_none():
                        self.stats["skipped_duplicates"] += 1
                        continue
                
                # Validate and parse date
                try:
                    tx_date = tx.date if hasattr(tx, "date") and tx.date else date.today()
                    if isinstance(tx_date, str):
                        tx_date = date.fromisoformat(tx_date)
                except (ValueError, TypeError):
                    tx_date = date.today()
                    self.log(f"  ⚠️ Invalid date for transaction {getattr(tx, 'id', 'unknown')}: using today", "WARN")
                
                # Validate amount
                amount_cents = self.validate_amount(getattr(tx, "amount", 0), "transaction amount")
                
                transaction_id = uuid4()
                
                budget_transaction = BudgetTransaction(
                    id=transaction_id,
                    family_id=self.family_id,
                    account_id=account_uuid,
                    category_id=category_uuid,
                    payee_id=payee_uuid,
                    date=tx_date,
                    amount=amount_cents,
                    notes=self.validate_string(getattr(tx, "notes", ""), "notes") or "",
                    cleared=getattr(tx, "cleared", False) or False,
                    reconciled=False,
                    imported_id=self.validate_string(getattr(tx, "imported_id", None), "imported_id", 255),
                    is_parent=False,
                )
                
                if not self.dry_run:
                    db.add(budget_transaction)
                
                self.stats["transactions"] += 1
                
                if self.stats["transactions"] % 100 == 0:
                    self.log(f"  ... {self.stats['transactions']} transactions migrated")
            
            except Exception as e:
                self.add_error("transactions", getattr(tx, "id", "unknown"), str(e))
                continue
        
        if not self.dry_run:
            await db.flush()
        
        self.log(f"  ✓ Total transactions migrated: {self.stats['transactions']}")
    
    async def migrate_allocations(self, db: AsyncSession, actual: Actual):
        """
        Migrate budget allocations (budgeted amounts per category per month).
        
        Actual Budget stores this in the zero_budgets table.
        """
        self.log("Migrating budget allocations...")
        
        try:
            # Query zero_budgets table directly using SQLAlchemy text
            query = text("""
                SELECT category, month, amount
                FROM zero_budgets
                WHERE amount IS NOT NULL AND amount != 0
                ORDER BY month, category
            """)
            
            result = actual.session.execute(query)
            allocations_data = list(result)
        except Exception as e:
            self.add_error("allocations", "all", f"Failed to fetch: {e}")
            return
        
        if not allocations_data:
            self.log("  ℹ️ No budget allocations found in Actual Budget")
            return
        
        for row in allocations_data:
            try:
                category_id_str = str(row[0])
                month_int = row[1]  # Format: 202602 for Feb 2026
                amount_cents = row[2]
                
                # Map category
                category_uuid = self.category_map.get(category_id_str)
                if not category_uuid:
                    self.add_skip("allocations", f"{category_id_str}-{month_int}", f"category {category_id_str} not found")
                    continue
                
                # Parse month (convert 202602 to "2026-02-01")
                try:
                    month_str = str(month_int).zfill(6)  # Ensure 6 digits
                    year = int(month_str[:4])
                    month = int(month_str[4:6])
                    if month < 1 or month > 12:
                        self.add_skip("allocations", f"{category_id_str}-{month_int}", f"invalid month {month}")
                        continue
                    month_date = date(year, month, 1)
                except (ValueError, TypeError) as e:
                    self.add_skip("allocations", f"{category_id_str}-{month_int}", f"invalid month format: {e}")
                    continue
                
                # Validate amount
                validated_amount = self.validate_amount(amount_cents, "allocation amount")
                
                # Check for existing allocation
                existing_query = select(BudgetAllocation).where(
                    and_(
                        BudgetAllocation.family_id == self.family_id,
                        BudgetAllocation.category_id == category_uuid,
                        BudgetAllocation.month == month_date
                    )
                )
                existing = await db.execute(existing_query)
                if existing.scalar_one_or_none():
                    self.stats["skipped_duplicates"] += 1
                    continue
                
                allocation = BudgetAllocation(
                    id=uuid4(),
                    family_id=self.family_id,
                    category_id=category_uuid,
                    month=month_date,
                    budgeted_amount=validated_amount,
                )
                
                if not self.dry_run:
                    db.add(allocation)
                
                self.stats["allocations"] += 1
            
            except Exception as e:
                self.add_error("allocations", f"row-{allocations_data.index(row)}", str(e))
                continue
        
        if not self.dry_run:
            await db.flush()
        
        self.log(f"  ✓ Total allocations migrated: {self.stats['allocations']}")
    
    async def validate_migration(self, db: AsyncSession) -> Tuple[bool, List[str]]:
        """
        Validate the migrated data integrity before committing.
        
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        
        try:
            # Check if there are any categories without groups
            orphan_categories = await db.execute(
                select(BudgetCategory).where(
                    and_(
                        BudgetCategory.family_id == self.family_id,
                        BudgetCategory.group_id.notin_(
                            select(BudgetCategoryGroup.id).where(
                                BudgetCategoryGroup.family_id == self.family_id
                            )
                        )
                    )
                )
            )
            if orphan_categories.scalars().first():
                issues.append("Found categories without valid groups")
            
            # Check if there are transactions without accounts
            orphan_transactions = await db.execute(
                select(BudgetTransaction).where(
                    and_(
                        BudgetTransaction.family_id == self.family_id,
                        BudgetTransaction.account_id.notin_(
                            select(BudgetAccount.id).where(
                                BudgetAccount.family_id == self.family_id
                            )
                        )
                    )
                )
            )
            if orphan_transactions.scalars().first():
                issues.append("Found transactions without valid accounts")
            
            # Check if allocations have valid categories
            orphan_allocations = await db.execute(
                select(BudgetAllocation).where(
                    and_(
                        BudgetAllocation.family_id == self.family_id,
                        BudgetAllocation.category_id.notin_(
                            select(BudgetCategory.id).where(
                                BudgetCategory.family_id == self.family_id
                            )
                        )
                    )
                )
            )
            if orphan_allocations.scalars().first():
                issues.append("Found allocations without valid categories")
            
        except Exception as e:
            issues.append(f"Validation error: {e}")
        
        is_valid = len(issues) == 0
        return is_valid, issues
    
    async def run(self) -> Dict[str, int]:
        """Run the full migration"""
        self.log("=" * 60)
        self.log("Starting Actual Budget → PostgreSQL Migration")
        self.log(f"Family ID: {self.family_id}")
        self.log(f"Budget File ID: {self.budget_file_id}")
        self.log(f"Actual Server: {self.actual_server_url}")
        self.log(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE MIGRATION'}")
        self.log("=" * 60)
        
        # Create database session
        engine = create_async_engine(
            settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://'),
            echo=False
        )
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        
        try:
            # Connect to Actual Budget
            self.log("Connecting to Actual Budget...")
            with Actual(
                base_url=self.actual_server_url,
                password=self.actual_password,
                file=self.budget_file_id
            ) as actual:
                self.log("✓ Connected to Actual Budget")
                
                # Create database session
                async with AsyncSessionLocal() as db:
                    # Run migrations in order
                    await self.migrate_category_groups(db, actual)
                    await self.migrate_categories(db, actual)
                    await self.migrate_accounts(db, actual)
                    await self.migrate_payees(db, actual)
                    await self.migrate_transactions(db, actual)
                    await self.migrate_allocations(db, actual)
                    
                    # Validate data integrity before commit
                    is_valid, validation_issues = await self.validate_migration(db)
                    
                    if not is_valid and not self.dry_run:
                        self.log("=" * 60, "ERROR")
                        self.log("❌ DATA INTEGRITY VALIDATION FAILED", "ERROR")
                        for issue in validation_issues:
                            self.log(f"  - {issue}", "ERROR")
                        self.log("❌ Rolling back migration to prevent data corruption", "ERROR")
                        self.log("=" * 60, "ERROR")
                        await db.rollback()
                        raise Exception("Migration validation failed. Rollback completed.")
                    
                    # Commit or rollback
                    if self.dry_run:
                        self.log("DRY RUN: Rolling back all changes")
                        await db.rollback()
                    else:
                        self.log("Validating and committing changes to database...")
                        await db.commit()
                        self.log("✅ Migration completed successfully!")
        
        except Exception as e:
            self.log(f"❌ Migration failed: {e}", "ERROR")
            raise
        
        finally:
            await engine.dispose()
        
        # Print summary
        self.log("=" * 60)
        self.log("Migration Summary:")
        self.log(f"  Category Groups: {self.stats['category_groups']}")
        self.log(f"  Categories: {self.stats['categories']}")
        self.log(f"  Accounts: {self.stats['accounts']}")
        self.log(f"  Payees: {self.stats['payees']}")
        self.log(f"  Transactions: {self.stats['transactions']}")
        self.log(f"  Budget Allocations: {self.stats['allocations']}")
        self.log(f"  Skipped Duplicates: {self.stats['skipped_duplicates']}")
        self.log(f"  Skipped (Validation): {self.stats['skipped_validation']}")
        self.log(f"  Errors: {self.stats['errors']}")
        self.log("=" * 60)
        
        # Print skipped records summary
        if any(self.skipped.values()):
            self.log("\nSkipped Records by Entity Type:")
            for entity_type, skipped_list in self.skipped.items():
                if skipped_list:
                    self.log(f"  {entity_type}: {len(skipped_list)} skipped")
                    if len(skipped_list) <= 10:
                        for item in skipped_list:
                            self.log(f"    - {item}")
                    else:
                        for item in skipped_list[:5]:
                            self.log(f"    - {item}")
                        self.log(f"    ... and {len(skipped_list) - 5} more")
        
        # Print errors summary
        if self.errors:
            self.log("\nMigration Errors:")
            for error in self.errors[:20]:  # Show first 20 errors
                self.log(f"  {error['entity']}: {error['id']} - {error['reason']}", "ERROR")
            if len(self.errors) > 20:
                self.log(f"  ... and {len(self.errors) - 20} more errors", "ERROR")
        
        return self.stats


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Migrate data from Actual Budget to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (no changes committed)
  python migrate_actual_to_postgres.py \\
    --family-id ce875133-1b85-4bfc-8e61-b52309381f0b \\
    --budget-file-id be31aae9-7308-4623-9a94-d1ea5c58b381 \\
    --dry-run

  # Live migration (changes committed to database)
  python migrate_actual_to_postgres.py \\
    --family-id ce875133-1b85-4bfc-8e61-b52309381f0b \\
    --budget-file-id be31aae9-7308-4623-9a94-d1ea5c58b381
        """
    )
    parser.add_argument(
        "--family-id",
        required=True,
        help="UUID of the family to migrate data for"
    )
    parser.add_argument(
        "--budget-file-id",
        required=True,
        help="Actual Budget file ID (e.g., be31aae9-7308-4623-9a94-d1ea5c58b381)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run migration without committing changes (for testing)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output"
    )
    
    args = parser.parse_args()
    
    try:
        family_uuid = UUID(args.family_id)
    except ValueError:
        print(f"❌ Invalid family ID: {args.family_id}")
        sys.exit(1)
    
    migration = ActualBudgetMigration(
        budget_file_id=args.budget_file_id,
        family_id=family_uuid,
        dry_run=args.dry_run,
        verbose=not args.quiet
    )
    
    try:
        stats = await migration.run()
        
        if args.dry_run:
            print("\n✅ Dry run completed successfully!")
            print("   Review the output above to verify the migration will work correctly.")
            print("   Run without --dry-run to perform the actual migration.")
            if migration.stats["errors"] > 0:
                print(f"\n   ⚠️ WARNING: {migration.stats['errors']} errors detected during dry run.")
                print("   Fix these issues in Actual Budget before running the live migration.")
        else:
            print("\n✅ Migration completed successfully!")
            print(f"   Migrated {stats['transactions']} transactions, {stats['categories']} categories,")
            print(f"   {stats['accounts']} accounts, {stats['payees']} payees, and more.")
            if migration.stats["errors"] > 0:
                print(f"\n   ⚠️ WARNING: {migration.stats['errors']} errors occurred during migration.")
                print("   Review the error log above for details.")
        
        sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
