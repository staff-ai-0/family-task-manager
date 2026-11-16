"""Profile switcher routes (UX-E4), mounted at /api/auth/profile/*.

`share` is authenticated by the parent's ordinary ACCESS token and returns a
"home" token. `list`, `switch` and `return` accept ONLY that home token as
the Bearer (type "home"); a refresh or access token gets 401 there, and a
home token gets 401 everywhere else.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limiter import AUTH_LIMIT, limiter
from app.core.security import oauth2_scheme
from app.models.user import User
from app.schemas.user import (
    ProfileListResponse,
    ProfileReturnRequest,
    ProfileReturnResponse,
    ProfileShareResponse,
    ProfileSwitchRequest,
    ProfileSwitchResponse,
    UserResponse,
)
from app.services.profile_switch_service import ProfileSwitchService

router = APIRouter()


@router.post("/profile/share", response_model=ProfileShareResponse)
async def share_device(
    token: str = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_user),
):
    return ProfileShareResponse(home_token=ProfileSwitchService.share(current_user, token))


@router.get("/profile/list", response_model=ProfileListResponse)
async def list_profiles(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    home = await ProfileSwitchService.resolve_home(db, token)
    profiles = await ProfileSwitchService.list_profiles(db, home)
    return ProfileListResponse(
        profiles=profiles,
        home_token=ProfileSwitchService.new_home_token(home),
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
        home_token=ProfileSwitchService.new_home_token(home),
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
