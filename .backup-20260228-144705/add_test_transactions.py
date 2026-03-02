#!/usr/bin/env python3
"""
Add test transactions to Actual Budget for testing reverse sync.

This script adds manual transactions to child accounts in Actual Budget
to demonstrate the Actual → Family sync direction.
"""
import os
import sys
from datetime import date, timedelta
from actual import Actual
from actual.queries import create_transaction, get_accounts
from dotenv import load_dotenv

load_dotenv()

ACTUAL_SERVER_URL = os.getenv("ACTUAL_SERVER_URL", "http://actual-server:5006")
ACTUAL_PASSWORD = os.getenv("ACTUAL_PASSWORD", "changeme")
ACTUAL_BUDGET_NAME = os.getenv("ACTUAL_BUDGET_NAME", "My Finances")


def add_test_transactions():
    """Add test transactions for Emma and Lucas."""
    print(f"🏦 Adding test transactions to Actual Budget")
    print(f"   Server: {ACTUAL_SERVER_URL}")
    print(f"   Budget: {ACTUAL_BUDGET_NAME}")
    print()
    
    try:
        with Actual(base_url=ACTUAL_SERVER_URL, password=ACTUAL_PASSWORD, file=ACTUAL_BUDGET_NAME) as actual:
            with actual.session as session:
                # Get accounts
                accounts = get_accounts(session)
                
                emma_account = None
                lucas_account = None
                
                for acc in accounts:
                    if "Emma" in acc.name:
                        emma_account = acc
                    elif "Lucas" in acc.name:
                        lucas_account = acc
                
                if not emma_account or not lucas_account:
                    print("❌ Could not find Emma or Lucas accounts")
                    print(f"   Found accounts: {[acc.name for acc in accounts]}")
                    return False
                
                print(f"✅ Found accounts:")
                print(f"   - {emma_account.name} (ID: {emma_account.id})")
                print(f"   - {lucas_account.name} (ID: {lucas_account.id})")
                print()
                
                # Test transactions for Emma
                print("📝 Adding transactions for Emma:")
                
                # Transaction 1: Ice cream reward (positive)
                tx1 = create_transaction(
                    session,
                    date=date.today() - timedelta(days=2),
                    account=emma_account.id,
                    payee="Ice Cream Reward",
                    notes="Good behavior this week",
                    amount=0.50,  # $0.50 = 5 points
                )
                print(f"   ✅ Ice Cream Reward: +$0.50 (5 points)")
                
                # Transaction 2: Book purchase (positive)
                tx2 = create_transaction(
                    session,
                    date=date.today() - timedelta(days=1),
                    account=emma_account.id,
                    payee="Book Store",
                    notes="Reading reward",
                    amount=1.00,  # $1.00 = 10 points
                )
                print(f"   ✅ Book Store: +$1.00 (10 points)")
                
                # Transaction 3: Toy expense (negative)
                tx3 = create_transaction(
                    session,
                    date=date.today(),
                    account=emma_account.id,
                    payee="Toy Store",
                    notes="Spent allowance on toy",
                    amount=-0.30,  # -$0.30 = -3 points
                )
                print(f"   ✅ Toy Store: -$0.30 (-3 points)")
                
                print()
                print("📝 Adding transactions for Lucas:")
                
                # Transaction 1: Movie reward (positive)
                tx4 = create_transaction(
                    session,
                    date=date.today() - timedelta(days=3),
                    account=lucas_account.id,
                    payee="Movie Theater",
                    notes="Completed all homework",
                    amount=1.50,  # $1.50 = 15 points
                )
                print(f"   ✅ Movie Theater: +$1.50 (15 points)")
                
                # Transaction 2: Video game expense (negative)
                tx5 = create_transaction(
                    session,
                    date=date.today() - timedelta(days=1),
                    account=lucas_account.id,
                    payee="Game Store",
                    notes="New video game purchase",
                    amount=-2.00,  # -$2.00 = -20 points
                )
                print(f"   ✅ Game Store: -$2.00 (-20 points)")
                
                # Transaction 3: Extra chores bonus (positive)
                tx6 = create_transaction(
                    session,
                    date=date.today(),
                    account=lucas_account.id,
                    payee="Extra Chores Bonus",
                    notes="Helped with yard work",
                    amount=0.75,  # $0.75 = 8 points (rounded)
                )
                print(f"   ✅ Extra Chores: +$0.75 (8 points)")
                
                # Commit all changes
                actual.commit()
                
                print()
                print("✅ Test transactions added successfully!")
                print()
                print("📊 Expected point changes after sync:")
                print(f"   Emma: +0.50 +1.00 -0.30 = +$1.20 = +12 points")
                print(f"   Lucas: +1.50 -2.00 +0.75 = +$0.25 = +3 points")
                print()
                print("🔄 Run sync to apply these transactions to Family Task Manager")
                
                return True
                
    except Exception as e:
        print(f"❌ Error adding transactions: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = add_test_transactions()
    sys.exit(0 if success else 1)
