"""UX-D1 progress: the signed-in kid's streak + rank, and the rank-up ack."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.progress import AckRankRequest, ProgressResponse
from app.services.progress_service import KID_ROLES, ProgressService, rank_for_xp

router = APIRouter()


@router.get("/me", response_model=ProgressResponse)
async def my_progress(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    return await ProgressService.progress_for(db, current_user)


@router.post("/me/ack-rank", status_code=status.HTTP_204_NO_CONTENT)
async def ack_rank(
    data: AckRankRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if current_user.role not in KID_ROLES:
        raise HTTPException(status_code=404, detail="Not found")
    held = rank_for_xp(await ProgressService.xp_for(db, current_user.family_id, current_user.id))
    current_user.last_seen_rank = max(current_user.last_seen_rank or 1, min(data.rank, held))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
