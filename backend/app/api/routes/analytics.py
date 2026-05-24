"""Parent analytics routes (W5.2)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.analytics_service import AnalyticsService


router = APIRouter()


@router.get("/pup-score")
async def pup_score(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await AnalyticsService.pup_score(
        db, to_uuid_required(current_user.family_id)
    )


@router.get("/pup-history")
async def pup_history(
    days: int = 30,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    days = max(7, min(180, int(days)))
    return await AnalyticsService.list_snapshots(
        db, to_uuid_required(current_user.family_id), days=days
    )


@router.get("/export.csv")
async def export_csv(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Per-member completion + late + gigs as CSV. Last 4 weeks."""
    from fastapi.responses import StreamingResponse
    import csv
    import io

    members = await AnalyticsService.per_member_completion_rate(
        db, to_uuid_required(current_user.family_id), lookback_weeks=4
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "user_id", "name", "role",
        "mandatory_total", "mandatory_done", "mandatory_late",
        "completion_rate", "gigs_completed",
    ])
    for m in members:
        w.writerow([
            m["user_id"], m["name"], m["role"],
            m["mandatory_total"], m["mandatory_done"], m["mandatory_late"],
            m["completion_rate"], m["gigs_completed"],
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="family-analytics.csv"'},
    )
