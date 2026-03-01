"""
DEPRECATED: Sync API Routes (Phase 10 Decommissioning)

These endpoints are no longer available as of Phase 10.

The Actual Budget sync service has been decommissioned.
All Actual Budget functionality has been migrated to the internal
PostgreSQL-based budget system.

For budget management, use the endpoints in:
- /api/budget/categories - Category management
- /api/budget/accounts - Account management
- /api/budget/transactions - Transaction management
- /api/budget/allocations - Budget allocations

Note: This module is kept for backwards compatibility and documentation.
All sync endpoints now return 410 Gone status.
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime

router = APIRouter(prefix="/api/sync", tags=["Sync (Deprecated)"])


@router.post("/trigger")
async def trigger_sync():
    """DEPRECATED: Sync service has been decommissioned."""
    raise HTTPException(
        status_code=410,
        detail="Sync service has been decommissioned in Phase 10. "
               "Use the internal PostgreSQL budget system instead via /api/budget/* endpoints."
    )


@router.get("/status")
async def get_sync_status():
    """DEPRECATED: Sync service has been decommissioned."""
    raise HTTPException(
        status_code=410,
        detail="Sync service has been decommissioned in Phase 10. "
               "Use the internal PostgreSQL budget system instead via /api/budget/* endpoints."
    )


@router.get("/health")
async def check_sync_health():
    """DEPRECATED: Sync service has been decommissioned."""
    return {
        "healthy": False,
        "status": "decommissioned",
        "message": "Sync service has been decommissioned in Phase 10",
        "migration_path": "Use /api/budget/* endpoints for budget management",
        "timestamp": datetime.utcnow().isoformat(),
    }
