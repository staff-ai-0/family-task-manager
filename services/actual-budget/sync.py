#!/usr/bin/env python3
"""
Family Finance Sync Service - BIDIRECTIONAL (Money Transactions Only)

Bridges the Family Task Manager with Actual Budget.
Supports bidirectional synchronization of MONEY transactions only:
- Family → Actual: Manual money transactions (DISABLED - points stay as points)
- Actual → Family: Manual money transactions → Money adjustments

NOTE: Automatic point-to-money conversion has been REMOVED.
Children now manually convert points to money via the dashboard conversion feature.

Usage:
    python sync.py                          # Run full bidirectional sync
    python sync.py --status                 # Show current sync status
    python sync.py --dry-run                # Preview what would be synced
    python sync.py --direction=to_actual    # Only sync Family → Actual
    python sync.py --direction=from_actual  # Only sync Actual → Family
"""

import os
import sys
import json
import decimal
import datetime
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID

import httpx
from dotenv import load_dotenv

load_dotenv()

# Configuration
ACTUAL_SERVER_URL = os.getenv("ACTUAL_SERVER_URL", "http://localhost:5006")
ACTUAL_PASSWORD = os.getenv("ACTUAL_PASSWORD", "password")
ACTUAL_BUDGET_NAME = os.getenv("ACTUAL_BUDGET_NAME", "My Finances")
ACTUAL_FILE_ID = os.getenv("ACTUAL_FILE_ID")  # Use file ID instead of name if provided

FAMILY_API_URL = os.getenv("FAMILY_API_URL", "http://localhost:8000")
FAMILY_API_EMAIL = os.getenv("FAMILY_API_EMAIL", "mom@demo.com")
FAMILY_API_PASSWORD = os.getenv("FAMILY_API_PASSWORD", "password123")

POINTS_TO_MONEY_RATE = float(os.getenv("POINTS_TO_MONEY_RATE", "0.10"))
CURRENCY = os.getenv("POINTS_TO_MONEY_CURRENCY", "MXN")

# Sync state file (tracks synced transactions to avoid duplicates)
SYNC_STATE_FILE = Path(__file__).parent / "sync_state.json"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_actual_date(date_int: int) -> str:
    """
    Convert Actual Budget date integer (YYYYMMDD) to ISO format string.
    
    Args:
        date_int: Date as integer (e.g., 20260226)
    
    Returns:
        ISO format date string (e.g., "2026-02-26")
    """
    if not date_int:
        return "Unknown"
    
    try:
        date_str = str(date_int)
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        return datetime.date(year, month, day).isoformat()
    except (ValueError, IndexError):
        return str(date_int)


# ============================================================================
# STATE MANAGEMENT
# ============================================================================

def load_sync_state() -> dict:
    """Load the persistent sync state from disk."""
    if SYNC_STATE_FILE.exists():
        return json.loads(SYNC_STATE_FILE.read_text())
    return {
        "last_sync": None,
        "synced_members": {},
        "synced_to_actual": {},      # {ftm_tx_id: actual_tx_id}
        "synced_from_actual": {},    # {actual_tx_id: ftm_tx_id}
    }


def save_sync_state(state: dict):
    """Persist sync state to disk."""
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ============================================================================
# FAMILY TASK MANAGER API
# ============================================================================

def get_family_api_token() -> str:
    """Login to Family Task Manager API and return access token."""
    login_resp = httpx.post(
        f"{FAMILY_API_URL}/api/auth/login",
        json={"email": FAMILY_API_EMAIL, "password": FAMILY_API_PASSWORD},
        timeout=10,
    )
    if login_resp.status_code != 200:
        print(f"   ❌ Login failed: {login_resp.text}")
        sys.exit(1)
    
    return login_resp.json()["access_token"]


def get_family_data(token: str) -> dict:
    """Fetch family members and their points from the Family Task Manager API."""
    print("📡 Connecting to Family Task Manager API...")
    
    headers = {"Authorization": f"Bearer {token}"}
    print("   ✅ Authenticated")

    # Get family
    family_resp = httpx.get(f"{FAMILY_API_URL}/api/families/me", headers=headers, timeout=10)
    if family_resp.status_code != 200:
        print(f"   ❌ Failed to fetch family: {family_resp.text}")
        sys.exit(1)

    family = family_resp.json()
    print(f"   👨‍👩‍👧‍👦 Family: {family.get('name', 'Unknown')} ({len(family.get('members', []))} members)")
    return family


def get_point_transactions(token: str, user_id: str, since: Optional[str] = None) -> List[dict]:
    """Fetch point transactions for a specific user."""
    headers = {"Authorization": f"Bearer {token}"}
    
    # Note: This endpoint doesn't exist yet, we'll create it in Phase 4
    # For now, we'll work with the points delta approach
    # TODO: Create /api/users/{user_id}/transactions endpoint
    
    return []


def create_point_adjustment(
    token: str,
    user_id: str,
    points: int,
    reason: str,
    created_by: Optional[str] = None
) -> dict:
    """Create a manual point adjustment in Family Task Manager."""
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "user_id": user_id,
        "points": points,
        "reason": reason,
    }
    
    resp = httpx.post(
        f"{FAMILY_API_URL}/api/users/points/adjust",
        headers=headers,
        json=payload,
        timeout=10,
    )
    
    if resp.status_code != 200:
        raise Exception(f"Failed to create point adjustment: {resp.text}")
    
    return resp.json()


# ============================================================================
# SYNC: FAMILY → ACTUAL BUDGET
# ============================================================================

def sync_to_actual(family: dict, token: str, dry_run: bool = False):
    """
    DISABLED: Automatic point-to-money conversion removed.
    
    Children now manually convert points to money via the dashboard.
    This function is preserved for future manual money transaction syncing.
    """
    print("\n⚠️  Automatic point-to-money sync is DISABLED")
    print("   Children convert points manually via the dashboard")
    print("   Only manual money transactions are synced")
    print("   ✅ Skipping Family → Actual sync")
    return


# ============================================================================
# SYNC: ACTUAL BUDGET → FAMILY
# ============================================================================

def sync_from_actual(family: dict, token: str, dry_run: bool = False):
    """
    Sync manual money transactions from Actual Budget to Family Task Manager.
    
    Converts manual money transactions (parent adjustments) to point adjustments.
    Skips transactions created by the conversion system (imported_id starts with 'ftm-conversion-').
    """
    try:
        from actual import Actual
        from actual.queries import (
            get_accounts,
            get_transactions,
        )
    except ImportError:
        print("❌ actualpy not installed. Run: pip install actualpy")
        sys.exit(1)

    members = family.get("members", [])
    children = [m for m in members if m.get("role") in ("child", "teen")]
    
    # Find a parent user to attribute adjustments to
    parents = [m for m in members if m.get("role") == "parent"]
    parent_id = parents[0]["id"] if parents else None

    if not children:
        print("ℹ️  No children found in family. Nothing to sync.")
        return

    state = load_sync_state()
    today = datetime.date.today().isoformat()

    print(f"\n💰 Reverse Sync: Actual Budget → Family Task Manager")
    print(f"📅 Sync date: {today}")
    print(f"👧 Children to check: {len(children)}\n")

    if "synced_from_actual" not in state:
        state["synced_from_actual"] = {}

    # Connect to Actual Budget
    print(f"🏦 Connecting to Actual Budget at {ACTUAL_SERVER_URL}...")
    try:
        # Use file ID if provided, otherwise fall back to name
        budget_identifier = ACTUAL_FILE_ID if ACTUAL_FILE_ID else ACTUAL_BUDGET_NAME
        with Actual(
            base_url=ACTUAL_SERVER_URL,
            password=ACTUAL_PASSWORD,
            file=budget_identifier,
        ) as actual:
            print("   ✅ Connected to budget")

            # Get existing accounts
            accounts = get_accounts(actual.session)
            account_map = {a.name: a for a in accounts}

            synced_count = 0

            for child in children:
                child_name = child["name"]
                child_id = str(child["id"])
                account_name = f"Domingo {child_name}"

                # Skip if account doesn't exist
                if account_name not in account_map:
                    print(f"\n  👤 {child_name}: No account in Actual Budget (skipping)")
                    continue

                account = account_map[account_name]
                print(f"\n  👤 {child_name}: Checking transactions...")

                # Get all transactions for this account
                transactions = get_transactions(actual.session, account=account)
                
                new_transactions = []
                
                for tx in transactions:
                    tx_id = str(tx.id)
                    
                    # Skip if already synced from Actual
                    if tx_id in state["synced_from_actual"]:
                        continue
                    
                    # Skip if this was originally synced FROM Family (check imported_id)
                    if hasattr(tx, 'imported_id') and tx.imported_id and tx.imported_id.startswith("ftm-"):
                        # Mark as synced but don't create adjustment (avoid loop)
                        state["synced_from_actual"][tx_id] = {
                            "source": "ftm_original",
                            "skipped": True,
                            "synced_at": today,
                        }
                        continue
                    
                    # This is a manual transaction in Actual Budget
                    new_transactions.append(tx)

                if not new_transactions:
                    print(f"     ✅ No new manual transactions")
                    continue

                print(f"     📝 Found {len(new_transactions)} new manual transaction(s)")

                for tx in new_transactions:
                    tx_id = str(tx.id)
                    amount_cents = int(tx.amount) if tx.amount else 0
                    amount_money = amount_cents / 100.0
                    
                    # Convert money to points
                    points = round(amount_money / POINTS_TO_MONEY_RATE)
                    
                    if points == 0:
                        print(f"     ⏭️  Skipping tx {tx_id[:8]}... (0 points)")
                        continue
                    
                    payee_name = tx.payee.name if tx.payee else "Unknown"
                    tx_date = parse_actual_date(tx.date) if tx.date else "Unknown"
                    notes = tx.notes or ""
                    
                    reason = f"Actual Budget: {payee_name} | {notes} | {tx_date}"
                    
                    print(f"     💸 Transaction: ${amount_money:+.2f} {CURRENCY} → {points:+d} pts")
                    print(f"        Date: {tx_date}, Payee: {payee_name}")
                    
                    if not dry_run:
                        try:
                            # Create point adjustment in Family Task Manager
                            create_point_adjustment(
                                token=token,
                                user_id=child_id,
                                points=points,
                                reason=reason,
                            )
                            
                            # Track in state
                            state["synced_from_actual"][tx_id] = {
                                "child_id": child_id,
                                "points": points,
                                "amount": amount_money,
                                "synced_at": today,
                                "actual_date": tx_date,
                                "payee": payee_name,
                            }
                            
                            print(f"        ✅ Point adjustment created in Family Task Manager")
                            synced_count += 1
                            
                        except Exception as e:
                            print(f"        ❌ Failed to create adjustment: {e}")
                    else:
                        print(f"        🔍 Would create point adjustment: {points:+d} pts")
                        synced_count += 1

            if dry_run:
                print(f"\n🔍 DRY RUN: Would sync {synced_count} transaction(s)")
            else:
                if synced_count > 0:
                    print(f"\n🔄 Synced {synced_count} transaction(s) from Actual Budget!")
                    state["last_sync"] = today
                    save_sync_state(state)
                    print(f"💾 Sync state saved")
                else:
                    print(f"\n✅ No new manual transactions to sync")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ============================================================================
# STATUS & MAIN
# ============================================================================

def show_status():
    """Display the current sync status."""
    state = load_sync_state()
    print("📊 Family Finance Sync Status")
    print("=" * 60)
    print(f"Last sync: {state.get('last_sync', 'Never')}")
    print(f"Rate: {POINTS_TO_MONEY_RATE} {CURRENCY}/pt")
    print(f"Actual Budget: {ACTUAL_SERVER_URL}")
    print(f"Family API: {FAMILY_API_URL}")

    members = state.get("synced_members", {})
    if members:
        print(f"\n👧 Synced Members ({len(members)}):")
        for mid, info in members.items():
            print(f"   {info['name']}: {info['last_points']} pts → ${info['last_amount']} {CURRENCY}")
            print(f"      Last sync: {info['last_sync']}")
    else:
        print("\nNo members synced yet.")
    
    # Show transaction counts
    to_actual = len(state.get("synced_to_actual", {}))
    from_actual = len(state.get("synced_from_actual", {}))
    
    print(f"\n📊 Transaction Stats:")
    print(f"   Family → Actual: {to_actual} transactions")
    print(f"   Actual → Family: {from_actual} transactions")


def main():
    parser = argparse.ArgumentParser(
        description="Family Finance Sync — Bidirectional sync between Family Task Manager and Actual Budget"
    )
    parser.add_argument("--status", action="store_true", help="Show current sync status")
    parser.add_argument("--dry-run", action="store_true", help="Preview sync without making changes")
    parser.add_argument(
        "--direction",
        choices=["both", "to_actual", "from_actual"],
        default="both",
        help="Sync direction (default: both)"
    )
    parser.add_argument("--family-id", type=str, help="Family UUID to sync")
    parser.add_argument("--budget-file-id", type=str, help="Actual Budget file ID for this family")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # Override ACTUAL_FILE_ID if provided via command line
    if args.budget_file_id:
        global ACTUAL_FILE_ID
        ACTUAL_FILE_ID = args.budget_file_id
    
    # Override SYNC_STATE_FILE to use family-specific state file
    if args.family_id:
        global SYNC_STATE_FILE
        SYNC_STATE_FILE = Path(__file__).parent / f"sync_state_{args.family_id}.json"

    # Get API token first
    token = get_family_api_token()
    family = get_family_data(token)

    # Run sync based on direction
    if args.direction in ("both", "to_actual"):
        print("\n" + "=" * 60)
        print("STEP 1: Family Task Manager → Actual Budget")
        print("=" * 60)
        sync_to_actual(family, token, dry_run=args.dry_run)

    if args.direction in ("both", "from_actual"):
        print("\n" + "=" * 60)
        print("STEP 2: Actual Budget → Family Task Manager")
        print("=" * 60)
        sync_from_actual(family, token, dry_run=args.dry_run)
    
    print("\n" + "=" * 60)
    print("✅ Sync complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
