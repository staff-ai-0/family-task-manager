"""Kiosk business logic (W3.3, P1-KIOSK).

- Device provisioning/revocation (parent only).
- Member prefs: kiosk color + 4-digit PIN (parent only).
- Snapshot + per-kid PIN view (token-gated, no user auth — the device
  token itself is the auth boundary for those two).

Raises `fastapi.HTTPException` directly rather than the app's domain
exceptions (`app.core.exceptions`) — matches the precedent already set by
several other services (bank_service, transfer_service, etc.) rather than
introducing a third exception convention in this pass.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import User
from app.models.calendar_event import CalendarEvent
from app.models.family import Family
from app.models.gig import GigClaim, GigClaimStatus, GigOffering
from app.models.kiosk_device import KioskDevice
from app.models.point_transaction import PointTransaction
from app.models.shopping import ShoppingItem, ShoppingList
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.user import UserRole
from app.schemas.kiosk import (
    KidChore,
    KidView,
    KioskBoss,
    KioskEvent,
    KioskLeaderboardEntry,
    KioskMember,
    KioskShoppingList,
    KioskSnapshot,
    KioskTask,
    MemberPrefOut,
)
from app.services.member_prefs_service import (
    MEMBER_COLORS,
    PIN_MAX_FAILURES,
    MemberPrefsService,
    color_hex,
    resolve_color_name,
)


def _family_timezone(family: Optional[Family]) -> ZoneInfo:
    tz_name = (family.timezone if family and family.timezone else None) or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _role_value(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


class KioskService:
    # ─── Device management ───────────────────────────────────────────

    @staticmethod
    async def list_devices(db: AsyncSession, family_id: UUID) -> List[KioskDevice]:
        q = (
            select(KioskDevice)
            .where(KioskDevice.family_id == family_id)
            .order_by(KioskDevice.created_at.desc())
        )
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def create_device(
        db: AsyncSession, family_id: UUID, name: str, created_by: UUID
    ) -> KioskDevice:
        token = secrets.token_urlsafe(32)[:64]
        device = KioskDevice(
            family_id=family_id,
            name=name,
            token=token,
            created_by=created_by,
        )
        db.add(device)
        await db.commit()
        await db.refresh(device)
        return device

    @staticmethod
    async def delete_device(db: AsyncSession, family_id: UUID, device_id: UUID) -> None:
        q = select(KioskDevice).where(
            and_(KioskDevice.id == device_id, KioskDevice.family_id == family_id)
        )
        dev = (await db.execute(q)).scalar_one_or_none()
        if not dev:
            raise HTTPException(status_code=404, detail="Device not found")
        await db.delete(dev)
        await db.commit()

    # ─── Member prefs: color + kiosk PIN ─────────────────────────────

    @staticmethod
    async def get_family_member_or_404(
        db: AsyncSession, family_id: UUID, user_id: UUID
    ) -> User:
        q = select(User).where(and_(User.id == user_id, User.family_id == family_id))
        member = (await db.execute(q)).scalar_one_or_none()
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        return member

    @staticmethod
    async def list_member_prefs(
        db: AsyncSession, family_id: UUID
    ) -> List[MemberPrefOut]:
        users_q = (
            select(User)
            .where(and_(User.family_id == family_id, User.is_active.is_(True)))
            .order_by(User.created_at.asc())
        )
        users = list((await db.execute(users_q)).scalars().all())
        prefs = await MemberPrefsService.get_family_prefs(family_id)
        out: List[MemberPrefOut] = []
        for u in users:
            entry = prefs.get(str(u.id)) or {}
            name = resolve_color_name(u.id, entry)
            out.append(
                MemberPrefOut(
                    user_id=u.id,
                    name=u.name,
                    role=_role_value(u),
                    color=name,
                    color_hex=color_hex(name),
                    has_pin=bool(entry.get("pin_hash")),
                )
            )
        return out

    @staticmethod
    async def update_member_prefs(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        color: Optional[str],
        pin: Optional[str],
    ) -> MemberPrefOut:
        member = await KioskService.get_family_member_or_404(db, family_id, user_id)

        if color is not None and color not in MEMBER_COLORS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown color '{color}'. Valid: {sorted(MEMBER_COLORS)}",
            )
        if pin is not None and pin != "" and not re.fullmatch(r"\d{4}", pin):
            raise HTTPException(status_code=400, detail="PIN must be exactly 4 digits")

        entry = await MemberPrefsService.update_member_prefs(
            family_id, user_id, color=color, pin=pin
        )
        name = resolve_color_name(user_id, entry)
        return MemberPrefOut(
            user_id=member.id,
            name=member.name,
            role=_role_value(member),
            color=name,
            color_hex=color_hex(name),
            has_pin=bool(entry.get("pin_hash")),
        )

    # ─── Per-kid PIN view (token-gated, no user auth) ────────────────

    @staticmethod
    async def resolve_pin_view(
        db: AsyncSession, token: str, user_id: UUID, pin: str
    ) -> KidView:
        """Kid taps their avatar on the kiosk → 4-digit PIN → their own view.

        The kiosk device token is the outer gate (same trust as the
        snapshot); the PIN only scopes WHICH member's detail shows on the
        shared screen. Throttled per (device, member) against PIN guessing
        between siblings.
        """
        q = select(KioskDevice).where(KioskDevice.token == token)
        device = (await db.execute(q)).scalar_one_or_none()
        if not device or not device.is_active:
            raise HTTPException(status_code=401, detail="Invalid kiosk token")

        family_id = device.family_id
        member = await KioskService.get_family_member_or_404(db, family_id, user_id)
        if not member.is_active:
            raise HTTPException(status_code=404, detail="Member not found")

        fails = await MemberPrefsService.pin_failures(device.id, member.id)
        if fails >= PIN_MAX_FAILURES:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again in a few minutes.",
            )

        verdict = await MemberPrefsService.verify_member_pin(family_id, member.id, pin)
        if verdict is None:
            raise HTTPException(status_code=403, detail="PIN not set")
        if verdict is False:
            await MemberPrefsService.record_pin_failure(device.id, member.id)
            raise HTTPException(status_code=403, detail="Wrong PIN")
        await MemberPrefsService.clear_pin_failures(device.id, member.id)

        # Today's chores for this member (family timezone).
        family = await db.get(Family, family_id)
        if family is not None and family.deleted_at is not None:
            raise HTTPException(status_code=401, detail="Account closed")
        tz = _family_timezone(family)
        today_local = datetime.now(tz).date()

        chores_q = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_to == member.id,
                    TaskAssignment.assigned_date == today_local,
                    TaskAssignment.status != AssignmentStatus.CANCELLED,
                )
            )
        )
        assignments = list((await db.execute(chores_q)).scalars().all())
        chores = [
            KidChore(
                title=a.template.title if a.template else "",
                title_es=a.template.title_es if a.template else None,
                # Effective (effort-multiplied) points — what completing
                # actually awards, matching the other kid-facing endpoints.
                points=int(a.template.effective_points) if a.template else 0,
                is_done=(a.status == AssignmentStatus.COMPLETED),
                is_bonus=bool(a.template.is_bonus) if a.template else False,
            )
            for a in assignments
        ]

        # Prior-day mandatory blockers (same query the dashboard's
        # "Atrasadas" section uses) — without them the kiosk shows "No
        # chores today! 🎉" while gigs are actually locked.
        from app.services.task_assignment_service import TaskAssignmentService

        overdue_assignments = await TaskAssignmentService.list_open_mandatory_before(
            db, member.id, family_id, today_local
        )
        overdue_chores = [
            KidChore(
                title=a.template.title if a.template else "",
                title_es=a.template.title_es if a.template else None,
                points=int(a.template.effective_points) if a.template else 0,
                is_done=False,
                is_bonus=False,
            )
            for a in overdue_assignments
        ]

        # Gigs THIS member could actually claim right now (display-only):
        # active board offerings whose allowed_roles admit the member's role
        # (claim-service semantics: null/empty = any non-parent role), minus
        # offerings the member already holds a non-rejected claim on. A
        # sibling's claim does NOT block this member (the unique claim
        # index is per gig+user), so it doesn't reduce the count. Parents
        # can never claim gigs → always 0 for them.
        role_value = _role_value(member)
        if member.role == UserRole.PARENT:
            gigs_open = 0
        else:
            offer_rows = (
                await db.execute(
                    select(GigOffering.id, GigOffering.allowed_roles).where(
                        and_(
                            GigOffering.family_id == family_id,
                            GigOffering.is_active.is_(True),
                        )
                    )
                )
            ).all()
            my_open_claims = {
                row[0]
                for row in (
                    await db.execute(
                        select(GigClaim.gig_id).where(
                            and_(
                                GigClaim.family_id == family_id,
                                GigClaim.claimed_by == member.id,
                                GigClaim.status != GigClaimStatus.REJECTED,
                            )
                        )
                    )
                ).all()
            }
            gigs_open = sum(
                1
                for gid, roles in offer_rows
                if gid not in my_open_claims and (not roles or role_value in roles)
            )

        prefs = await MemberPrefsService.get_family_prefs(family_id)
        cname = resolve_color_name(member.id, prefs.get(str(member.id)))

        return KidView(
            user_id=member.id,
            name=member.name,
            color_hex=color_hex(cname),
            points=int(member.points or 0),
            cash_cents=int(member.cash_cents or 0),
            chores=chores,
            chores_done=sum(1 for c in chores if c.is_done),
            gigs_open=int(gigs_open),
            overdue_chores=overdue_chores,
            star_mode=bool(getattr(member, "star_mode", False)),
        )

    # ─── Snapshot (token-gated, no user auth) ────────────────────────

    @staticmethod
    async def get_snapshot(db: AsyncSession, token: str) -> KioskSnapshot:
        # Look up device by token. is_active gates access. last_seen is
        # updated so the parent UI can show whether a kiosk is alive.
        q = select(KioskDevice).where(KioskDevice.token == token)
        device = (await db.execute(q)).scalar_one_or_none()
        if not device or not device.is_active:
            raise HTTPException(status_code=401, detail="Invalid kiosk token")
        device.last_seen = datetime.now(timezone.utc)

        family_id = device.family_id
        family = await db.get(Family, family_id)
        if family is not None and family.deleted_at is not None:
            raise HTTPException(status_code=401, detail="Account closed")
        fam_name = family.name if family else ""

        # Today/tomorrow window in family timezone
        tz = _family_timezone(family)
        now_local = datetime.now(tz)
        today_local = now_local.date()
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

        # Member colors (stored override or deterministic default) + PIN flags.
        prefs = await MemberPrefsService.get_family_prefs(family_id)
        user_color = {
            u.id: color_hex(resolve_color_name(u.id, prefs.get(str(u.id))))
            for u in users
        }

        members_out: List[KioskMember] = []
        for u in users:
            u_tasks = [a for a in assignments if a.assigned_to == u.id]
            done = sum(1 for a in u_tasks if a.status == AssignmentStatus.COMPLETED)
            members_out.append(
                KioskMember(
                    id=u.id,
                    name=u.name,
                    role=_role_value(u),
                    tasks_today=len(u_tasks),
                    tasks_done=done,
                    color_hex=user_color.get(u.id, "#4FB8E6"),
                    has_pin=bool((prefs.get(str(u.id)) or {}).get("pin_hash")),
                )
            )

        tasks_out = [
            KioskTask(
                title=a.template.title if a.template else "",
                user_name=user_name.get(a.assigned_to, ""),
                user_color=user_color.get(a.assigned_to, "#4FB8E6"),
                is_done=(a.status == AssignmentStatus.COMPLETED),
                is_bonus=bool(a.template.is_bonus) if a.template else False,
            )
            for a in assignments
        ]

        # Weekly leaderboard: positive point transactions since Monday
        # 00:00 (family tz), summed per member. point_transactions has no
        # family_id, so scope through the member list we already filtered
        # by family.
        week_start_local = today_local - timedelta(days=today_local.weekday())
        week_start_dt = datetime.combine(
            week_start_local, datetime.min.time(), tzinfo=tz
        )
        user_ids = [u.id for u in users]
        week_points: dict = {}
        if user_ids:
            lb_q = (
                select(
                    PointTransaction.user_id,
                    func.sum(PointTransaction.points).label("pts"),
                )
                .where(
                    and_(
                        PointTransaction.user_id.in_(user_ids),
                        PointTransaction.points > 0,
                        PointTransaction.created_at >= week_start_dt,
                    )
                )
                .group_by(PointTransaction.user_id)
            )
            week_points = {
                row[0]: int(row[1] or 0) for row in (await db.execute(lb_q)).all()
            }
        leaderboard = sorted(
            (
                KioskLeaderboardEntry(
                    user_id=u.id,
                    name=u.name,
                    color_hex=user_color.get(u.id, "#4FB8E6"),
                    points_week=week_points.get(u.id, 0),
                )
                for u in users
                if (u.role != UserRole.PARENT) or week_points.get(u.id, 0) > 0
            ),
            key=lambda e: e.points_week,
            reverse=True,
        )

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
            list_ids = [sl.id for sl in lists]
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
            pending = {
                row[0]: int(row[1] or 0) for row in (await db.execute(counts_q)).all()
            }
            for sl in lists:
                shopping_out.append(
                    KioskShoppingList(name=sl.name, pending=pending.get(sl.id, 0))
                )

        # Cooperative weekly boss battle (same family-local week as the leaderboard).
        from app.services.family_cup_service import FamilyCupService

        boss_data = await FamilyCupService.boss_battle(db, family_id)

        await db.commit()

        return KioskSnapshot(
            family_name=fam_name,
            now_utc=datetime.now(timezone.utc),
            members=members_out,
            tasks=tasks_out,
            events_today=events_today,
            events_tomorrow=events_tomorrow,
            shopping=shopping_out,
            leaderboard=leaderboard,
            boss=KioskBoss(
                key=boss_data["key"],
                name_es=boss_data["name_es"],
                name_en=boss_data["name_en"],
                emoji=boss_data["emoji"],
                max_hp=boss_data["max_hp"],
                current_hp=boss_data["current_hp"],
                damage=boss_data["damage"],
                percent_defeated=boss_data["percent_defeated"],
                defeated=boss_data["defeated"],
                active=boss_data["active"],
            ),
            week_start=week_start_local,
        )
