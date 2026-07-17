"""Calendar event service (W2.1).

Family-scoped CRUD with optional date-range query.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.calendar_event import CalendarEvent
from app.schemas.calendar_event import (
    CalendarEventCreate,
    CalendarEventUpdate,
)


def _expand_recurrence(
    master: CalendarEvent,
    start: Optional[datetime],
    end: Optional[datetime],
    cap: int = 200,
) -> list[CalendarEvent]:
    """Expand master event with RRULE into virtual instances inside [start, end).

    Uses dateutil.rrule. Each virtual instance carries the master's id but a
    derived ``start_ts``/``end_ts``. Caller must treat them as read-only.
    """
    try:
        from dateutil.rrule import rrulestr
    except ImportError:
        return [master]
    try:
        rule = rrulestr(master.recurrence_rule, dtstart=master.start_ts)
    except Exception:
        return [master]

    window_start = start or master.start_ts
    # rrulestr returns infinite sets; bound by COUNT or by end window.
    window_end = end or (window_start + timedelta(days=365))
    duration = (
        (master.end_ts - master.start_ts) if master.end_ts else None
    )
    out: list[CalendarEvent] = []
    for occ in rule.between(window_start, window_end, inc=True):
        if len(out) >= cap:
            break
        # Build a lightweight detached instance; do not add to session.
        inst = CalendarEvent(
            id=uuid4(),
            family_id=master.family_id,
            title=master.title,
            description=master.description,
            location=master.location,
            start_ts=occ,
            end_ts=occ + duration if duration else None,
            all_day=master.all_day,
            attendees=master.attendees,
            color=master.color,
            source=master.source,
            source_doc_url=master.source_doc_url,
            created_by=master.created_by,
            recurrence_rule=master.recurrence_rule,
            recurrence_parent_id=master.id,
            created_at=master.created_at,
            updated_at=master.updated_at,
        )
        out.append(inst)
    return out


class CalendarService:
    @staticmethod
    async def list_events(
        db: AsyncSession,
        family_id: UUID,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[CalendarEvent]:
        """Return events in [start, end). Recurring masters are expanded
        into virtual instances; non-recurring rows pass through."""
        # Pull non-recurring events whose start_ts falls in the window.
        non_rec_q = select(CalendarEvent).where(
            and_(
                CalendarEvent.family_id == family_id,
                CalendarEvent.recurrence_rule.is_(None),
            )
        )
        if start is not None:
            non_rec_q = non_rec_q.where(CalendarEvent.start_ts >= start)
        if end is not None:
            non_rec_q = non_rec_q.where(CalendarEvent.start_ts < end)
        non_rec = list((await db.execute(non_rec_q)).scalars().all())

        # Pull all recurring masters; expand each within the window.
        # We do NOT filter by start_ts on masters — a weekly event starting
        # last year still produces occurrences in this week's window.
        rec_q = select(CalendarEvent).where(
            and_(
                CalendarEvent.family_id == family_id,
                CalendarEvent.recurrence_rule.isnot(None),
            )
        )
        masters = list((await db.execute(rec_q)).scalars().all())
        expanded: list[CalendarEvent] = []
        for m in masters:
            expanded.extend(_expand_recurrence(m, start, end))

        merged = non_rec + expanded
        merged.sort(key=lambda e: e.start_ts)
        return merged

    @staticmethod
    async def get_event(
        db: AsyncSession, event_id: UUID, family_id: UUID
    ) -> CalendarEvent:
        q = select(CalendarEvent).where(
            and_(
                CalendarEvent.id == event_id,
                CalendarEvent.family_id == family_id,
            )
        )
        evt = (await db.execute(q)).scalar_one_or_none()
        if not evt:
            raise NotFoundException("Calendar event not found")
        return evt

    @staticmethod
    async def create_event(
        db: AsyncSession,
        data: CalendarEventCreate,
        family_id: UUID,
        created_by: UUID,
    ) -> CalendarEvent:
        if data.end_ts is not None and data.end_ts < data.start_ts:
            raise ValidationException("end_ts cannot be before start_ts")
        # Validate RRULE early so we don't store garbage.
        if data.recurrence_rule:
            try:
                from dateutil.rrule import rrulestr
                rrulestr(data.recurrence_rule, dtstart=data.start_ts)
            except ImportError:
                pass
            except Exception as exc:
                raise ValidationException(f"Invalid recurrence_rule: {exc}")

        evt = CalendarEvent(
            family_id=family_id,
            title=data.title,
            description=data.description,
            location=data.location,
            start_ts=data.start_ts,
            end_ts=data.end_ts,
            all_day=data.all_day,
            attendees=[str(u) for u in data.attendees] if data.attendees else None,
            color=data.color,
            source=data.source,
            source_doc_url=data.source_doc_url,
            recurrence_rule=data.recurrence_rule,
            created_by=created_by,
        )
        db.add(evt)
        await db.commit()
        await db.refresh(evt)

        # W5.5: notify family when AI-imported, so kids see the calendar
        # gained new entries from the school flyer scan.
        if evt.source in ("ocr_flyer", "school_import"):
            try:
                from app.services.notification_service import NotificationService
                when = evt.start_ts.strftime("%a %b %d, %H:%M")
                await NotificationService.create_localized(
                    db,
                    family_id=family_id,
                    key="calendar_event_added",
                    user_id=None,
                    params={"title": evt.title, "when": when},
                    link="/calendar",
                    push=False,  # family-wide; per-user push handled separately
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "calendar event notification failed"
                )
        return evt

    @staticmethod
    async def update_event(
        db: AsyncSession,
        event_id: UUID,
        data: CalendarEventUpdate,
        family_id: UUID,
    ) -> CalendarEvent:
        evt = await CalendarService.get_event(db, event_id, family_id)
        update = data.model_dump(exclude_unset=True)
        if "attendees" in update:
            ats = update.pop("attendees")
            evt.attendees = [str(u) for u in ats] if ats else None
        for k, v in update.items():
            setattr(evt, k, v)
        if evt.end_ts is not None and evt.end_ts < evt.start_ts:
            raise ValidationException("end_ts cannot be before start_ts")
        await db.commit()
        await db.refresh(evt)
        return evt

    @staticmethod
    async def delete_event(
        db: AsyncSession, event_id: UUID, family_id: UUID
    ) -> None:
        evt = await CalendarService.get_event(db, event_id, family_id)
        await db.delete(evt)
        await db.commit()
