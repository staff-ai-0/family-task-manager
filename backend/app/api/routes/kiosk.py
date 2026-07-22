"""Kiosk routes (W3.3, P1-KIOSK).

- /devices CRUD (parent only): provision and revoke wall-display tokens.
- /snapshot (token-gated public): returns family snapshot for the kiosk
  page. The token itself is the auth.
- /member-prefs (parent only): per-member kiosk color + 4-digit PIN.
- /pin-view (token-gated public): PIN-scoped per-kid view on the kiosk.

Business logic lives in `app.services.kiosk_service.KioskService` — this
file is routing + dependency injection only.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
from app.schemas.kiosk import (
    DeviceCreate,
    DeviceOut,
    KidView,
    KioskSnapshot,
    MemberPrefOut,
    MemberPrefUpdate,
    PinViewRequest,
)
from app.services.kiosk_service import KioskService

router = APIRouter()


# ─── Device management (parent only) ────────────────────────────────


@router.get("/devices", response_model=List[DeviceOut])
async def list_devices(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await KioskService.list_devices(db, to_uuid_required(current_user.family_id))


@router.post(
    "/devices",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_device(
    data: DeviceCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await KioskService.create_device(
        db,
        to_uuid_required(current_user.family_id),
        data.name,
        to_uuid_required(current_user.id),
    )


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    await KioskService.delete_device(
        db, to_uuid_required(current_user.family_id), device_id
    )
    return None


# ─── Member prefs: color + kiosk PIN (parent only) ──────────────────


@router.get("/member-prefs", response_model=List[MemberPrefOut])
async def list_member_prefs(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await KioskService.list_member_prefs(
        db, to_uuid_required(current_user.family_id)
    )


@router.put("/member-prefs/{user_id}", response_model=MemberPrefOut)
async def update_member_prefs(
    user_id: UUID,
    data: MemberPrefUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await KioskService.update_member_prefs(
        db,
        to_uuid_required(current_user.family_id),
        user_id,
        color=data.color,
        pin=data.pin,
    )


# ─── Per-kid PIN view (token-gated, no user auth) ────────────────────


@router.post("/pin-view", response_model=KidView)
async def pin_view(
    data: PinViewRequest,
    db: AsyncSession = Depends(get_db),
):
    return await KioskService.resolve_pin_view(
        db, data.token, data.user_id, data.pin
    )


# ─── Snapshot (token-gated, no user auth) ────────────────────────────


@router.get("/snapshot", response_model=KioskSnapshot)
async def snapshot(
    token: str = Query(..., min_length=10, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    return await KioskService.get_snapshot(db, token)
