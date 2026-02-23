#!/usr/bin/env python3
"""
Finance API — Micro-service that exposes Actual Budget data as JSON.
Runs on port 5007 and is consumed by the Astro frontend via SSR fetch.

Usage:
    source .venv/bin/activate
    uvicorn api:app --port 5007 --reload
"""

import os
import datetime
import decimal
from contextlib import contextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

ACTUAL_SERVER_URL = os.getenv("ACTUAL_SERVER_URL", "http://localhost:5006")
ACTUAL_PASSWORD = os.getenv("ACTUAL_PASSWORD", "jc")
ACTUAL_BUDGET_NAME = os.getenv("ACTUAL_BUDGET_NAME", "My Finances")

app = FastAPI(title="Family Finance API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@contextmanager
def get_actual():
    """Context manager for Actual Budget connection."""
    from actual import Actual
    with Actual(base_url=ACTUAL_SERVER_URL, password=ACTUAL_PASSWORD, file=ACTUAL_BUDGET_NAME) as actual:
        yield actual


@app.get("/api/finance/summary")
def get_summary():
    """Get a high-level summary of all accounts and balances."""
    try:
        from actual.queries import get_accounts, get_transactions
        with get_actual() as actual:
            accounts = get_accounts(actual.session)
            result = []
            total_balance = 0

            for acc in accounts:
                transactions = get_transactions(actual.session, account=acc)
                balance = sum(
                    float(t.amount) / 100 if hasattr(t, 'amount') and t.amount else 0
                    for t in transactions
                )
                total_balance += balance
                last_tx = None
                if transactions:
                    last = sorted(transactions, key=lambda t: t.date or datetime.date.min, reverse=True)[0]
                    last_tx = {
                        "date": str(last.date) if last.date else None,
                        "amount": float(last.amount) / 100 if last.amount else 0,
                        "notes": last.notes,
                    }

                result.append({
                    "id": str(acc.id),
                    "name": acc.name,
                    "balance": round(balance, 2),
                    "transaction_count": len(transactions),
                    "last_transaction": last_tx,
                })

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
def get_account_transactions(account_id: str):
    """Get transactions for a specific account."""
    try:
        from actual.queries import get_accounts, get_transactions
        with get_actual() as actual:
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
                    for t in sorted(transactions, key=lambda t: t.date or datetime.date.min, reverse=True)
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/finance/categories")
def get_categories(month: str = None):
    """Get categories and their current budget/balance for a given month (YYYY-MM)."""
    if not month:
        month = datetime.date.today().strftime("%Y-%m")
        
    try:
        from actual.queries import get_category_groups, get_categories as actual_get_categories
        with get_actual() as actual:
            # We would need to read budget balances, but actualpy limits this somewhat natively.
            # As a simplification for the API, we'll return the categories.
            # In a real implementation we would query the `zero_budget_months` table.
            
            groups = get_category_groups(actual.session)
            categories = actual_get_categories(actual.session)
            
            cat_map = {c.id: {'id': str(c.id), 'name': c.name, 'group_id': str(c.cat_group), 'is_income': c.is_income} for c in categories}
            group_list = []
            
            for g in groups:
                group_cats = [c for c in cat_map.values() if c['group_id'] == str(g.id)]
                group_list.append({
                    "id": str(g.id),
                    "name": g.name,
                    "is_income": g.is_income,
                    "categories": group_cats
                })
                
            return {
                "month": month,
                "groups": group_list
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/finance/categories/{category_id}/transactions")
def get_category_transactions(category_id: str):
    """Get transactions for a specific category."""
    try:
        from actual.queries import get_categories as actual_get_categories, get_transactions
        with get_actual() as actual:
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
                        "account_name": t.account.name if getattr(t, 'account', None) else None,
                    }
                    for t in sorted(transactions, key=lambda t: t.date or datetime.date.min, reverse=True)
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "ok", "service": "family-finance-api"}

from pydantic import BaseModel
class TransactionCreate(BaseModel):
    account_id: str
    category_id: str
    amount: float
    notes: str = ""
    date: str = None
    payee_name: str = "Family Task Manager"

@app.post("/api/finance/transactions")
def add_transaction(data: TransactionCreate):
    """Create a new transaction in Actual Budget."""
    try:
        from actual.queries import get_accounts, get_categories as actual_get_categories, get_or_create_payee, create_transaction
        with get_actual() as actual:
            accounts = get_accounts(actual.session)
            account = next((a for a in accounts if str(a.id) == data.account_id), None)
            if not account:
                # Fallback to the first account (e.g. cash) if specific account not found
                account = accounts[0] if accounts else None
                if not account:
                    raise HTTPException(status_code=400, detail="No accounts exist to create transaction")

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

