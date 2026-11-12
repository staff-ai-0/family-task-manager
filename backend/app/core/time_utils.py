"""Timezone-safe clock helpers.

Rule (enforced by ruff DTZ in CI): no naive datetimes, no host-local dates.
Production containers run UTC, so `date.today()` happened to equal the UTC
date there — but any non-UTC host (local dev, future deployments) silently
shifts a "today" computed that way. Family-local calendar logic must go
through TaskAssignmentService._family_local_today (family timezone); pure
bookkeeping dates use these UTC helpers.
"""
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """Timezone-aware current instant (UTC)."""
    return datetime.now(timezone.utc)


def utc_today() -> date:
    """Today's date on the UTC clock (host-timezone independent)."""
    return datetime.now(timezone.utc).date()


def safe_zoneinfo(tz_name: Optional[str]) -> ZoneInfo:
    """ZoneInfo for a stored family timezone; UTC when unset or unknown."""
    try:
        return ZoneInfo(tz_name or "UTC")
    except Exception:
        return ZoneInfo("UTC")
