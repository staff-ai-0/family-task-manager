"""Platform-wide operator reads."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_superadmin
from app.models.user import User
from app.services.admin.admin_read_service import AdminReadService

router = APIRouter()


@router.get("/overview")
async def platform_overview(
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-screen platform state: tenants, users, billing, queues."""
    return await AdminReadService.platform_pulse(db)
