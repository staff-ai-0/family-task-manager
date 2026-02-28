#!/usr/bin/env python3
"""
Setup Family Budget Accounts and Categories

Creates the default category structure and individual child accounts when
a family first enables Actual Budget sync.

This script is called:
- Manually via CLI: python setup_family_budget.py --family-id=<uuid> --budget-file-id=<uuid>
- Automatically when parents enable sync in the UI (future integration)

Account Structure per Child (TEEN role only):
- {Child Name} - Cuenta de Ahorros (Savings) - Receives 15% of conversions
- {Child Name} - Cuenta de Cheques/Cash (Checking) - Receives 85% of conversions

Default Categories:
- Group: "Gastos Familiares" (Family Expenses)
  - Entretenimiento (Entertainment)
  - Restaurantes (Restaurants)
  - Fondo de Vacaciones (Vacation Fund)
  - Domingos (Allowances/Conversions) ← Target category for point conversions
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from actual import Actual
from actual.queries import (
    get_accounts,
    create_account,
    get_category_groups,
    create_category_group,
    get_categories,
    create_category,
    get_or_create_category_group,
)

load_dotenv()

# Configuration
ACTUAL_SERVER_URL = os.getenv("ACTUAL_SERVER_URL", "http://localhost:5006")
ACTUAL_PASSWORD = os.getenv("ACTUAL_PASSWORD", "password")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://familyapp:familyapp_prod_2026@db:5432/familyapp")

# Default category structure
DEFAULT_CATEGORY_GROUP = "Gastos Familiares"
DEFAULT_CATEGORIES = [
    {"name": "Entretenimiento", "name_en": "Entertainment"},
    {"name": "Restaurantes", "name_en": "Restaurants"},
    {"name": "Fondo de Vacaciones", "name_en": "Vacation Fund"},
    {"name": "Domingos", "name_en": "Allowances"},  # Used for point conversions
]


def get_family_teens(family_id: str) -> List[Dict]:
    """Query database for TEEN users in the family."""
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, name, email, role
                    FROM users
                    WHERE family_id = :family_id
                    AND role IN ('TEEN', 'CHILD')
                    ORDER BY name
                """),
                {"family_id": family_id}
            )
            
            teens = []
            for row in result:
                teens.append({
                    "id": str(row.id),
                    "name": row.name,
                    "email": row.email,
                    "role": row.role,
                })
            
            return teens
    finally:
        engine.dispose()


def setup_categories(actual: Actual) -> Dict[str, any]:
    """Create default category group and categories."""
    print(f"\n📂 Setting up categories...")
    
    # Get existing category groups
    groups = get_category_groups(actual.session)
    group_map = {g.name: g for g in groups}
    
    # Create or get the family expenses group
    if DEFAULT_CATEGORY_GROUP in group_map:
        group = group_map[DEFAULT_CATEGORY_GROUP]
        print(f"   ✅ Found category group: {DEFAULT_CATEGORY_GROUP}")
    else:
        group = create_category_group(actual.session, DEFAULT_CATEGORY_GROUP)
        print(f"   ✨ Created category group: {DEFAULT_CATEGORY_GROUP}")
    
    # Get existing categories
    categories = get_categories(actual.session)
    category_map = {c.name: c for c in categories}
    
    created_count = 0
    for cat_config in DEFAULT_CATEGORIES:
        cat_name = cat_config["name"]
        
        if cat_name in category_map:
            print(f"   ✅ Found category: {cat_name}")
        else:
            category = create_category(
                actual.session,
                name=cat_name,
                group_id=group.id
            )
            category_map[cat_name] = category
            print(f"   ✨ Created category: {cat_name}")
            created_count += 1
    
    print(f"   📊 Created {created_count} new categories")
    return category_map


def setup_child_accounts(actual: Actual, teens: List[Dict]) -> Dict[str, any]:
    """Create savings and checking accounts for each child."""
    print(f"\n💳 Setting up child accounts...")
    
    # Get existing accounts
    accounts = get_accounts(actual.session)
    account_map = {a.name: a for a in accounts}
    
    created_count = 0
    account_structure = {}
    
    for teen in teens:
        child_name = teen["name"]
        
        # Create Savings account (15% of conversions)
        savings_name = f"{child_name} - Cuenta de Ahorros"
        if savings_name in account_map:
            savings_account = account_map[savings_name]
            print(f"   ✅ Found: {savings_name}")
        else:
            savings_account = create_account(actual.session, savings_name, offbudget=False)
            account_map[savings_name] = savings_account
            print(f"   ✨ Created: {savings_name}")
            created_count += 1
        
        # Create Checking/Cash account (85% of conversions)
        checking_name = f"{child_name} - Cuenta de Cheques/Cash"
        if checking_name in account_map:
            checking_account = account_map[checking_name]
            print(f"   ✅ Found: {checking_name}")
        else:
            checking_account = create_account(actual.session, checking_name, offbudget=False)
            account_map[checking_name] = checking_account
            print(f"   ✨ Created: {checking_name}")
            created_count += 1
        
        account_structure[teen["id"]] = {
            "name": child_name,
            "savings": savings_account,
            "checking": checking_account,
        }
    
    print(f"   📊 Created {created_count} new accounts")
    return account_structure


def setup_family_budget(family_id: str, budget_file_id: str) -> bool:
    """
    Main setup function for a family's Actual Budget.
    
    Args:
        family_id: UUID of the family in the database
        budget_file_id: Actual Budget file ID for this family
        
    Returns:
        True if setup succeeded, False otherwise
    """
    print("=" * 70)
    print("🏦 Family Budget Setup")
    print("=" * 70)
    print(f"Family ID: {family_id}")
    print(f"Budget File ID: {budget_file_id}")
    print(f"Actual Server: {ACTUAL_SERVER_URL}")
    print()
    
    try:
        # Get family's TEEN users from database
        print("👧 Querying family members...")
        teens = get_family_teens(family_id)
        
        if not teens:
            print("⚠️  No TEEN/CHILD users found in this family")
            print("   Skipping account creation")
            teens_to_setup = []
        else:
            print(f"   Found {len(teens)} children:")
            for teen in teens:
                print(f"   - {teen['name']} ({teen['role']})")
            teens_to_setup = teens
        
        # Connect to Actual Budget
        print(f"\n🔌 Connecting to Actual Budget...")
        with Actual(
            base_url=ACTUAL_SERVER_URL,
            password=ACTUAL_PASSWORD,
            file=budget_file_id,
        ) as actual:
            print("   ✅ Connected successfully")
            
            # Setup categories
            categories = setup_categories(actual)
            
            # Setup child accounts
            if teens_to_setup:
                accounts = setup_child_accounts(actual, teens_to_setup)
                
                print(f"\n📋 Account Structure Summary:")
                for teen_id, acc_info in accounts.items():
                    print(f"   {acc_info['name']}:")
                    print(f"      💰 Savings: {acc_info['savings'].name}")
                    print(f"      💵 Checking: {acc_info['checking'].name}")
            
            # Commit all changes
            print(f"\n💾 Saving changes to Actual Budget...")
            actual.commit()
            print("   ✅ Changes committed successfully")
            
            print()
            print("=" * 70)
            print("✅ Family budget setup complete!")
            print("=" * 70)
            print()
            print("Next steps:")
            print("1. Children can now convert points to money via their dashboard")
            print("2. Conversions will deposit:")
            print("   - 85% to Checking account (spendable)")
            print("   - 15% to Savings account (locked)")
            print("3. Hourly sync will keep transactions in sync")
            print()
            
            return True
            
    except Exception as e:
        print(f"\n❌ Error during setup: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Setup Actual Budget accounts and categories for a family"
    )
    parser.add_argument(
        "--family-id",
        type=str,
        required=True,
        help="Family UUID from the database"
    )
    parser.add_argument(
        "--budget-file-id",
        type=str,
        required=True,
        help="Actual Budget file ID for this family"
    )
    args = parser.parse_args()
    
    success = setup_family_budget(args.family_id, args.budget_file_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
