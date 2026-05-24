"""Calendar routes (W2.1)."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.exceptions import ValidationError
from app.core.type_utils import to_uuid_required
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
async def scan_document(
    file: UploadFile = File(...),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Extract events from a school flyer, sport schedule, invitation, or
    permission slip. Returns the parsed events for the caller to review and
    confirm via POST /events. No persistence happens here.
    """
    if file.content_type not in ALLOWED_SCAN_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}",
        )
    payload = await file.read()
    if len(payload) > MAX_SCAN_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
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
