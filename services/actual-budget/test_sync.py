#!/usr/bin/env python3
"""
Test script for PostgreSQL sync service.

This script tests the sync functionality by:
1. Creating a test budget transaction
2. Running the sync
3. Verifying sync state
"""
import os
import sys
from datetime import date
from uuid import UUID

# Add parent directory to path
sys.path.insert(0, '/app')

from sync_postgres import (
    get_db_connection,
    get_or_create_sync_state,
    get_or_create_child_account,
    run_sync,
    get_sync_status
)

# Test family ID (replace with actual family ID from your database)
TEST_FAMILY_ID = os.getenv("TEST_FAMILY_ID", "ce875133-1b85-4bfc-8e61-b52309381f0b")


def test_sync_state():
    """Test sync state creation and retrieval."""
    print("=" * 60)
    print("TEST 1: Sync State")
    print("=" * 60)
    
    conn = get_db_connection()
    try:
        state = get_or_create_sync_state(conn, TEST_FAMILY_ID)
        print(f"✅ Sync state created/retrieved")
        print(f"   Family ID: {state['family_id']}")
        print(f"   Last sync to budget: {state.get('last_sync_to_budget')}")
        print(f"   Last sync from budget: {state.get('last_sync_from_budget')}")
    finally:
        conn.close()


def test_get_status():
    """Test getting sync status."""
    print("\n" + "=" * 60)
    print("TEST 2: Get Sync Status")
    print("=" * 60)
    
    try:
        status = get_sync_status(TEST_FAMILY_ID)
        print(f"✅ Status retrieved:")
        print(f"   Family ID: {status['family_id']}")
        print(f"   Point tx count: {status['synced_point_tx_count']}")
        print(f"   Budget tx count: {status['synced_budget_tx_count']}")
        print(f"   Recent errors: {len(status.get('recent_errors', []))}")
    except Exception as e:
        print(f"❌ Failed to get status: {e}")
        import traceback
        traceback.print_exc()


def test_dry_run_sync():
    """Test running a dry-run sync."""
    print("\n" + "=" * 60)
    print("TEST 3: Dry Run Sync")
    print("=" * 60)
    
    try:
        results = run_sync(
            family_id=TEST_FAMILY_ID,
            direction="both",
            dry_run=True
        )
        
        print(f"✅ Dry run completed:")
        for direction, stats in results.items():
            print(f"\n   {direction}:")
            print(f"      Synced: {stats.get('synced', 0)}")
            print(f"      Skipped: {stats.get('skipped', 0)}")
            print(f"      Errors: {stats.get('errors', 0)}")
    
    except Exception as e:
        print(f"❌ Dry run failed: {e}")
        import traceback
        traceback.print_exc()


def test_child_account_creation():
    """Test child account creation."""
    print("\n" + "=" * 60)
    print("TEST 4: Child Account Creation")
    print("=" * 60)
    
    conn = get_db_connection()
    try:
        # Test with a dummy child
        test_child_id = "00000000-0000-0000-0000-000000000001"
        test_child_name = "Test Child"
        
        account_id = get_or_create_child_account(
            conn,
            TEST_FAMILY_ID,
            test_child_name,
            test_child_id
        )
        
        print(f"✅ Account created/retrieved:")
        print(f"   Account ID: {account_id}")
        print(f"   Account name: Domingo {test_child_name}")
    
    except Exception as e:
        print(f"❌ Account creation failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


def main():
    """Run all tests."""
    print("\n🧪 PostgreSQL Sync Service Tests")
    print("=" * 60)
    print(f"Family ID: {TEST_FAMILY_ID}\n")
    
    test_sync_state()
    test_get_status()
    test_child_account_creation()
    test_dry_run_sync()
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
