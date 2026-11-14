"""Rules acceptance: what each member has agreed to. Logic only; routes are HTTP."""
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AnnounceTooSoonException,
    EarlyBirdOffException,
    NotFoundException,
    StaleRulesVersionException,
)
from app.models.family import Family
from app.models.notification import Notification, NotificationType
from app.models.rules_acceptance import RulesAcceptance
from app.models.user import APPROVAL_APPROVED, User
from app.services.early_bird_rules import LADDER_BONUS_TIERS, LADDER_FLOOR_PCT


def _hhmm(t: time) -> str:
    return t.strftime("%H:%M")


class RulesService:
    @staticmethod
    def _version(family: Family) -> int:
        return int(family.rules_version or 1)

    @staticmethod
    def snapshot(family: Family) -> dict:
        return {
            "version": RulesService._version(family),
            "deadline": _hhmm(family.early_bird_deadline),
            "cutoff": _hhmm(family.chore_cutoff),
            "grab_end": _hhmm(family.grab_window_end),
            "alarm_1": _hhmm(family.teen_alarm_1),
            "alarm_2": _hhmm(family.teen_alarm_2),
            "streak_cents": int(family.early_bird_streak_cents),
            "chore_bonus_pct": int(family.early_bird_bonus_pct),
            "floor_pct": int(LADDER_FLOOR_PCT),
            "bonus_tiers": [
                {"early_pct": int(e), "bonus_pct": int(b)} for e, b in LADDER_BONUS_TIERS
            ],
        }

    @staticmethod
    async def _family(db: AsyncSession, family_id) -> Family:
        fam = (await db.execute(select(Family).where(Family.id == family_id))).scalar_one_or_none()
        if fam is None:
            raise NotFoundException("family_not_found")
        return fam

    @staticmethod
    async def _existing(db: AsyncSession, user: User, version: int) -> Optional[RulesAcceptance]:
        return (await db.execute(
            select(RulesAcceptance).where(
                RulesAcceptance.family_id == user.family_id,
                RulesAcceptance.user_id == user.id,
                RulesAcceptance.rules_version == version,
            )
        )).scalar_one_or_none()

    @staticmethod
    async def status(db: AsyncSession, user: User) -> dict:
        fam = await RulesService._family(db, user.family_id)
        version = RulesService._version(fam)
        row = await RulesService._existing(db, user, version)
        return {
            "required": bool(fam.early_bird_enabled) and row is None,
            "version": version,
            "accepted_at": row.accepted_at if row else None,
            "rules": RulesService.snapshot(fam),
        }

    @staticmethod
    async def accept(db: AsyncSession, user: User, version: int) -> RulesAcceptance:
        fam = await RulesService._family(db, user.family_id)
        if version != RulesService._version(fam):
            raise StaleRulesVersionException("stale_version")
        # Upsert-safe: a double tap or concurrent request never makes two rows.
        # The key includes family_id: an invitation can move an account to
        # another family, whose v1 is a different agreement.
        await db.execute(
            pg_insert(RulesAcceptance)
            .values(
                family_id=user.family_id,
                user_id=user.id,
                rules_version=version,
                snapshot=RulesService.snapshot(fam),
            )
            .on_conflict_do_nothing(constraint="uq_rules_acceptances_family_user_version")
        )
        await db.commit()
        return await RulesService._existing(db, user, version)

    @staticmethod
    async def acceptances(db: AsyncSession, family_id) -> list[dict]:
        fam = await RulesService._family(db, family_id)
        # The rules are Early Bird's: with it off nobody is asked, so the
        # parent card has nothing to report (it stays hidden on an empty list).
        if not fam.early_bird_enabled:
            return []
        version = RulesService._version(fam)
        users = (await db.execute(
            select(User).where(
                User.family_id == family_id,
                User.is_active.is_(True),
                User.approval_status == APPROVAL_APPROVED,
            ).order_by(User.name)
        )).scalars().all()
        accepted = {
            r.user_id: r.accepted_at
            for r in (await db.execute(
                select(RulesAcceptance).where(
                    RulesAcceptance.family_id == family_id,
                    RulesAcceptance.rules_version == version,
                )
            )).scalars()
        }
        return [
            {
                "user_id": u.id,
                "name": u.name,
                "role": u.role.value,
                "accepted_at": accepted.get(u.id),
            }
            for u in users
        ]

    @staticmethod
    async def announce(db: AsyncSession, family_id, *, force: bool = False) -> int:
        """Tell every active, approved member the rules need their acceptance.
        The notification rows double as the send record, so the hourly cap
        needs no column. Returns how many members were notified."""
        # Local import: notification_service pulls in push machinery.
        from app.services.notification_service import NotificationService

        fam = await RulesService._family(db, family_id)
        if not fam.early_bird_enabled:
            raise EarlyBirdOffException("early_bird_off")
        if not force:
            since = datetime.now(timezone.utc) - timedelta(hours=1)
            recent = (await db.execute(
                select(Notification.id).where(
                    Notification.family_id == family_id,
                    Notification.type == NotificationType.RULES_UPDATE,
                    Notification.created_at > since,
                ).limit(1)
            )).first()
            if recent is not None:
                raise AnnounceTooSoonException("announce_too_soon")
        members = (await db.execute(
            select(User.id).where(
                User.family_id == family_id,
                User.is_active.is_(True),
                User.approval_status == APPROVAL_APPROVED,
            )
        )).scalars().all()
        for uid in members:
            await NotificationService.create_localized(
                db, family_id, "rules_update",
                user_id=uid, link="/dashboard?rules=1", push_tag="ftm-rules-update",
            )
        return len(members)
