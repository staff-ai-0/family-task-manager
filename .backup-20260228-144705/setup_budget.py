#!/usr/bin/env python3
"""
Setup Actual Budget for Family Task Manager Sync

Creates the budget file and child accounts needed for synchronization.
"""
import os
import sys
from actual import Actual
from dotenv import load_dotenv

load_dotenv()

ACTUAL_SERVER_URL = os.getenv("ACTUAL_SERVER_URL", "http://actual-server:5006")
ACTUAL_PASSWORD = os.getenv("ACTUAL_PASSWORD", "changeme")
ACTUAL_BUDGET_NAME = os.getenv("ACTUAL_BUDGET_NAME", "My Finances")


def setup_budget():
    """Create budget file and accounts."""
    print(f"🏦 Setting up Actual Budget")
    print(f"   Server: {ACTUAL_SERVER_URL}")
    print(f"   Budget name: {ACTUAL_BUDGET_NAME}")
    print()
    
    try:
        # Connect and create/open budget
        with Actual(base_url=ACTUAL_SERVER_URL, password=ACTUAL_PASSWORD) as actual:
            print("✅ Connected to Actual Budget")
            
            # List existing files
            files = actual.list_user_files()
            print(f"📁 Existing budget files: {len(files.data)}")
            
            # Check if our budget exists
            budget_exists = any(f.name == ACTUAL_BUDGET_NAME for f in files.data)
            
            if budget_exists:
                print(f"ℹ️  Budget '{ACTUAL_BUDGET_NAME}' already exists")
                actual.download_budget(ACTUAL_BUDGET_NAME)
            else:
                print(f"📝 Creating new budget: {ACTUAL_BUDGET_NAME}")
                actual.create_budget(ACTUAL_BUDGET_NAME)
                print(f"✅ Budget created successfully")
                
                # Upload the budget to the server
                print(f"📤 Uploading budget to server...")
                actual.upload_budget()
                print(f"✅ Budget uploaded successfully")
            
            print()
            
            # Get or create accounts for children
            # We'll create accounts as needed during sync
            # For now, just verify the budget is accessible
            
            try:
                with actual.session() as session:
                    accounts = session.query(actual.Accounts).all()
                    print(f"💳 Existing accounts: {len(accounts)}")
                    for account in accounts:
                        print(f"   - {account.name}")
            except Exception as e:
                print(f"💳 Could not list accounts (this is normal for new budgets): {e}")
            
            # Commit changes
            actual.commit()
            
            print()
            print("✅ Budget setup complete!")
            print(f"   You can now access it at: {ACTUAL_SERVER_URL}")
            
            return True
            
    except Exception as e:
        print(f"❌ Error setting up budget: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = setup_budget()
    sys.exit(0 if success else 1)
