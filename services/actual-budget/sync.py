#!/usr/bin/env python3
"""
Family Finance Sync Service - PostgreSQL Integration

Bridges the Family Task Manager with the internal PostgreSQL budget system.
Supports bidirectional synchronization of MONEY transactions:
- Family → Budget: Manual money transactions (DISABLED - points stay as points)
- Budget → Family: Manual budget transactions → Money adjustments

NOTE: Automatic point-to-money conversion has been REMOVED.
Children now manually convert points to money via the dashboard conversion feature.

This script now uses PostgreSQL directly instead of Actual Budget.

Usage:
    python sync.py --family-id=<uuid>                   # Run full bidirectional sync
    python sync.py --family-id=<uuid> --status          # Show current sync status
    python sync.py --family-id=<uuid> --dry-run         # Preview what would be synced
    python sync.py --family-id=<uuid> --direction=to_budget    # Only sync Family → Budget
    python sync.py --family-id=<uuid> --direction=from_budget  # Only sync Budget → Family
"""

import os
import sys
import argparse
from typing import Optional

from dotenv import load_dotenv

# Import the new PostgreSQL sync module
from sync_postgres import run_sync, get_sync_status

load_dotenv()

# Configuration
FAMILY_API_URL = os.getenv("FAMILY_API_URL", "http://backend:8002")
POINTS_TO_MONEY_RATE = float(os.getenv("POINTS_TO_MONEY_RATE", "0.10"))
CURRENCY = os.getenv("POINTS_TO_MONEY_CURRENCY", "MXN")


# ============================================================================
# STATUS & MAIN
# ============================================================================

def show_status(family_id: Optional[str] = None):
    """Display the current sync status."""
    if not family_id:
        print("❌ --family-id required for status check")
        sys.exit(1)
    
    try:
        status = get_sync_status(family_id)
        
        print("📊 Family Finance Sync Status (PostgreSQL)")
        print("=" * 60)
        print(f"Family ID: {status['family_id']}")
        print(f"Rate: {POINTS_TO_MONEY_RATE} {CURRENCY}/pt")
        print(f"Family API: {FAMILY_API_URL}")
        print(f"\nLast sync to budget: {status.get('last_sync_to_budget', 'Never')}")
        print(f"Last sync from budget: {status.get('last_sync_from_budget', 'Never')}")
        print(f"\n📊 Transaction Stats:")
        print(f"   Family → Budget: {status.get('synced_point_tx_count', 0)} transactions")
        print(f"   Budget → Family: {status.get('synced_budget_tx_count', 0)} transactions")
        
        recent_errors = status.get('recent_errors', [])
        if recent_errors:
            print(f"\n⚠️  Recent Errors ({len(recent_errors)}):")
            for err in recent_errors:
                print(f"   {err.get('timestamp')}: {err.get('error')}")
    
    except Exception as e:
        print(f"❌ Failed to get status: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Family Finance Sync — PostgreSQL-based bidirectional sync"
    )
    parser.add_argument("--status", action="store_true", help="Show current sync status")
    parser.add_argument("--dry-run", action="store_true", help="Preview sync without making changes")
    parser.add_argument(
        "--direction",
        choices=["both", "to_budget", "from_budget"],
        default="both",
        help="Sync direction (default: both)"
    )
    parser.add_argument("--family-id", type=str, required=True, help="Family UUID to sync")
    args = parser.parse_args()

    if args.status:
        show_status(args.family_id)
        return

    if not args.family_id:
        print("❌ --family-id is required")
        sys.exit(1)

    # Run sync using the PostgreSQL module
    try:
        results = run_sync(
            family_id=args.family_id,
            direction=args.direction,
            dry_run=args.dry_run
        )
        
        # Print summary
        print("\n📊 Sync Summary:")
        for direction, stats in results.items():
            print(f"\n{direction.upper()}:")
            print(f"   Synced: {stats.get('synced', 0)}")
            print(f"   Skipped: {stats.get('skipped', 0)}")
            print(f"   Errors: {stats.get('errors', 0)}")
    
    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
