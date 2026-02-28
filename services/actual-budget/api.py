#!/usr/bin/env python3
"""
Finance API — Micro-service that exposes Actual Budget data as JSON.
Runs on port 5007 and is consumed by the Astro frontend via SSR fetch.

Family-aware: Requires JWT token and queries family's Actual Budget file from database.

Usage:
    source .venv/bin/activate
    uvicorn api:app --port 5007 --reload
"""

import os
import datetime
import decimal
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Security, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from jose import JWTError, jwt
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from actual import Actual
from actual.queries import (
    get_accounts,
    get_transactions,
    get_category_groups,
    get_categories as actual_get_categories,
    get_or_create_payee,
    create_transaction,
    create_category,
    create_category_group,
    get_or_create_category_group,
)

load_dotenv()

# Configuration
ACTUAL_SERVER_URL = os.getenv("ACTUAL_SERVER_URL", "http://localhost:5006")
ACTUAL_PASSWORD = os.getenv("ACTUAL_PASSWORD", "jc")
ACTUAL_BUDGET_NAME = os.getenv("ACTUAL_BUDGET_NAME", "My Finances")
ACTUAL_FILE_ID = os.getenv("ACTUAL_FILE_ID", None)  # Fallback for dev mode
FINANCE_API_KEY = os.getenv("FINANCE_API_KEY", "")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3003,http://localhost:3000").split(",")

# JWT Configuration (must match backend)
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://familyapp:familyapp123@db:5432/familyapp")

# Create database engine (synchronous for simple queries)
engine = create_engine(
    DATABASE_URL.replace("+asyncpg", ""),  # Use psycopg2 instead of asyncpg
    poolclass=NullPool  # Don't pool connections in this simple service
)

# --- Auth ---

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    """Verify API key if one is configured. Skips auth if FINANCE_API_KEY is empty."""
    if not FINANCE_API_KEY:
        return  # No key configured = open access (dev mode)
    if api_key != FINANCE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


def decode_jwt_token(token: str) -> dict:
    """Decode JWT token from Authorization header."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_family_budget_file_id(authorization: Optional[str] = Header(None)) -> str:
    """
    Get the family's Actual Budget file ID from database based on JWT token.
    
    Returns:
        The family's actual_budget_file_id
    
    Raises:
        HTTPException: If not authenticated, family not found, or no budget configured
    """
    if not authorization:
        # Fallback to environment variable for backward compatibility / dev mode
        if ACTUAL_FILE_ID:
            return ACTUAL_FILE_ID
        raise HTTPException(
            status_code=401,
            detail="Authorization header required"
        )
    
    # Extract token from "Bearer <token>"
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    token = authorization.replace("Bearer ", "")
    payload = decode_jwt_token(token)
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    # Query database for user's family and budget file ID
    with engine.connect() as conn:
        # Get user's family_id
        user_query = text("SELECT family_id FROM users WHERE id = :user_id")
        result = conn.execute(user_query, {"user_id": user_id})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        
        family_id = row[0]
        
        # Get family's Actual Budget file ID
        family_query = text("""
            SELECT actual_budget_file_id, actual_budget_sync_enabled 
            FROM families 
            WHERE id = :family_id
        """)
        result = conn.execute(family_query, {"family_id": family_id})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Family not found")
        
        budget_file_id = row[0]
        sync_enabled = row[1]
        
        if not budget_file_id:
            raise HTTPException(
                status_code=404, 
                detail="No Actual Budget configured for your family. Please contact an administrator."
            )
        
        if not sync_enabled:
            raise HTTPException(
                status_code=403,
                detail="Actual Budget sync is disabled for your family."
            )
        
        return budget_file_id


# --- App ---

app = FastAPI(title="Family Finance API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- Pydantic models ---

class TransactionCreate(BaseModel):
    account_id: str
    category_id: str
    amount: float
    notes: str = ""
    date: Optional[str] = None
    payee_name: str = "Family Task Manager"


class CategoryCreate(BaseModel):
    name: str
    group_name: str = "Usual Expenses"


class CategoryGroupCreate(BaseModel):
    name: str


class ConversionDepositCreate(BaseModel):
    """Request to deposit converted points into child's accounts."""
    child_name: str
    total_amount_mxn: float
    points_converted: int
    notes: str = ""
    date: Optional[str] = None


# --- Helpers ---

@contextmanager
def get_actual(file_id: str):
    """Context manager for Actual Budget connection."""
    with Actual(base_url=ACTUAL_SERVER_URL, password=ACTUAL_PASSWORD, file=file_id) as actual:
        yield actual


# --- Routes ---

@app.get("/api/finance/summary")
def get_summary(
    file_id: str = Depends(get_family_budget_file_id),
    _: None = Depends(verify_api_key)
):
    """Get a high-level summary of all accounts and balances."""
    try:
        with get_actual(file_id) as actual:
            accounts = get_accounts(actual.session)
            result = []
            total_balance = 0

            for acc in accounts:
                transactions = get_transactions(actual.session, account=acc)
                balance = sum(
                    float(t.amount) / 100 if hasattr(t, "amount") and t.amount else 0
                    for t in transactions
                )
                total_balance += balance
                last_tx = None
                if transactions:
                    last = sorted(
                        transactions,
                        key=lambda t: t.date or datetime.date.min,
                        reverse=True,
                    )[0]
                    last_tx = {
                        "date": str(last.date) if last.date else None,
                        "amount": float(last.amount) / 100 if last.amount else 0,
                        "notes": last.notes,
                    }

                result.append(
                    {
                        "id": str(acc.id),
                        "name": acc.name,
                        "balance": round(balance, 2),
                        "transaction_count": len(transactions),
                        "last_transaction": last_tx,
                    }
                )

            return {
                "accounts": result,
                "total_balance": round(total_balance, 2),
                "account_count": len(result),
                "budget_name": ACTUAL_BUDGET_NAME,
                "synced_at": datetime.datetime.now().isoformat(),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/finance/accounts/{account_id}/transactions")
def get_account_transactions(
    account_id: str,
    file_id: str = Depends(get_family_budget_file_id),
    _: None = Depends(verify_api_key)
):
    """Get transactions for a specific account."""
    try:
        with get_actual(file_id) as actual:
            accounts = get_accounts(actual.session)
            account = next((a for a in accounts if str(a.id) == account_id), None)
            if not account:
                raise HTTPException(status_code=404, detail="Account not found")

            transactions = get_transactions(actual.session, account=account)
            return {
                "account": {"id": str(account.id), "name": account.name},
                "transactions": [
                    {
                        "id": str(t.id),
                        "date": str(t.date) if t.date else None,
                        "amount": float(t.amount) / 100 if t.amount else 0,
                        "notes": t.notes,
                        "payee_name": t.payee.name if t.payee else None,
                        "category_name": t.category.name if t.category else None,
                    }
                    for t in sorted(
                        transactions,
                        key=lambda t: t.date or datetime.date.min,
                        reverse=True,
                    )
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/finance/categories")
def get_categories(
    month: Optional[str] = None,
    file_id: str = Depends(get_family_budget_file_id),
    _: None = Depends(verify_api_key)
):
    """Get categories and their current budget/balance for a given month (YYYY-MM)."""
    if not month:
        month = datetime.date.today().strftime("%Y-%m")

    try:
        with get_actual(file_id) as actual:
            groups = get_category_groups(actual.session)
            categories = actual_get_categories(actual.session)

            # Get budget amounts for the month
            # Query zero_budgets table for budget amounts
            from sqlalchemy import text
            month_int = int(month.replace("-", ""))  # Convert "2026-02" to 202602
            
            budget_query = text("""
                SELECT category, amount 
                FROM zero_budgets 
                WHERE month = :month
            """)
            budget_results = actual.session.execute(budget_query, {"month": month_int}).fetchall()
            budget_map = {str(row[0]): row[1] for row in budget_results}
            
            # Get spent amounts by category for the month
            # Parse month to get start and end dates
            year, month_num = month.split("-")
            start_date = int(f"{year}{month_num}01")
            if month_num == "12":
                end_date = int(f"{int(year)+1}0101")
            else:
                end_date = int(f"{year}{int(month_num)+1:02d}01")
            
            spent_query = text("""
                SELECT category, SUM(amount) as spent
                FROM transactions
                WHERE category IS NOT NULL 
                  AND date >= :start_date 
                  AND date < :end_date
                  AND isParent = 0
                GROUP BY category
            """)
            spent_results = actual.session.execute(
                spent_query, 
                {"start_date": start_date, "end_date": end_date}
            ).fetchall()
            spent_map = {str(row[0]): abs(row[1] or 0) for row in spent_results}

            cat_map = {}
            for c in categories:
                budgeted = budget_map.get(str(c.id), 0) or 0
                spent = spent_map.get(str(c.id), 0)
                balance = budgeted - spent
                
                cat_map[c.id] = {
                    "id": str(c.id),
                    "name": c.name,
                    "group_id": str(c.cat_group),
                    "is_income": c.is_income,
                    "budgeted": float(budgeted) / 100,  # Convert cents to currency
                    "spent": float(spent) / 100,
                    "balance": float(balance) / 100,
                }
            
            group_list = []
            for g in groups:
                group_cats = [c for c in cat_map.values() if c["group_id"] == str(g.id)]
                
                # Calculate group totals
                group_budgeted = sum(c["budgeted"] for c in group_cats)
                group_spent = sum(c["spent"] for c in group_cats)
                group_balance = sum(c["balance"] for c in group_cats)
                
                group_list.append(
                    {
                        "id": str(g.id),
                        "name": g.name,
                        "is_income": g.is_income,
                        "budgeted": round(group_budgeted, 2),
                        "spent": round(group_spent, 2),
                        "balance": round(group_balance, 2),
                        "categories": group_cats,
                    }
                )

            return {"month": month, "groups": group_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/finance/categories/{category_id}/transactions")
def get_category_transactions(
    category_id: str,
    file_id: str = Depends(get_family_budget_file_id),
    _: None = Depends(verify_api_key)
):
    """Get transactions for a specific category."""
    try:
        with get_actual(file_id) as actual:
            categories = actual_get_categories(actual.session)
            category = next((c for c in categories if str(c.id) == category_id), None)
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")

            transactions = get_transactions(actual.session, category=category)
            return {
                "category": {"id": str(category.id), "name": category.name},
                "transactions": [
                    {
                        "id": str(t.id),
                        "date": str(t.date) if t.date else None,
                        "amount": float(t.amount) / 100 if t.amount else 0,
                        "notes": t.notes,
                        "payee_name": t.payee.name if t.payee else None,
                        "account_name": t.account.name if getattr(t, "account", None) else None,
                    }
                    for t in sorted(
                        transactions,
                        key=lambda t: t.date or datetime.date.min,
                        reverse=True,
                    )
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/finance/transactions")
def add_transaction(
    data: TransactionCreate,
    file_id: str = Depends(get_family_budget_file_id),
    _: None = Depends(verify_api_key)
):
    """Create a new transaction in Actual Budget."""
    try:
        with get_actual(file_id) as actual:
            accounts = get_accounts(actual.session)
            account = next((a for a in accounts if str(a.id) == data.account_id), None)
            if not account:
                # Fallback to the first account if specific account not found
                account = accounts[0] if accounts else None
                if not account:
                    raise HTTPException(
                        status_code=400, detail="No accounts exist to create transaction"
                    )

            categories = actual_get_categories(actual.session)
            category = next((c for c in categories if str(c.id) == data.category_id), None)

            payee = get_or_create_payee(actual.session, data.payee_name)
            tx_date = datetime.date.fromisoformat(data.date) if data.date else datetime.date.today()

            t = create_transaction(
                actual.session,
                tx_date,
                account,
                payee,
                category=category,
                notes=data.notes,
                amount=decimal.Decimal(str(data.amount)),
            )
            actual.commit()
            return {"status": "ok", "transaction_id": str(t.id)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/finance/categories")
def add_category(
    data: CategoryCreate,
    file_id: str = Depends(get_family_budget_file_id),
    _: None = Depends(verify_api_key)
):
    """Create a new budget category."""
    try:
        with get_actual(file_id) as actual:
            category = create_category(
                actual.session,
                name=data.name,
                group_name=data.group_name
            )
            actual.commit()
            return {
                "status": "ok",
                "category": {
                    "id": str(category.id),
                    "name": category.name,
                    "group_id": str(category.cat_group),
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/finance/category-groups")
def add_category_group(
    data: CategoryGroupCreate,
    file_id: str = Depends(get_family_budget_file_id),
    _: None = Depends(verify_api_key)
):
    """Create a new category group."""
    try:
        with get_actual(file_id) as actual:
            group = create_category_group(actual.session, name=data.name)
            actual.commit()
            return {
                "status": "ok",
                "group": {
                    "id": str(group.id),
                    "name": group.name,
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/finance/convert-deposit")
def create_conversion_deposit(
    data: ConversionDepositCreate,
    file_id: str = Depends(get_family_budget_file_id),
    _: None = Depends(verify_api_key)
):
    """
    Create deposit transactions for point-to-money conversion.
    
    Splits the total amount as:
    - 85% to Checking/Cash account (spendable)
    - 15% to Savings account (locked)
    
    Both transactions use the "Domingos" category and are marked with
    imported_id to prevent sync loops.
    """
    try:
        with get_actual(file_id) as actual:
            # Get accounts
            accounts = get_accounts(actual.session)
            account_map = {a.name: a for a in accounts}
            
            # Find child's accounts
            checking_name = f"{data.child_name} - Cuenta de Cheques/Cash"
            savings_name = f"{data.child_name} - Cuenta de Ahorros"
            
            checking_account = account_map.get(checking_name)
            savings_account = account_map.get(savings_name)
            
            if not checking_account:
                raise HTTPException(
                    status_code=404,
                    detail=f"Checking account not found: {checking_name}. Please run setup_family_budget.py first."
                )
            
            if not savings_account:
                raise HTTPException(
                    status_code=404,
                    detail=f"Savings account not found: {savings_name}. Please run setup_family_budget.py first."
                )
            
            # Get or create Domingos category
            categories = actual_get_categories(actual.session)
            domingos_category = next((c for c in categories if c.name == "Domingos"), None)
            
            if not domingos_category:
                # Create Domingos category if it doesn't exist
                domingos_category = create_category(
                    actual.session,
                    name="Domingos",
                    group_name="Gastos Familiares"
                )
            
            # Get or create payee
            payee = get_or_create_payee(actual.session, data.child_name)
            
            # Parse date
            tx_date = datetime.date.fromisoformat(data.date) if data.date else datetime.date.today()
            
            # Calculate split amounts
            checking_amount = round(data.total_amount_mxn * 0.85, 2)
            savings_amount = round(data.total_amount_mxn * 0.15, 2)
            
            # Create unique imported_ids to prevent sync loops
            import_base = f"ftm-conversion-{data.child_name.replace(' ', '-')}-{tx_date.isoformat()}"
            checking_imported_id = f"{import_base}-checking"
            savings_imported_id = f"{import_base}-savings"
            
            # Create checking deposit (85%)
            checking_tx = create_transaction(
                actual.session,
                tx_date,
                checking_account,
                payee,
                category=domingos_category,
                notes=f"{data.notes} (85% spendable - {data.points_converted} points)",
                amount=decimal.Decimal(str(checking_amount)),
                imported_id=checking_imported_id,
            )
            
            # Create savings deposit (15%)
            savings_tx = create_transaction(
                actual.session,
                tx_date,
                savings_account,
                payee,
                category=domingos_category,
                notes=f"{data.notes} (15% savings - {data.points_converted} points)",
                amount=decimal.Decimal(str(savings_amount)),
                imported_id=savings_imported_id,
            )
            
            # Commit both transactions
            actual.commit()
            
            return {
                "status": "ok",
                "total_amount": data.total_amount_mxn,
                "checking_deposit": {
                    "transaction_id": str(checking_tx.id),
                    "account": checking_name,
                    "amount": checking_amount,
                    "percentage": 85,
                },
                "savings_deposit": {
                    "transaction_id": str(savings_tx.id),
                    "account": savings_name,
                    "amount": savings_amount,
                    "percentage": 15,
                },
                "notes": data.notes,
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok", "service": "family-finance-api"}
