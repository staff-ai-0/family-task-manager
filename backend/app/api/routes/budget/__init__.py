"""
Budget routes module

API endpoints for budget management.
"""

from fastapi import APIRouter
from app.api.routes.budget import categories, accounts, transactions, allocations, payees, month

router = APIRouter()

# Include sub-routers
router.include_router(categories.router, prefix="/categories", tags=["budget-categories"])
router.include_router(accounts.router, prefix="/accounts", tags=["budget-accounts"])
router.include_router(transactions.router, prefix="/transactions", tags=["budget-transactions"])
router.include_router(allocations.router, prefix="/allocations", tags=["budget-allocations"])
router.include_router(payees.router, prefix="/payees", tags=["budget-payees"])
router.include_router(month.router, prefix="/month", tags=["budget-month"])

__all__ = ["router"]
