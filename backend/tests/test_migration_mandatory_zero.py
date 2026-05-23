"""Assert migration outcomes are durable."""
import pytest
from sqlalchemy import select, func, text

from app.models.task_template import TaskTemplate


@pytest.mark.asyncio
async def test_all_mandatory_templates_have_zero_points(db_session):
    bad = await db_session.scalar(
        select(func.count())
        .select_from(TaskTemplate)
        .where(
            TaskTemplate.is_bonus.is_(False),
            TaskTemplate.points != 0,
        )
    )
    assert bad == 0


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


@pytest.mark.asyncio
async def test_check_constraint_rejects_nonzero_mandatory_insert(db_session, test_family):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="chk_mandatory_zero_points|check constraint"):
        await db_session.execute(
            text(
                "INSERT INTO task_templates "
                "(id, title, points, interval_days, assignment_type, is_bonus, "
                " is_active, family_id, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'bad', 5, 1, 'auto', false, true, "
                " :fid, NOW(), NOW())"
            ),
            {"fid": str(test_family.id)},
        )
        await db_session.commit()
    await db_session.rollback()
