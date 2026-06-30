"""Default-gig seeding for new families.

NOTE: the old "mandatory tasks must have zero points" rule (Pydantic validator
+ chk_mandatory_zero_points CHECK constraint) was intentionally removed in the
two-currency-economy change — mandatory chores now award privilege points. The
tests that asserted that rule were deleted; see
docs/superpowers/specs/2026-06-30-two-currency-economy-design.md.
"""
import pytest
from sqlalchemy import select, func

from app.models.task_template import TaskTemplate


@pytest.mark.asyncio
async def test_new_family_gets_default_gigs(db_session):
    from uuid import uuid4
    from app.services.family_service import FamilyService
    from app.schemas.family import FamilyCreate

    family = await FamilyService.create_family(
        db_session,
        FamilyCreate(name="Brand New Fam"),
        created_by=uuid4(),
    )

    count = await db_session.scalar(
        select(func.count())
        .select_from(TaskTemplate)
        .where(
            TaskTemplate.family_id == family.id,
            TaskTemplate.is_bonus.is_(True),
        )
    )
    assert count == len(FamilyService.DEFAULT_GIGS)
