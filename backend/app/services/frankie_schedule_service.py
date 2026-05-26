"""Frankie schedule service (W9.1).

Stores recurring prompts + handles cron tick that fires due ones. Uses
APScheduler's CronTrigger to compute next_run_at from the stored
cron_expr; the actual ticking is done by the lifespan scheduler in
main.py calling ``sweep_due()`` every 5 minutes.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.frankie_schedule import FrankieSchedule, VALID_CHANNELS


def _translate_dow_linux_to_apscheduler(field: str) -> str:
    """Translate cron day-of-week field from Linux (0=Sun) to APScheduler (0=Mon).

    Handles digits, ranges (1-5), lists (1,3,5), step (*/2), wildcard, and
    day-name aliases (sun, mon, ...). APScheduler accepts day names directly
    so this only rewrites bare integers.
    """
    if not field or field == "*" or "/" in field and field.startswith("*/"):
        return field

    def _digit_to_apsched(d: str) -> str:
        try:
            n = int(d)
        except ValueError:
            return d  # leave alpha day-name alone
        # Linux: 0=Sun, 1=Mon, ..., 6=Sat, 7=Sun
        # APScheduler: 0=Mon, 1=Tue, ..., 6=Sun
        if n in (0, 7):
            return "6"
        return str(n - 1)

    parts = []
    for chunk in field.split(","):
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            parts.append(f"{_digit_to_apsched(lo)}-{_digit_to_apsched(hi)}")
        else:
            parts.append(_digit_to_apsched(chunk))
    return ",".join(parts)


def _parse_cron(expr: str) -> CronTrigger:
    """Parse 5-field standard Linux cron expression.

    User-facing day-of-week follows Linux convention (0=Sun, 1=Mon, ...,
    6=Sat, 7=Sun). We translate to APScheduler's 0=Mon convention here
    so '0 9 * * 1' fires on Monday as users expect.
    """
    expr = (expr or "").strip()
    parts = expr.split()
    if len(parts) != 5:
        raise ValidationException(
            "cron_expr must be 5 fields (minute hour day month dow)"
        )
    minute, hour, day, month, dow = parts
    dow = _translate_dow_linux_to_apscheduler(dow)
    try:
        return CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
        )
    except Exception as exc:
        raise ValidationException(f"Invalid cron_expr: {exc}")


def _next_fire(trigger: CronTrigger, after: datetime) -> datetime:
    nxt = trigger.get_next_fire_time(None, after)
    if nxt is None:
        # Trigger never fires; push 1 year out so we don't busy-loop.
        from datetime import timedelta
        return after + timedelta(days=365)
    return nxt


class FrankieScheduleService:
    @staticmethod
    async def create(
        db: AsyncSession,
        family_id: UUID,
        created_by: UUID,
        *,
        name: str,
        prompt: str,
        cron_expr: str,
        channel: str = "notification",
    ) -> FrankieSchedule:
        if channel not in VALID_CHANNELS:
            raise ValidationException(f"channel must be one of {sorted(VALID_CHANNELS)}")
        if not name.strip() or not prompt.strip():
            raise ValidationException("name and prompt required")
        trigger = _parse_cron(cron_expr)
        now = datetime.now(timezone.utc)
        nxt = _next_fire(trigger, now)
        s = FrankieSchedule(
            family_id=family_id,
            created_by=created_by,
            name=name.strip()[:120],
            prompt=prompt.strip(),
            cron_expr=cron_expr.strip(),
            channel=channel,
            is_active=True,
            next_run_at=nxt,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s

    @staticmethod
    async def list(
        db: AsyncSession, family_id: UUID
    ) -> List[FrankieSchedule]:
        q = (
            select(FrankieSchedule)
            .where(FrankieSchedule.family_id == family_id)
            .order_by(FrankieSchedule.created_at.desc())
        )
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def delete(
        db: AsyncSession, schedule_id: UUID, family_id: UUID
    ) -> None:
        q = select(FrankieSchedule).where(
            and_(
                FrankieSchedule.id == schedule_id,
                FrankieSchedule.family_id == family_id,
            )
        )
        s = (await db.execute(q)).scalar_one_or_none()
        if not s:
            raise NotFoundException("Schedule not found")
        await db.delete(s)
        await db.commit()

    @staticmethod
    async def toggle(
        db: AsyncSession, schedule_id: UUID, family_id: UUID
    ) -> FrankieSchedule:
        q = select(FrankieSchedule).where(
            and_(
                FrankieSchedule.id == schedule_id,
                FrankieSchedule.family_id == family_id,
            )
        )
        s = (await db.execute(q)).scalar_one_or_none()
        if not s:
            raise NotFoundException("Schedule not found")
        s.is_active = not s.is_active
        if s.is_active and s.next_run_at is None:
            s.next_run_at = _next_fire(
                _parse_cron(s.cron_expr), datetime.now(timezone.utc)
            )
        await db.commit()
        await db.refresh(s)
        return s

    @staticmethod
    async def sweep_due(db: AsyncSession) -> int:
        """Fire every schedule whose next_run_at <= now. Returns count fired.

        Each fire calls FrankieService.chat with the stored prompt as the
        creator's message, then delivers the reply to the chosen channel.
        Failures are logged and don't stop other schedules in the same sweep.
        """
        from app.services.frankie_service import FrankieService
        from app.services.notification_service import NotificationService
        from app.services.family_chat_service import FamilyChatService
        from app.models.notification import NotificationType
        from app.core.exceptions import ValidationError

        now = datetime.now(timezone.utc)
        q = (
            select(FrankieSchedule)
            .where(
                and_(
                    FrankieSchedule.is_active.is_(True),
                    FrankieSchedule.next_run_at.isnot(None),
                    FrankieSchedule.next_run_at <= now,
                )
            )
            .limit(50)
        )
        due = list((await db.execute(q)).scalars().all())
        fired = 0
        for s in due:
            try:
                result = await FrankieService.chat(
                    db,
                    family_id=s.family_id,
                    user_id=s.created_by or s.family_id,  # fallback
                    message=s.prompt,
                )
                reply = result.get("reply", "")[:1000]
                if s.channel == "chat" and s.created_by:
                    await FamilyChatService.post_message(
                        db, s.family_id, s.created_by,
                        f"🤖 Jarvis ({s.name}): {reply}",
                    )
                else:
                    await NotificationService.create(
                        db,
                        family_id=s.family_id,
                        user_id=s.created_by,
                        type=NotificationType.SHOPPING_ITEM_ADDED,
                        title=f"🤖 {s.name}",
                        body=reply[:200],
                        link="/parent/frankie",
                    )
                fired += 1
            except ValidationError:
                pass
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "Jarvis schedule %s failed", s.id
                )
            # advance regardless of success
            s.last_run_at = now
            try:
                s.next_run_at = _next_fire(_parse_cron(s.cron_expr), now)
            except Exception:
                s.is_active = False
        await db.commit()
        return fired
