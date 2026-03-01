#!/usr/bin/env python3
"""
PostgreSQL-based sync service for Family Task Manager budget system.

This module provides bidirectional synchronization between:
- Family points system → Budget transactions (points to money conversion)
- Budget transactions → Family money adjustments

Replaces the Actual Budget sync with direct PostgreSQL integration.
"""
import os
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from uuid import UUID
import decimal

import psycopg2
from psycopg2.extras import RealDictCursor, Json
import httpx

# Database configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_NAME = os.getenv("DB_NAME", "familyapp")
DB_USER = os.getenv("DB_USER", "familyapp")
DB_PASSWORD = os.getenv("DB_PASSWORD", "familyapp_prod_2026")

# Family API configuration
FAMILY_API_URL = os.getenv("FAMILY_API_URL", "http://backend:8002")
FAMILY_API_EMAIL = os.getenv("FAMILY_API_EMAIL", "mom@demo.com")
FAMILY_API_PASSWORD = os.getenv("FAMILY_API_PASSWORD", "password123")

# Conversion rate
POINTS_TO_MONEY_RATE = float(os.getenv("POINTS_TO_MONEY_RATE", "0.10"))
CURRENCY = os.getenv("POINTS_TO_MONEY_CURRENCY", "MXN")


# ============================================================================
# DATABASE HELPERS
# ============================================================================

def get_db_connection():
    """Create and return a database connection."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def get_or_create_sync_state(conn, family_id: str) -> dict:
    """
    Get or create sync state for a family.
    
    Returns:
        dict with sync state fields
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Try to get existing state
        cur.execute(
            """
            SELECT 
                id, family_id, last_sync_to_budget, last_sync_from_budget,
                synced_point_transactions, synced_budget_transactions, sync_errors
            FROM budget_sync_state
            WHERE family_id = %s
            """,
            (family_id,)
        )
        
        state = cur.fetchone()
        
        if state:
            return dict(state)
        
        # Create new state
        cur.execute(
            """
            INSERT INTO budget_sync_state 
                (family_id, synced_point_transactions, synced_budget_transactions, sync_errors)
            VALUES 
                (%s, %s, %s, %s)
            RETURNING 
                id, family_id, last_sync_to_budget, last_sync_from_budget,
                synced_point_transactions, synced_budget_transactions, sync_errors
            """,
            (family_id, Json({}), Json({}), Json([]))
        )
        
        new_state = cur.fetchone()
        conn.commit()
        
        return dict(new_state)


def update_sync_state(
    conn,
    family_id: str,
    direction: str,
    synced_point_txs: Optional[dict] = None,
    synced_budget_txs: Optional[dict] = None,
    error: Optional[str] = None
):
    """
    Update sync state after a sync operation.
    
    Args:
        conn: Database connection
        family_id: Family UUID
        direction: 'to_budget' or 'from_budget'
        synced_point_txs: Updated point transaction mapping
        synced_budget_txs: Updated budget transaction mapping
        error: Error message if sync failed
    """
    with conn.cursor() as cur:
        now = datetime.utcnow()
        
        if direction == "to_budget":
            timestamp_field = "last_sync_to_budget"
        elif direction == "from_budget":
            timestamp_field = "last_sync_from_budget"
        else:
            raise ValueError(f"Invalid direction: {direction}")
        
        # Build update query
        updates = [f"{timestamp_field} = %s"]
        params = [now]
        
        if synced_point_txs is not None:
            updates.append("synced_point_transactions = synced_point_transactions || %s::jsonb")
            params.append(Json(synced_point_txs))
        
        if synced_budget_txs is not None:
            updates.append("synced_budget_transactions = synced_budget_transactions || %s::jsonb")
            params.append(Json(synced_budget_txs))
        
        if error:
            updates.append("sync_errors = sync_errors || %s::jsonb")
            params.append(Json([{"timestamp": now.isoformat(), "error": error}]))
        
        params.append(family_id)
        
        query = f"""
            UPDATE budget_sync_state
            SET {', '.join(updates)}, updated_at = NOW()
            WHERE family_id = %s
        """
        
        cur.execute(query, params)
        conn.commit()


# ============================================================================
# FAMILY API HELPERS
# ============================================================================

def get_family_api_token() -> str:
    """Login to Family Task Manager API and return access token."""
    login_resp = httpx.post(
        f"{FAMILY_API_URL}/api/auth/login",
        json={"email": FAMILY_API_EMAIL, "password": FAMILY_API_PASSWORD},
        timeout=10,
    )
    
    if login_resp.status_code != 200:
        raise Exception(f"Login failed: {login_resp.text}")
    
    return login_resp.json()["access_token"]


def get_family_data(token: str, family_id: Optional[str] = None) -> dict:
    """Fetch family data from the API."""
    headers = {"Authorization": f"Bearer {token}"}
    
    if family_id:
        # Get specific family
        resp = httpx.get(
            f"{FAMILY_API_URL}/api/families/{family_id}",
            headers=headers,
            timeout=10
        )
    else:
        # Get logged-in user's family
        resp = httpx.get(
            f"{FAMILY_API_URL}/api/families/me",
            headers=headers,
            timeout=10
        )
    
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch family: {resp.text}")
    
    return resp.json()


def create_money_adjustment(
    token: str,
    user_id: str,
    amount_cents: int,
    reason: str,
) -> dict:
    """
    Create a money adjustment in Family Task Manager.
    
    This updates the user's money balance directly.
    """
    headers = {"Authorization": f"Bearer {token}"}
    
    # Convert cents to decimal
    amount_money = decimal.Decimal(amount_cents) / 100
    
    payload = {
        "user_id": user_id,
        "amount": float(amount_money),
        "reason": reason,
    }
    
    resp = httpx.post(
        f"{FAMILY_API_URL}/api/users/money/adjust",
        headers=headers,
        json=payload,
        timeout=10,
    )
    
    if resp.status_code not in (200, 201):
        raise Exception(f"Failed to create money adjustment: {resp.text}")
    
    return resp.json()


# ============================================================================
# BUDGET ACCOUNT HELPERS
# ============================================================================

def get_or_create_child_account(conn, family_id: str, child_name: str, child_id: str) -> str:
    """
    Get or create a budget account for a child.
    
    Account name format: "Domingo {child_name}"
    
    Returns:
        Account UUID as string
    """
    account_name = f"Domingo {child_name}"
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Try to find existing account
        cur.execute(
            """
            SELECT id FROM budget_accounts
            WHERE family_id = %s AND name = %s
            """,
            (family_id, account_name)
        )
        
        account = cur.fetchone()
        
        if account:
            return str(account['id'])
        
        # Create new account
        cur.execute(
            """
            INSERT INTO budget_accounts
                (family_id, name, type, offbudget, closed)
            VALUES
                (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (family_id, account_name, "other", False, False)
        )
        
        new_account = cur.fetchone()
        conn.commit()
        
        return str(new_account['id'])


def get_account_balance(conn, account_id: str) -> int:
    """
    Calculate account balance (sum of all transactions).
    
    Returns:
        Balance in cents
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as balance
            FROM budget_transactions
            WHERE account_id = %s
            """,
            (account_id,)
        )
        
        result = cur.fetchone()
        return int(result[0]) if result else 0


# ============================================================================
# SYNC: FAMILY → BUDGET (Manual money conversions)
# ============================================================================

def sync_to_budget(family_id: str, dry_run: bool = False) -> dict:
    """
    Sync manual money conversions from Family to Budget.
    
    Currently DISABLED - children convert points manually via dashboard.
    This function is preserved for future enhancement.
    
    Returns:
        dict with sync statistics
    """
    print("\n⚠️  Automatic point-to-money sync is DISABLED")
    print("   Children convert points manually via the dashboard")
    print("   ✅ Skipping Family → Budget sync")
    
    return {
        "synced": 0,
        "skipped": 0,
        "errors": 0,
        "message": "Automatic sync disabled"
    }


# ============================================================================
# SYNC: BUDGET → FAMILY (Budget transactions to money adjustments)
# ============================================================================

def sync_from_budget(family_id: str, dry_run: bool = False) -> dict:
    """
    DISABLED: Budget IS the family money system now.
    
    Since we migrated to PostgreSQL, the budget_transactions table IS the 
    source of truth for family money. There's no need to sync "back" to 
    Family since they're the same system now.
    
    This function is preserved for potential future features.
    
    Returns:
        dict with sync statistics
    """
    print("\n⚠️  Budget → Family sync is DISABLED")
    print("   Budget transactions ARE the family money system")
    print("   All money is managed through /budget/* pages")
    print("   ✅ Skipping Budget → Family sync")
    
    return {
        "synced": 0,
        "skipped": 0,
        "errors": 0,
        "message": "Budget IS the family money system"
    }


# ============================================================================
# MAIN SYNC FUNCTION
# ============================================================================

def run_sync(
    family_id: str,
    direction: str = "both",
    dry_run: bool = False
) -> dict:
    """
    Run bidirectional sync between Family and Budget.
    
    Args:
        family_id: Family UUID
        direction: 'both', 'to_budget', or 'from_budget'
        dry_run: Preview changes without applying
    
    Returns:
        dict with sync results for each direction
    """
    results = {}
    
    if direction in ("both", "to_budget"):
        print("\n" + "=" * 60)
        print("STEP 1: Family Task Manager → Budget")
        print("=" * 60)
        results["to_budget"] = sync_to_budget(family_id, dry_run)
    
    if direction in ("both", "from_budget"):
        print("\n" + "=" * 60)
        print("STEP 2: Budget → Family Task Manager")
        print("=" * 60)
        results["from_budget"] = sync_from_budget(family_id, dry_run)
    
    print("\n" + "=" * 60)
    print("✅ Sync complete!")
    print("=" * 60)
    
    return results


def get_sync_status(family_id: str) -> dict:
    """
    Get current sync status for a family.
    
    Returns:
        dict with sync state information
    """
    conn = get_db_connection()
    
    try:
        state = get_or_create_sync_state(conn, family_id)
        
        return {
            "family_id": family_id,
            "last_sync_to_budget": state.get("last_sync_to_budget"),
            "last_sync_from_budget": state.get("last_sync_from_budget"),
            "synced_point_tx_count": len(state.get("synced_point_transactions", {})),
            "synced_budget_tx_count": len(state.get("synced_budget_transactions", {})),
            "recent_errors": state.get("sync_errors", [])[-5:],  # Last 5 errors
        }
    finally:
        conn.close()
