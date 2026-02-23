#!/usr/bin/env python3
"""
Family Finance Sync Service

Bridges the Family Task Manager points system with Actual Budget.
- Reads family members and their points from the Family Task Manager API
- Creates/updates accounts in Actual Budget for each child
- Converts accumulated points to money transactions (domingos/allowance)

Usage:
    python sync.py                # Run a full sync
    python sync.py --status       # Show current sync status
    python sync.py --dry-run      # Preview what would be synced without making changes
"""

import os
import sys
import json
import decimal
import datetime
import argparse
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# Configuration
ACTUAL_SERVER_URL = os.getenv("ACTUAL_SERVER_URL", "http://localhost:5006")
ACTUAL_PASSWORD = os.getenv("ACTUAL_PASSWORD", "password")
ACTUAL_BUDGET_NAME = os.getenv("ACTUAL_BUDGET_NAME", "My Finances")

FAMILY_API_URL = os.getenv("FAMILY_API_URL", "http://localhost:8000")
FAMILY_API_EMAIL = os.getenv("FAMILY_API_EMAIL", "mom@demo.com")
FAMILY_API_PASSWORD = os.getenv("FAMILY_API_PASSWORD", "password123")

POINTS_TO_MONEY_RATE = float(os.getenv("POINTS_TO_MONEY_RATE", "0.10"))
CURRENCY = os.getenv("POINTS_TO_MONEY_CURRENCY", "MXN")

# Sync state file (tracks last sync to avoid duplicates)
SYNC_STATE_FILE = Path(__file__).parent / "sync_state.json"


def load_sync_state() -> dict:
    """Load the persistent sync state from disk."""
    if SYNC_STATE_FILE.exists():
        return json.loads(SYNC_STATE_FILE.read_text())
    return {"last_sync": None, "synced_members": {}}


def save_sync_state(state: dict):
    """Persist sync state to disk."""
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def get_family_data() -> dict:
    """Fetch family members and their points from the Family Task Manager API."""
    print("📡 Connecting to Family Task Manager API...")

    # Login
    login_resp = httpx.post(
        f"{FAMILY_API_URL}/api/auth/login",
        json={"email": FAMILY_API_EMAIL, "password": FAMILY_API_PASSWORD},
        timeout=10,
    )
    if login_resp.status_code != 200:
        print(f"   ❌ Login failed: {login_resp.text}")
        sys.exit(1)

    token = login_resp.json()["access_token"]
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


def sync_to_actual(family: dict, dry_run: bool = False):
    """Sync family points data to Actual Budget."""
    try:
        from actual import Actual
        from actual.queries import (
            create_transaction,
            create_account,
            get_accounts,
            get_or_create_payee,
        )
    except ImportError:
        print("❌ actualpy not installed. Run: pip install actualpy")
        sys.exit(1)

    members = family.get("members", [])
    children = [m for m in members if m.get("role") in ("child", "teen")]

    if not children:
        print("ℹ️  No children found in family. Nothing to sync.")
        return

    state = load_sync_state()
    today = datetime.date.today().isoformat()

    print(f"\n💰 Points-to-Money Rate: {POINTS_TO_MONEY_RATE} {CURRENCY} per point")
    print(f"📅 Sync date: {today}")
    print(f"👧 Children to sync: {len(children)}\n")

    if dry_run:
        print("=" * 50)
        print("🔍 DRY RUN — No changes will be made")
        print("=" * 50)
        for child in children:
            points = child.get("points", 0)
            money = round(points * POINTS_TO_MONEY_RATE, 2)
            last_synced = state.get("synced_members", {}).get(str(child["id"]), {})
            last_points = last_synced.get("last_points", 0)
            delta = points - last_points

            print(f"\n  👤 {child['name']} ({child['role']})")
            print(f"     Current points: {points}")
            print(f"     Last synced points: {last_points}")
            print(f"     Points delta: {delta:+d}")
            if delta > 0:
                delta_money = round(delta * POINTS_TO_MONEY_RATE, 2)
                print(f"     → Would create: {delta_money} {CURRENCY} transaction")
            else:
                print(f"     → No new points, skipping")
        return

    # Connect to Actual Budget
    print(f"🏦 Connecting to Actual Budget at {ACTUAL_SERVER_URL}...")
    try:
        with Actual(
            base_url=ACTUAL_SERVER_URL,
            password=ACTUAL_PASSWORD,
            file=ACTUAL_BUDGET_NAME,
        ) as actual:
            print("   ✅ Connected to budget")

            # Get existing accounts
            accounts = get_accounts(actual.session)
            account_map = {a.name: a for a in accounts}

            for child in children:
                child_name = child["name"]
                child_id = str(child["id"])
                points = child.get("points", 0)

                # Check delta since last sync
                last_synced = state.get("synced_members", {}).get(child_id, {})
                last_points = last_synced.get("last_points", 0)
                delta = points - last_points

                print(f"\n  👤 {child_name}: {points} pts (delta: {delta:+d})")

                if delta <= 0:
                    print(f"     ⏭️  No new points since last sync")
                    continue

                # Find or create the child's account
                account_name = f"Domingo {child_name}"
                if account_name in account_map:
                    account = account_map[account_name]
                    print(f"     📋 Found account: {account_name}")
                else:
                    account = create_account(actual.session, account_name)
                    print(f"     ✨ Created account: {account_name}")

                # Calculate money
                money = round(delta * POINTS_TO_MONEY_RATE, 2)

                # Create the allowance transaction
                payee = get_or_create_payee(actual.session, "Family Task Manager")
                t = create_transaction(
                    actual.session,
                    datetime.date.today(),
                    account,
                    payee,
                    notes=f"Domingo: {delta} pts × ${POINTS_TO_MONEY_RATE}/{CURRENCY} = ${money} {CURRENCY} ({today})",
                    amount=decimal.Decimal(str(money)),
                    imported_id=f"ftm-sync-{child_id}-{today}",
                )
                print(f"     ✅ Transaction: +${money} {CURRENCY} ({delta} pts converted)")

                # Update sync state for this child
                if "synced_members" not in state:
                    state["synced_members"] = {}
                state["synced_members"][child_id] = {
                    "name": child_name,
                    "last_points": points,
                    "last_sync": today,
                    "last_amount": money,
                }

            # Commit all transactions to Actual Budget
            actual.commit()
            print("\n🔄 Synced to Actual Budget server!")

            state["last_sync"] = today
            save_sync_state(state)
            print(f"💾 Sync state saved to {SYNC_STATE_FILE}")

    except Exception as e:
        print(f"\n❌ Error connecting to Actual Budget: {e}")
        print("   Make sure:")
        print(f"   - Actual server is running at {ACTUAL_SERVER_URL}")
        print(f"   - Password is correct")
        print(f"   - Budget '{ACTUAL_BUDGET_NAME}' exists")
        sys.exit(1)


def show_status():
    """Display the current sync status."""
    state = load_sync_state()
    print("📊 Family Finance Sync Status")
    print("=" * 40)
    print(f"Last sync: {state.get('last_sync', 'Never')}")
    print(f"Rate: {POINTS_TO_MONEY_RATE} {CURRENCY}/pt")
    print(f"Actual Budget: {ACTUAL_SERVER_URL}")
    print(f"Family API: {FAMILY_API_URL}")

    members = state.get("synced_members", {})
    if members:
        print(f"\n👧 Synced Members ({len(members)}):")
        for mid, info in members.items():
            print(f"   {info['name']}: {info['last_points']} pts → ${info['last_amount']} {CURRENCY} (synced {info['last_sync']})")
    else:
        print("\nNo members synced yet.")


def main():
    parser = argparse.ArgumentParser(description="Family Finance Sync — Points to Actual Budget")
    parser.add_argument("--status", action="store_true", help="Show current sync status")
    parser.add_argument("--dry-run", action="store_true", help="Preview sync without making changes")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    family = get_family_data()
    sync_to_actual(family, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
