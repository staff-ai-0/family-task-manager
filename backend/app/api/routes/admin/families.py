"""Per-family operator reads."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_superadmin
from app.models.user import User
from app.services.admin.admin_lookup_service import AdminLookupService
from app.services.admin.admin_read_service import AdminReadService

router = APIRouter()


@router.get("/families")
async def list_families(
    q: Optional[str] = Query(None, description="name, join code, id, or member email"),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Family directory with search."""
    return await AdminLookupService.search_families(
        db, q=q, include_deleted=include_deleted, limit=limit, offset=offset
    )


@router.get("/families/{family_id}")
async def family_detail(
    family_id: UUID,
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full support view of one family. Metadata only — never content."""
    return await AdminReadService.family_detail(db, family_id)


@router.get("/families/{family_id}/paycheck-preview/{kid_id}")
async def paycheck_preview(
    family_id: UUID,
    kid_id: UUID,
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Side-effect-free projection + the kid's unreleased weeks.

    The operator must see this before releasing anything.
    """
    from fastapi import HTTPException, status as http_status

    from app.models.user import User as UserModel
    from app.services.bank_service import BankService

    kid = await db.scalar(select(UserModel).where(UserModel.id == kid_id))
    if kid is None or kid.family_id != family_id:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Not Found")
    return {
        "preview": await BankService.chore_paycheck_preview(db, kid, family_id),
        "outstanding_weeks": await BankService.list_outstanding_weeks(
            db, kid, family_id
        ),
    }
