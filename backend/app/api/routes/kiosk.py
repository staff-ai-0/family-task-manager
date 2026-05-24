"""Kiosk routes (W3.3).

- /devices CRUD (parent only): provision and revoke wall-display tokens.
- /snapshot (token-gated public): returns family snapshot for the kiosk
  page. The token itself is the auth.
"""

import secrets
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
from app.models.calendar_event import CalendarEvent
from app.models.kiosk_device import KioskDevice
from app.models.shopping import ShoppingItem, ShoppingList
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.task_template import TaskTemplate
from app.models.user import UserRole


router = APIRouter()


# ─── Device management (parent only) ────────────────────────────────


class DeviceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class DeviceOut(BaseModel):
    id: UUID
    name: str
    token: str
    is_active: bool
    last_seen: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/devices", response_model=List[DeviceOut])
async def list_devices(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    fam = to_uuid_required(current_user.family_id)
    q = (
        select(KioskDevice)
        .where(KioskDevice.family_id == fam)
        .order_by(KioskDevice.created_at.desc())
    )
    return list((await db.execute(q)).scalars().all())


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
    token = secrets.token_urlsafe(32)[:64]
    device = KioskDevice(
        family_id=to_uuid_required(current_user.family_id),
        name=data.name,
        token=token,
        created_by=to_uuid_required(current_user.id),
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    fam = to_uuid_required(current_user.family_id)
    q = select(KioskDevice).where(
        and_(KioskDevice.id == device_id, KioskDevice.family_id == fam)
    )
    dev = (await db.execute(q)).scalar_one_or_none()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.delete(dev)
    await db.commit()
    return None


# ─── Snapshot (token-gated, no user auth) ────────────────────────────


class KioskMember(BaseModel):
    id: UUID
    name: str
    role: str
    tasks_today: int
    tasks_done: int


class KioskTask(BaseModel):
    title: str
    user_name: str
    is_done: bool
    is_bonus: bool


class KioskEvent(BaseModel):
    title: str
    start_ts: datetime
    location: Optional[str] = None
    all_day: bool


class KioskShoppingList(BaseModel):
    name: str
    pending: int


class KioskSnapshot(BaseModel):
    family_name: str
    now_utc: datetime
    members: List[KioskMember]
    tasks: List[KioskTask]
    events_today: List[KioskEvent]
    events_tomorrow: List[KioskEvent]
    shopping: List[KioskShoppingList]


@router.get("/snapshot", response_model=KioskSnapshot)
async def snapshot(
    token: str = Query(..., min_length=10, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    # Look up device by token. is_active gates access. last_seen is updated
    # so the parent UI can show whether a kiosk is alive.
    q = select(KioskDevice).where(KioskDevice.token == token)
    device = (await db.execute(q)).scalar_one_or_none()
    if not device or not device.is_active:
        raise HTTPException(status_code=401, detail="Invalid kiosk token")
    device.last_seen = datetime.now(timezone.utc)

    family_id = device.family_id
    from app.models.family import Family
    family = await db.get(Family, family_id)
    fam_name = family.name if family else ""

    # Today/tomorrow window in family timezone
    tz_name = (family.timezone if family and family.timezone else None) or "UTC"
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now_local = datetime.now(tz)
    today_local = now_local.date()
    tomorrow_local = today_local + timedelta(days=1)
    today_start = datetime.combine(today_local, datetime.min.time(), tzinfo=tz)
    tomorrow_start = today_start + timedelta(days=1)
    day_after = today_start + timedelta(days=2)

    # Members
    members_q = select(User).where(
        and_(User.family_id == family_id, User.is_active.is_(True))
    )
    users = list((await db.execute(members_q)).scalars().all())

    # Today's task assignments
    tasks_q = (
        select(TaskAssignment)
        .options(selectinload(TaskAssignment.template))
        .where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_date == today_local,
            )
        )
    )
    assignments = list((await db.execute(tasks_q)).scalars().all())

    user_name = {u.id: u.name for u in users}

    members_out: List[KioskMember] = []
    for u in users:
        u_tasks = [a for a in assignments if a.assigned_to == u.id]
        done = sum(1 for a in u_tasks if a.status == AssignmentStatus.COMPLETED)
        members_out.append(
            KioskMember(
                id=u.id,
                name=u.name,
                role=u.role.value if hasattr(u.role, "value") else str(u.role),
                tasks_today=len(u_tasks),
                tasks_done=done,
            )
        )

    tasks_out = [
        KioskTask(
            title=a.template.title if a.template else "",
            user_name=user_name.get(a.assigned_to, ""),
            is_done=(a.status == AssignmentStatus.COMPLETED),
            is_bonus=bool(a.template.is_bonus) if a.template else False,
        )
        for a in assignments
    ]

    # Events
    evts_q = (
        select(CalendarEvent)
        .where(
            and_(
                CalendarEvent.family_id == family_id,
                CalendarEvent.start_ts >= today_start,
                CalendarEvent.start_ts < day_after,
            )
        )
        .order_by(CalendarEvent.start_ts.asc())
    )
    evts = list((await db.execute(evts_q)).scalars().all())
    events_today: List[KioskEvent] = []
    events_tomorrow: List[KioskEvent] = []
    for e in evts:
        bucket = events_today if e.start_ts < tomorrow_start else events_tomorrow
        bucket.append(
            KioskEvent(
                title=e.title,
                start_ts=e.start_ts,
                location=e.location,
                all_day=bool(e.all_day),
            )
        )

    # Shopping lists with pending counts
    lists_q = (
        select(ShoppingList)
        .where(
            and_(
                ShoppingList.family_id == family_id,
                ShoppingList.is_archived.is_(False),
            )
        )
        .order_by(ShoppingList.created_at.desc())
        .limit(5)
    )
    lists = list((await db.execute(lists_q)).scalars().all())
    shopping_out: List[KioskShoppingList] = []
    if lists:
        list_ids = [l.id for l in lists]
        counts_q = (
            select(
                ShoppingItem.list_id,
                func.count()
                .filter(ShoppingItem.is_checked.is_(False))
                .label("pending"),
            )
            .where(ShoppingItem.list_id.in_(list_ids))
            .group_by(ShoppingItem.list_id)
        )
        pending = {row[0]: int(row[1] or 0) for row in (await db.execute(counts_q)).all()}
        for l in lists:
            shopping_out.append(
                KioskShoppingList(name=l.name, pending=pending.get(l.id, 0))
            )

    await db.commit()

    return KioskSnapshot(
        family_name=fam_name,
        now_utc=datetime.now(timezone.utc),
        members=members_out,
        tasks=tasks_out,
        events_today=events_today,
        events_tomorrow=events_tomorrow,
        shopping=shopping_out,
    )
