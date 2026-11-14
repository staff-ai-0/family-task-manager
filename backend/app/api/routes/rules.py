"""Rules acceptance endpoints. HTTP only; logic in RulesService."""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.models.user import User
from app.schemas.rules import AcceptanceRow, AcceptRequest, AcceptResponse, RulesStatus
from app.services.rules_service import RulesService

router = APIRouter()


@router.get("/status", response_model=RulesStatus)
async def rules_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await RulesService.status(db, current_user)


@router.post("/accept", response_model=AcceptResponse)
async def accept_rules(
    body: AcceptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Everyone accepts only for themself: the user comes from the token.
    row = await RulesService.accept(db, current_user, body.version)
    return {"version": row.rules_version, "accepted_at": row.accepted_at}


@router.get("/acceptances", response_model=List[AcceptanceRow])
async def list_acceptances(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await RulesService.acceptances(db, current_user.family_id)


@router.post("/announce")
async def announce_rules(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"sent": await RulesService.announce(db, current_user.family_id)}
