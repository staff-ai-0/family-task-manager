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
        
        # Statistics
        self.stats = {
            "category_groups": 0,
            "categories": 0,
            "accounts": 0,
            "payees": 0,
            "transactions": 0,
            "allocations": 0,
            "skipped_duplicates": 0,
        }
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message"""
        if self.verbose:
            prefix = "🔍 DRY RUN" if self.dry_run else "✅"
            print(f"{prefix} [{level}] {message}")
    
    async def migrate_category_groups(self, db: AsyncSession, actual: Actual):
        """Migrate category groups from Actual Budget"""
        self.log("Migrating category groups...")
        
        groups = get_category_groups(actual.session)
        
        for group in groups:
            # Skip internal/hidden groups
            if group.hidden or not group.name:
                continue
            
            group_id = uuid4()
            self.category_group_map[str(group.id)] = group_id
            
            budget_group = BudgetCategoryGroup(
                id=group_id,
                family_id=self.family_id,
                name=group.name,
                is_income=group.is_income or False,
                sort_order=group.sort_order or 0,
            )
            
            if not self.dry_run:
                db.add(budget_group)
            
            self.stats["category_groups"] += 1
            self.log(f"  ✓ Category group: {group.name} (income={group.is_income})")
        
        if not self.dry_run:
            await db.flush()
    
    async def migrate_categories(self, db: AsyncSession, actual: Actual):
        """Migrate categories from Actual Budget"""
        self.log("Migrating categories...")
        
        categories = get_categories(actual.session)
        
        for category in categories:
            # Skip hidden/deleted categories
            if category.hidden or category.tombstone or not category.name:
                continue
            
            # Map to category group
            group_uuid = self.category_group_map.get(str(category.cat_group))
            if not group_uuid:
                self.log(f"  ⚠️ Skipping category {category.name}: group not found", "WARN")
                continue
            
            category_id = uuid4()
            self.category_map[str(category.id)] = category_id
            
            budget_category = BudgetCategory(
                id=category_id,
                family_id=self.family_id,
                group_id=group_uuid,
                name=category.name,
                is_income=category.is_income or False,
                sort_order=category.sort_order or 0,
            )
            
            if not self.dry_run:
                db.add(budget_category)
            
            self.stats["categories"] += 1
            self.log(f"  ✓ Category: {category.name}")
        
        if not self.dry_run:
            await db.flush()
    
    async def migrate_accounts(self, db: AsyncSession, actual: Actual):
        """Migrate accounts from Actual Budget"""
        self.log("Migrating accounts...")
        
        accounts = get_accounts(actual.session)
        
        for account in accounts:
            # Skip closed/deleted accounts
            if account.closed or account.tombstone or not account.name:
                continue
            
            account_id = uuid4()
            self.account_map[str(account.id)] = account_id
            
            # Determine account type based on name
            account_type = "checking"
            name_lower = account.name.lower()
            if "savings" in name_lower or "ahorros" in name_lower:
                account_type = "savings"
            elif "credit" in name_lower or "crédito" in name_lower:
                account_type = "credit_card"
            elif "cash" in name_lower or "efectivo" in name_lower:
                account_type = "cash"
            
            budget_account = BudgetAccount(
                id=account_id,
                family_id=self.family_id,
                name=account.name,
                type=account_type,
                off_budget=account.offbudget or False,
            )
            
            if not self.dry_run:
                db.add(budget_account)
            
            self.stats["accounts"] += 1
            self.log(f"  ✓ Account: {account.name} ({account_type})")
        
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
        
        for payee in payees:
            # Skip deleted payees
            if payee.tombstone or not payee.name:
                continue
            
            payee_id = uuid4()
            self.payee_map[str(payee.id)] = payee_id
            
            budget_payee = BudgetPayee(
                id=payee_id,
                family_id=self.family_id,
                name=payee.name,
            )
            
            if not self.dry_run:
                db.add(budget_payee)
            
            self.stats["payees"] += 1
            self.log(f"  ✓ Payee: {payee.name}")
        
        if not self.dry_run:
            await db.flush()
    
    async def migrate_transactions(self, db: AsyncSession, actual: Actual):
        """Migrate transactions from Actual Budget"""
        self.log("Migrating transactions...")
        
        transactions = get_transactions(actual.session)
        
        for tx in transactions:
            # Skip deleted transactions or parent transfers
            if tx.tombstone or tx.isParent:
                continue
            
            # Map account
            account_uuid = self.account_map.get(str(tx.acct))
            if not account_uuid:
                self.log(f"  ⚠️ Skipping transaction: account not found", "WARN")
                continue
            
            # Map category (optional)
            category_uuid = None
            if tx.category:
                category_uuid = self.category_map.get(str(tx.category))
            
            # Map payee (optional)
            payee_uuid = None
            if tx.payee:
                payee_uuid = self.payee_map.get(str(tx.payee))
            
            # Check for duplicate by imported_id
            if tx.imported_id:
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
            
            # Convert amount from cents to decimal
            amount = Decimal(tx.amount) / 100 if tx.amount else Decimal(0)
            
            # Parse date
            tx_date = tx.date if tx.date else date.today()
            
            transaction_id = uuid4()
            
            budget_transaction = BudgetTransaction(
                id=transaction_id,
                family_id=self.family_id,
                account_id=account_uuid,
                category_id=category_uuid,
                payee_id=payee_uuid,
                date=tx_date,
                amount=amount,
                notes=tx.notes or "",
                cleared=tx.cleared or False,
                reconciled=False,  # Actual doesn't have reconciled flag
                imported_id=tx.imported_id,
            )
            
            if not self.dry_run:
                db.add(budget_transaction)
            
            self.stats["transactions"] += 1
            
            if self.stats["transactions"] % 100 == 0:
                self.log(f"  ... {self.stats['transactions']} transactions migrated")
        
        if not self.dry_run:
            await db.flush()
        
        self.log(f"  ✓ Total transactions migrated: {self.stats['transactions']}")
    
    async def migrate_allocations(self, db: AsyncSession, actual: Actual):
        """
        Migrate budget allocations (budgeted amounts per category per month).
        
        Actual Budget stores this in the zero_budgets table.
        """
        self.log("Migrating budget allocations...")
        
        # Query zero_budgets table directly using SQLAlchemy text
        query = text("""
            SELECT category, month, amount
            FROM zero_budgets
            WHERE amount IS NOT NULL AND amount != 0
            ORDER BY month, category
        """)
        
        result = actual.session.execute(query)
        
        for row in result:
            category_id_str = str(row[0])
            month_int = row[1]  # Format: 202602 for Feb 2026
            amount_cents = row[2]
            
            # Map category
            category_uuid = self.category_map.get(category_id_str)
            if not category_uuid:
                continue
            
            # Parse month (convert 202602 to "2026-02-01")
            month_str = str(month_int)
            year = int(month_str[:4])
            month = int(month_str[4:6])
            month_date = date(year, month, 1)
            
            # Convert amount from cents
            amount = Decimal(amount_cents) / 100
            
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
                budgeted=amount,
            )
            
            if not self.dry_run:
                db.add(allocation)
            
            self.stats["allocations"] += 1
        
        if not self.dry_run:
            await db.flush()
        
        self.log(f"  ✓ Total allocations migrated: {self.stats['allocations']}")
    
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
                    
                    # Commit or rollback
                    if self.dry_run:
                        self.log("DRY RUN: Rolling back all changes")
                        await db.rollback()
                    else:
                        self.log("Committing changes to database...")
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
        self.log("=" * 60)
        
        return self.stats


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Migrate data from Actual Budget to PostgreSQL"
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
            print("\n✅ Dry run completed successfully. No data was modified.")
            print("   Run without --dry-run to perform the actual migration.")
        else:
            print("\n✅ Migration completed successfully!")
            print(f"   Migrated {stats['transactions']} transactions, "
                  f"{stats['categories']} categories, and more.")
        
        sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
