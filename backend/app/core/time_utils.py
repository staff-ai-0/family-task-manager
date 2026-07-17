"""Timezone-safe clock helpers.

Rule (enforced by ruff DTZ in CI): no naive datetimes, no host-local dates.
Production containers run UTC, so `date.today()` happened to equal the UTC
date there — but any non-UTC host (local dev, future deployments) silently
shifts a "today" computed that way. Family-local calendar logic must go
through TaskAssignmentService._family_local_today (family timezone); pure
bookkeeping dates use these UTC helpers.
"""
from datetime import date, datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware current instant (UTC)."""
    return datetime.now(timezone.utc)


def utc_today() -> date:
    """Today's date on the UTC clock (host-timezone independent)."""
    return datetime.now(timezone.utc).date()
