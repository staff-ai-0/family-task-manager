"""Calendar routes (W2.1)."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.exceptions import ValidationError
from app.core.premium import require_feature
from app.core.rate_limiter import limiter, AI_LIMIT
from app.core.type_utils import to_uuid_required
from app.core.upload_validation import read_upload_capped
from app.models import User
from app.schemas.calendar_event import (
    CalendarEventCreate,
    CalendarEventResponse,
    CalendarEventUpdate,
)
from app.services.calendar_scanner_service import scan_calendar_document
from app.services.calendar_service import CalendarService


ALLOWED_SCAN_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/pdf",
}
MAX_SCAN_BYTES = 8 * 1024 * 1024  # 8 MB


router = APIRouter()


@router.get("/events", response_model=List[CalendarEventResponse])
async def list_events(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    events = await CalendarService.list_events(
        db, to_uuid_required(current_user.family_id), start, end
    )
    return events


@router.post(
    "/events",
    response_model=CalendarEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_event(
    data: CalendarEventCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    evt = await CalendarService.create_event(
        db,
        data,
        to_uuid_required(current_user.family_id),
        to_uuid_required(current_user.id),
    )
    return evt


@router.get("/events/{event_id}", response_model=CalendarEventResponse)
async def get_event(
    event_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await CalendarService.get_event(
        db, event_id, to_uuid_required(current_user.family_id)
    )


@router.patch("/events/{event_id}", response_model=CalendarEventResponse)
async def update_event(
    event_id: UUID,
    data: CalendarEventUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await CalendarService.update_event(
        db, event_id, data, to_uuid_required(current_user.family_id)
    )


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    await CalendarService.delete_event(
        db, event_id, to_uuid_required(current_user.family_id)
    )
    return None


@router.get("/feed.ics")
async def ical_feed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """iCal subscription feed. Returns next 6 months of family events.

    Recurring events emit a single VEVENT with RRULE so calendar clients
    expand them locally.
    """
    from fastapi.responses import PlainTextResponse
    from datetime import datetime as dt, timedelta as td, timezone as tz

    now = dt.now(tz.utc)
    end = now + td(days=180)

    # Fetch raw rows (not expanded — clients handle RRULE themselves).
    from sqlalchemy import select as sa_select
    from app.models.calendar_event import CalendarEvent
    q = sa_select(CalendarEvent).where(
        CalendarEvent.family_id == to_uuid_required(current_user.family_id)
    )
    rows = list((await db.execute(q)).scalars().all())

    def _fmt(t: dt) -> str:
        return t.astimezone(tz.utc).strftime("%Y%m%dT%H%M%SZ")

    def _escape(s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Family Task Manager//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for e in rows:
        # Skip non-recurring events older than 30 days to keep feed small.
        if not e.recurrence_rule and e.start_ts < now - td(days=30):
            continue
        # Skip non-recurring events more than 6 months out.
        if not e.recurrence_rule and e.start_ts > end:
            continue
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{e.id}@family-task-manager")
        lines.append(f"DTSTAMP:{_fmt(now)}")
        lines.append(f"DTSTART:{_fmt(e.start_ts)}")
        if e.end_ts:
            lines.append(f"DTEND:{_fmt(e.end_ts)}")
        else:
            lines.append(f"DTEND:{_fmt(e.start_ts + td(hours=1))}")
        lines.append(f"SUMMARY:{_escape(e.title)}")
        if e.description:
            lines.append(f"DESCRIPTION:{_escape(e.description)}")
        if e.location:
            lines.append(f"LOCATION:{_escape(e.location)}")
        if e.recurrence_rule:
            lines.append(f"RRULE:{e.recurrence_rule}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    return PlainTextResponse(
        "\r\n".join(lines) + "\r\n",
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="family.ics"'},
    )


class ScannedEventOut(BaseModel):
    title: str
    start_ts: datetime
    end_ts: Optional[datetime] = None
    all_day: bool = False
    location: Optional[str] = None
    description: Optional[str] = None


class ScanCalendarResponse(BaseModel):
    doc_type: str
    confidence: float
    events: List[ScannedEventOut]


@router.post("/scan-document", response_model=ScanCalendarResponse)
@limiter.limit(AI_LIMIT)
async def scan_document(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Extract events from a school flyer, sport schedule, invitation, or
    permission slip. Returns the parsed events for the caller to review and
    confirm via POST /events. No persistence happens here.
    """
    # Plan gate BEFORE touching the upload: this endpoint burns LLM tokens,
    # so free-tier families (ai_features=False) are blocked up front —
    # same machinery as budget scan-receipt.
    await require_feature("ai_features", db, current_user)
    if file.content_type not in ALLOWED_SCAN_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}",
        )
    # Stream with a hard cap so an oversized body is aborted mid-read rather
    # than fully buffered into memory before the size check.
    payload = await read_upload_capped(file, MAX_SCAN_BYTES)
    if not payload:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        result = await scan_calendar_document(payload, file.content_type)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return ScanCalendarResponse(
        doc_type=result.doc_type,
        confidence=result.confidence,
        events=[
            ScannedEventOut(
                title=e.title,
                start_ts=e.start_ts,
                end_ts=e.end_ts,
                all_day=e.all_day,
                location=e.location,
                description=e.description,
            )
            for e in result.events
        ],
    )
