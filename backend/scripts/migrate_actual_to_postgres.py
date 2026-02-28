#!/usr/bin/env python3
"""
Migrate data from Actual Budget SQLite to PostgreSQL Budget System

This script migrates all budget data from Actual Budget to the Family Task Manager's
internal PostgreSQL budget system.

Usage:
    python migrate_actual_to_postgres.py --family-id <UUID> --actual-file <PATH> [--dry-run]
    
Example:
    python migrate_actual_to_postgres.py \
        --family-id ce875133-1b85-4bfc-8e61-b52309381f0b \
        --actual-file /path/to/actual-budget.sqlite \
        --dry-run
"""

import argparse
import asyncio
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.budget import (
    BudgetAccount,
    BudgetAllocation,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetPayee,
    BudgetTransaction,
)


class ActualBudgetMigration:
    """Migrates data from Actual Budget SQLite to PostgreSQL"""
    
    def __init__(
        self,
        actual_file_path: str,
        family_id: UUID,
        dry_run: bool = False,
        verbose: bool = True
    ):
        self.actual_file_path = actual_file_path
        self.family_id = family_id
        self.dry_run = dry_run
        self.verbose = verbose
        
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
        }
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message"""
        if self.verbose:
            prefix = "🔍 DRY RUN" if self.dry_run else "✅"
            print(f"{prefix} [{level}] {message}")
    
    def connect_actual_db(self) -> sqlite3.Connection:
        """Connect to Actual Budget SQLite database"""
        if not Path(self.actual_file_path).exists():
            raise FileNotFoundError(f"Actual Budget file not found: {self.actual_file_path}")
        
        conn = sqlite3.connect(self.actual_file_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn
    
    async def migrate_category_groups(self, db: AsyncSession, actual_conn: sqlite3.Connection):
        """Migrate category groups from Actual Budget"""
        self.log("Migrating category groups...")
        
        cursor = actual_conn.cursor()
        cursor.execute("""
            SELECT id, name, is_income, hidden, sort_order
            FROM category_groups
            WHERE tombstone = 0
            ORDER BY sort_order
        """)
        
        for row in cursor.fetchall():
            actual_id = row["id"]
            
            # Check if already exists
            existing = await db.execute(
                select(BudgetCategoryGroup).where(
                    and_(
                        BudgetCategoryGroup.family_id == self.family_id,
                        BudgetCategoryGroup.name == row["name"]
                    )
                )
            )
            existing_group = existing.scalar_one_or_none()
            
            if existing_group:
                self.log(f"  Category group '{row['name']}' already exists, skipping")
                self.category_group_map[actual_id] = existing_group.id
                continue
            
            if not self.dry_run:
                group = BudgetCategoryGroup(
                    id=uuid4(),
                    family_id=self.family_id,
                    name=row["name"] or "Uncategorized",
                    is_income=bool(row["is_income"]) if row["is_income"] is not None else False,
                    hidden=bool(row["hidden"]) if row["hidden"] is not None else False,
                    sort_order=row["sort_order"] or 0,
                )
                db.add(group)
                await db.flush()
                self.category_group_map[actual_id] = group.id
                self.log(f"  ✓ Created category group: {group.name}")
            else:
                mock_id = uuid4()
                self.category_group_map[actual_id] = mock_id
                self.log(f"  [DRY RUN] Would create category group: {row['name']}")
            
            self.stats["category_groups"] += 1
        
        cursor.close()
        self.log(f"Migrated {self.stats['category_groups']} category groups")
    
    async def migrate_categories(self, db: AsyncSession, actual_conn: sqlite3.Connection):
        """Migrate categories from Actual Budget"""
        self.log("Migrating categories...")
        
        cursor = actual_conn.cursor()
        cursor.execute("""
            SELECT id, name, cat_group as group_id, is_income, hidden, sort_order, goal_def
            FROM categories
            WHERE tombstone = 0
            ORDER BY sort_order
        """)
        
        for row in cursor.fetchall():
            actual_id = row["id"]
            actual_group_id = row["group_id"]
            
            # Map to PostgreSQL group
            if actual_group_id not in self.category_group_map:
                self.log(f"  ⚠️ Category '{row['name']}' references unknown group, skipping", "WARN")
                continue
            
            postgres_group_id = self.category_group_map[actual_group_id]
            
            # Check if already exists
            existing = await db.execute(
                select(BudgetCategory).where(
                    and_(
                        BudgetCategory.family_id == self.family_id,
                        BudgetCategory.name == row["name"],
                        BudgetCategory.group_id == postgres_group_id
                    )
                )
            )
            existing_category = existing.scalar_one_or_none()
            
            if existing_category:
                self.log(f"  Category '{row['name']}' already exists, skipping")
                self.category_map[actual_id] = existing_category.id
                continue
            
            # Parse goal amount if exists
            goal_amount = 0
            # Actual Budget stores goals in a JSON-like format, we'll skip complex parsing for now
            
            if not self.dry_run:
                category = BudgetCategory(
                    id=uuid4(),
                    family_id=self.family_id,
                    group_id=postgres_group_id,
                    name=row["name"] or "Uncategorized",
                    hidden=bool(row["hidden"]) if row["hidden"] is not None else False,
                    sort_order=row["sort_order"] or 0,
                    rollover_enabled=True,  # Default
                    goal_amount=goal_amount,
                )
                db.add(category)
                await db.flush()
                self.category_map[actual_id] = category.id
                self.log(f"  ✓ Created category: {category.name}")
            else:
                mock_id = uuid4()
                self.category_map[actual_id] = mock_id
                self.log(f"  [DRY RUN] Would create category: {row['name']}")
            
            self.stats["categories"] += 1
        
        cursor.close()
        self.log(f"Migrated {self.stats['categories']} categories")
    
    async def migrate_accounts(self, db: AsyncSession, actual_conn: sqlite3.Connection):
        """Migrate accounts from Actual Budget"""
        self.log("Migrating accounts...")
        
        cursor = actual_conn.cursor()
        cursor.execute("""
            SELECT id, name, offbudget, closed, sort_order
            FROM accounts
            WHERE tombstone = 0
            ORDER BY sort_order
        """)
        
        # Map Actual account types to our types
        type_map = {
            "checking": "checking",
            "savings": "savings",
            "credit": "credit",
            "investment": "investment",
            "mortgage": "loan",
        }
        
        for row in cursor.fetchall():
            actual_id = row["id"]
            
            # Check if already exists
            existing = await db.execute(
                select(BudgetAccount).where(
                    and_(
                        BudgetAccount.family_id == self.family_id,
                        BudgetAccount.name == row["name"]
                    )
                )
            )
            existing_account = existing.scalar_one_or_none()
            
            if existing_account:
                self.log(f"  Account '{row['name']}' already exists, skipping")
                self.account_map[actual_id] = existing_account.id
                continue
            
            # Guess account type based on name
            account_name_lower = row["name"].lower()
            account_type = "other"
            for key, value in type_map.items():
                if key in account_name_lower:
                    account_type = value
                    break
            
            if not self.dry_run:
                account = BudgetAccount(
                    id=uuid4(),
                    family_id=self.family_id,
                    name=row["name"] or "Unnamed Account",
                    type=account_type,
                    offbudget=bool(row["offbudget"]) if row["offbudget"] is not None else False,
                    closed=bool(row["closed"]) if row["closed"] is not None else False,
                    sort_order=row["sort_order"] or 0,
                )
                db.add(account)
                await db.flush()
                self.account_map[actual_id] = account.id
                self.log(f"  ✓ Created account: {account.name} ({account.type})")
            else:
                mock_id = uuid4()
                self.account_map[actual_id] = mock_id
                self.log(f"  [DRY RUN] Would create account: {row['name']} ({account_type})")
            
            self.stats["accounts"] += 1
        
        cursor.close()
        self.log(f"Migrated {self.stats['accounts']} accounts")
    
    async def migrate_payees(self, db: AsyncSession, actual_conn: sqlite3.Connection):
        """Migrate payees from Actual Budget"""
        self.log("Migrating payees...")
        
        cursor = actual_conn.cursor()
        cursor.execute("""
            SELECT id, name
            FROM payees
            WHERE tombstone = 0
        """)
        
        for row in cursor.fetchall():
            actual_id = row["id"]
            
            # Check if already exists
            existing = await db.execute(
                select(BudgetPayee).where(
                    and_(
                        BudgetPayee.family_id == self.family_id,
                        BudgetPayee.name == row["name"]
                    )
                )
            )
            existing_payee = existing.scalar_one_or_none()
            
            if existing_payee:
                self.log(f"  Payee '{row['name']}' already exists, skipping")
                self.payee_map[actual_id] = existing_payee.id
                continue
            
            if not self.dry_run:
                payee = BudgetPayee(
                    id=uuid4(),
                    family_id=self.family_id,
                    name=row["name"] or "Unknown",
                )
                db.add(payee)
                await db.flush()
                self.payee_map[actual_id] = payee.id
                self.log(f"  ✓ Created payee: {payee.name}")
            else:
                mock_id = uuid4()
                self.payee_map[actual_id] = mock_id
                self.log(f"  [DRY RUN] Would create payee: {row['name']}")
            
            self.stats["payees"] += 1
        
        cursor.close()
        self.log(f"Migrated {self.stats['payees']} payees")
    
    def parse_actual_date(self, date_int: Optional[int]) -> Optional[date]:
        """Convert Actual Budget date integer (YYYYMMDD) to Python date"""
        if not date_int:
            return None
        
        try:
            date_str = str(date_int)
            year = int(date_str[:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            return date(year, month, day)
        except (ValueError, IndexError):
            return None
    
    async def migrate_transactions(self, db: AsyncSession, actual_conn: sqlite3.Connection):
        """Migrate transactions from Actual Budget"""
        self.log("Migrating transactions...")
        
        cursor = actual_conn.cursor()
        cursor.execute("""
            SELECT id, acct as account_id, date, amount, payee as payee_id,
                   category as category_id, notes, cleared, is_parent, is_child,
                   parent_id, transfer_id
            FROM transactions
            WHERE tombstone = 0
            ORDER BY date
        """)
        
        for row in cursor.fetchall():
            actual_id = row["id"]
            actual_account_id = row["account_id"]
            
            # Map to PostgreSQL account
            if actual_account_id not in self.account_map:
                self.log(f"  ⚠️ Transaction references unknown account, skipping", "WARN")
                continue
            
            postgres_account_id = self.account_map[actual_account_id]
            
            # Parse date
            transaction_date = self.parse_actual_date(row["date"])
            if not transaction_date:
                self.log(f"  ⚠️ Transaction has invalid date, skipping", "WARN")
                continue
            
            # Map payee
            postgres_payee_id = None
            if row["payee_id"] and row["payee_id"] in self.payee_map:
                postgres_payee_id = self.payee_map[row["payee_id"]]
            
            # Map category
            postgres_category_id = None
            if row["category_id"] and row["category_id"] in self.category_map:
                postgres_category_id = self.category_map[row["category_id"]]
            
            # Check if already exists (by imported_id)
            imported_id = f"actual_{actual_id}"
            existing = await db.execute(
                select(BudgetTransaction).where(
                    and_(
                        BudgetTransaction.family_id == self.family_id,
                        BudgetTransaction.imported_id == imported_id
                    )
                )
            )
            existing_transaction = existing.scalar_one_or_none()
            
            if existing_transaction:
                continue  # Skip silently
            
            # Convert amount (Actual uses cents)
            amount = row["amount"] or 0
            
            if not self.dry_run:
                transaction = BudgetTransaction(
                    id=uuid4(),
                    family_id=self.family_id,
                    account_id=postgres_account_id,
                    date=transaction_date,
                    amount=amount,
                    payee_id=postgres_payee_id,
                    category_id=postgres_category_id,
                    notes=row["notes"],
                    cleared=bool(row["cleared"]) if row["cleared"] is not None else False,
                    reconciled=False,  # Don't preserve reconciled status
                    imported_id=imported_id,
                    is_parent=bool(row["is_parent"]) if row["is_parent"] is not None else False,
                )
                db.add(transaction)
                
                if self.stats["transactions"] % 100 == 0:
                    await db.flush()  # Flush periodically
                    self.log(f"  Processed {self.stats['transactions']} transactions...")
            else:
                if self.stats["transactions"] < 5:  # Only show first few in dry run
                    self.log(f"  [DRY RUN] Would create transaction: {transaction_date} - ${amount/100:.2f}")
            
            self.stats["transactions"] += 1
        
        cursor.close()
        self.log(f"Migrated {self.stats['transactions']} transactions")
    
    async def infer_budget_allocations(self, db: AsyncSession, actual_conn: sqlite3.Connection):
        """
        Infer budget allocations from Actual Budget's budget data
        
        Actual Budget stores monthly budgets differently. We'll try to extract them.
        """
        self.log("Inferring budget allocations...")
        
        cursor = actual_conn.cursor()
        
        # Actual Budget stores budgets in the `reflect_budgets` table
        # This is a simplified approach - may need adjustment based on actual schema
        try:
            cursor.execute("""
                SELECT category as category_id, month, amount
                FROM reflect_budgets
            """)
            
            for row in cursor.fetchall():
                actual_category_id = row["category_id"]
                
                if actual_category_id not in self.category_map:
                    continue
                
                postgres_category_id = self.category_map[actual_category_id]
                
                # Parse month (format: YYYY-MM)
                month_str = row["month"]
                try:
                    year, month_num = month_str.split("-")
                    month_date = date(int(year), int(month_num), 1)
                except:
                    continue
                
                # Check if already exists
                existing = await db.execute(
                    select(BudgetAllocation).where(
                        and_(
                            BudgetAllocation.category_id == postgres_category_id,
                            BudgetAllocation.month == month_date
                        )
                    )
                )
                existing_allocation = existing.scalar_one_or_none()
                
                if existing_allocation:
                    continue
                
                amount = row["amount"] or 0
                
                if not self.dry_run:
                    allocation = BudgetAllocation(
                        id=uuid4(),
                        family_id=self.family_id,
                        category_id=postgres_category_id,
                        month=month_date,
                        budgeted_amount=amount,
                    )
                    db.add(allocation)
                
                self.stats["allocations"] += 1
        
        except sqlite3.OperationalError as e:
            self.log(f"  ⚠️ Could not read budget allocations: {e}", "WARN")
            self.log("  Allocations will need to be set manually", "WARN")
        
        cursor.close()
        self.log(f"Inferred {self.stats['allocations']} budget allocations")
    
    async def run(self):
        """Run the full migration"""
        self.log("=" * 60)
        self.log(f"Starting Actual Budget → PostgreSQL Migration")
        self.log(f"Family ID: {self.family_id}")
        self.log(f"Actual Budget File: {self.actual_file_path}")
        self.log(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.log("=" * 60)
        
        # Connect to databases
        actual_conn = self.connect_actual_db()
        
        # Create async engine for PostgreSQL
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        async_session = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        async with async_session() as db:
            try:
                # Run migrations in order
                await self.migrate_category_groups(db, actual_conn)
                await self.migrate_categories(db, actual_conn)
                await self.migrate_accounts(db, actual_conn)
                await self.migrate_payees(db, actual_conn)
                await self.migrate_transactions(db, actual_conn)
                await self.infer_budget_allocations(db, actual_conn)
                
                if not self.dry_run:
                    await db.commit()
                    self.log("✅ Migration committed to database")
                else:
                    self.log("🔍 DRY RUN - No changes made to database")
                
            except Exception as e:
                await db.rollback()
                self.log(f"❌ Migration failed: {e}", "ERROR")
                raise
            finally:
                actual_conn.close()
        
        await engine.dispose()
        
        # Print summary
        self.log("=" * 60)
        self.log("Migration Summary:")
        self.log(f"  Category Groups: {self.stats['category_groups']}")
        self.log(f"  Categories: {self.stats['categories']}")
        self.log(f"  Accounts: {self.stats['accounts']}")
        self.log(f"  Payees: {self.stats['payees']}")
        self.log(f"  Transactions: {self.stats['transactions']}")
        self.log(f"  Allocations: {self.stats['allocations']}")
        self.log("=" * 60)
        
        return self.stats


async def main():
    parser = argparse.ArgumentParser(
        description="Migrate Actual Budget data to PostgreSQL"
    )
    parser.add_argument(
        "--family-id",
        required=True,
        help="UUID of the family to migrate data for"
    )
    parser.add_argument(
        "--actual-file",
        required=True,
        help="Path to Actual Budget SQLite file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (no database changes)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output"
    )
    
    args = parser.parse_args()
    
    try:
        family_id = UUID(args.family_id)
    except ValueError:
        print(f"Error: Invalid UUID format for family-id: {args.family_id}")
        sys.exit(1)
    
    migration = ActualBudgetMigration(
        actual_file_path=args.actual_file,
        family_id=family_id,
        dry_run=args.dry_run,
        verbose=not args.quiet
    )
    
    try:
        stats = await migration.run()
        
        if args.dry_run:
            print("\n✅ Dry run completed successfully!")
            print("Run without --dry-run to perform actual migration")
        else:
            print("\n✅ Migration completed successfully!")
        
        sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
