"""
Budget routes module

API endpoints for budget management.
"""

from fastapi import APIRouter
from app.api.routes.budget import categories, accounts, transactions, allocations, payees, month, transfers, reports, categorization_rules, goals, recurring_transactions, months, recycle_bin, saved_filters, tags, export, custom_reports, receipt_drafts, items, a2a_webhook as _a2a, price_comparison as _price_comparison, bank_sync as _bank_sync, ai_settings as _ai_settings

router = APIRouter()

# Include sub-routers
router.include_router(categories.router, prefix="/categories", tags=["budget-categories"])
router.include_router(accounts.router, prefix="/accounts", tags=["budget-accounts"])
router.include_router(transactions.router, prefix="/transactions", tags=["budget-transactions"])
router.include_router(allocations.router, prefix="/allocations", tags=["budget-allocations"])
router.include_router(payees.router, prefix="/payees", tags=["budget-payees"])
router.include_router(month.router, prefix="/month", tags=["budget-month"])
router.include_router(months.router, prefix="/months", tags=["budget-months"])
router.include_router(transfers.router, prefix="/transfers", tags=["budget-transfers"])
router.include_router(reports.router, prefix="/reports", tags=["budget-reports"])
router.include_router(categorization_rules.router, prefix="/categorization-rules", tags=["budget-categorization-rules"])
router.include_router(goals.router, prefix="/goals", tags=["budget-goals"])
router.include_router(recurring_transactions.router, prefix="/recurring-transactions", tags=["budget-recurring-transactions"])
router.include_router(recycle_bin.router, prefix="/recycle-bin", tags=["budget-recycle-bin"])
router.include_router(saved_filters.router, prefix="/saved-filters", tags=["Budget - Saved Filters"])
router.include_router(tags.router, prefix="/tags", tags=["Budget - Tags"])
router.include_router(export.router, tags=["budget-export"])
router.include_router(custom_reports.router, prefix="/custom-reports", tags=["budget-custom-reports"])
router.include_router(receipt_drafts.router, prefix="/receipt-drafts", tags=["budget-receipt-drafts"])
router.include_router(items.router, prefix="/items", tags=["budget-items"])
router.include_router(_a2a.router, prefix="/a2a-webhook", tags=["budget-a2a"])
router.include_router(
    _price_comparison.router,
    prefix="/price-comparison",
    tags=["budget-price-comparison"],
)
router.include_router(_bank_sync.router, prefix="/bank-sync", tags=["budget-bank-sync"])
router.include_router(_ai_settings.router, prefix="/ai-settings", tags=["budget-ai-settings"])

__all__ = ["router"]
