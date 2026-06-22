"""Sync API — decommissioned in Phase 10 (budget went native PostgreSQL).

Every /api/sync/* endpoint returns 410 Gone. Kept as a small tombstone so any
old client gets a clear, permanent signal (and a pointer to the replacement)
instead of a bare 404. See CLAUDE.md: "/api/sync/* — returns 410 Gone".
"""
from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def sync_gone(path: str = ""):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "The sync API was decommissioned in Phase 10. "
            "Budget data is now native; use /api/budget/."
        ),
    )
