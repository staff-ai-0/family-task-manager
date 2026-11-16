"""Profile switcher routes (UX-E4), mounted at /api/auth/profile/*.

All three are authenticated by the parent's refresh token ("home token")
as a Bearer, never by an access token.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limiter import AUTH_LIMIT, limiter
from app.core.security import oauth2_scheme
from app.schemas.user import (
    ProfileListResponse,
    ProfileReturnRequest,
    ProfileReturnResponse,
    ProfileSwitchRequest,
    ProfileSwitchResponse,
    UserResponse,
)
from app.services.profile_switch_service import ProfileSwitchService

router = APIRouter()


@router.get("/profile/list", response_model=ProfileListResponse)
async def list_profiles(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    home = await ProfileSwitchService.resolve_home(db, token)
    profiles = await ProfileSwitchService.list_profiles(db, home)
    return ProfileListResponse(
        profiles=profiles,
        home_refresh_token=ProfileSwitchService.new_home_token(home),
    )


@router.post("/profile/switch", response_model=ProfileSwitchResponse)
@limiter.limit(AUTH_LIMIT)
async def switch_profile(
    request: Request,
    body: ProfileSwitchRequest,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    home = await ProfileSwitchService.resolve_home(db, token)
    user, access, refresh = await ProfileSwitchService.switch(
        db, home, body.user_id, body.pin
    )
    return ProfileSwitchResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        user=UserResponse.model_validate(user),
        switched=True,
        home_refresh_token=ProfileSwitchService.new_home_token(home),
    )


@router.post("/profile/return", response_model=ProfileReturnResponse)
@limiter.limit(AUTH_LIMIT)
async def return_to_parent(
    request: Request,
    body: ProfileReturnRequest,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    home = await ProfileSwitchService.resolve_home(db, token)
    user, access, refresh = await ProfileSwitchService.return_to_parent(
        db, home, body.password
    )
    return ProfileReturnResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )
