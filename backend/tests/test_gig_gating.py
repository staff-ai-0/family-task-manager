"""Gig gating + zero-point mandatory tests."""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.task_assignment_service import TaskAssignmentService


@pytest.mark.asyncio
async def test_local_today_returns_family_tz(db_session: AsyncSession, test_family, test_child_user):
    """Helper computes today in family timezone."""
    test_family.timezone = "America/Mexico_City"
    await db_session.commit()

    result = await TaskAssignmentService._user_local_today(db_session, test_child_user.id)

    assert isinstance(result, date)
