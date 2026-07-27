"""The database must refuse invalid rows even when no route validates them.

Four CHECK constraints and two partial unique indexes existed in the deployed
schema but not in the ORM models. Because conftest builds the test schema from
`Base.metadata.create_all`, the whole suite ran without them — so nothing here
could ever catch a write that production would reject.

That gap was reachable: `app/mcp/schemas/gigs.py` declares bare `points: int`
and `difficulty: int` (the HTTP route in `api/routes/gigs.py` bounds both), so a
Jarvis MCP tool call could create an offering with points=-500, difficulty=99
and fail only in production.

These tests exercise the constraints directly, which is the point: they must
hold for ANY writer, not just for the paths that happen to validate first.
`scripts/check_schema_parity.py` (wired into CI) stops the two schemas drifting
apart again.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.gig import GigOffering
from app.models.task_template import TaskTemplate


class TestGigOfferingConstraints:
    async def test_points_must_be_positive(self, db, family):
        db.add(GigOffering(
            family_id=family.id,
            title="Bad gig", points=-500, difficulty=1,
        ))
        with pytest.raises(IntegrityError, match="chk_gig_points_positive"):
            await db.commit()
        await db.rollback()

    async def test_points_may_not_be_zero(self, db, family):
        db.add(GigOffering(
            family_id=family.id,
            title="Free gig", points=0, difficulty=1,
        ))
        with pytest.raises(IntegrityError, match="chk_gig_points_positive"):
            await db.commit()
        await db.rollback()

    @pytest.mark.parametrize("difficulty", [0, 4, 99])
    async def test_difficulty_must_be_1_to_3(self, db, family, difficulty):
        db.add(GigOffering(
            family_id=family.id,
            title="Odd gig", points=10, difficulty=difficulty,
        ))
        with pytest.raises(IntegrityError, match="chk_gig_difficulty_range"):
            await db.commit()
        await db.rollback()

    @pytest.mark.parametrize("difficulty", [1, 2, 3])
    async def test_valid_difficulty_is_accepted(self, db, family, difficulty):
        offering = GigOffering(
            family_id=family.id,
            title="Fine gig", points=10, difficulty=difficulty,
        )
        db.add(offering)
        await db.commit()
        assert offering.id is not None


class TestTaskTemplateConstraints:
    async def test_gig_mode_must_be_a_known_value(self, db, family):
        db.add(TaskTemplate(
            family_id=family.id, title="Bad mode",
            effort_level=1, gig_mode="whatever",
        ))
        with pytest.raises(IntegrityError, match="chk_gig_mode_valid"):
            await db.commit()
        await db.rollback()

    @pytest.mark.parametrize("days", [0, 31])
    async def test_late_duration_must_be_1_to_30(self, db, family, days):
        db.add(TaskTemplate(
            family_id=family.id, title="Bad late window",
            effort_level=1, late_duration_days=days,
        ))
        with pytest.raises(IntegrityError, match="chk_late_duration_positive"):
            await db.commit()
        await db.rollback()


class TestBudgetNameUniqueness:
    async def test_group_name_is_unique_per_family(self, db, family):
        from app.schemas.budget import CategoryGroupCreate
        from app.services.budget.category_service import CategoryGroupService

        await CategoryGroupService.create(
            db, family.id, CategoryGroupCreate(name="Mandado", is_income=False)
        )
        with pytest.raises(IntegrityError):
            await CategoryGroupService.create(
                db, family.id, CategoryGroupCreate(name="Mandado", is_income=False)
            )
        await db.rollback()

    async def test_the_same_group_name_is_fine_in_another_family(
        self, db, family, other_family
    ):
        """The index is scoped per family, not global."""
        from app.schemas.budget import CategoryGroupCreate
        from app.services.budget.category_service import CategoryGroupService

        await CategoryGroupService.create(
            db, family.id, CategoryGroupCreate(name="Mandado", is_income=False)
        )
        theirs = await CategoryGroupService.create(
            db, other_family.id, CategoryGroupCreate(name="Mandado", is_income=False)
        )
        assert theirs.id is not None

    async def test_a_recycled_name_becomes_reusable(self, db, family):
        """The index is partial (WHERE deleted_at IS NULL) precisely so a
        soft-deleted category does not reserve its name forever."""
        from datetime import datetime, timezone

        from app.schemas.budget import CategoryCreate, CategoryGroupCreate
        from app.services.budget.category_service import (
            CategoryGroupService,
            CategoryService,
        )

        group = await CategoryGroupService.create(
            db, family.id, CategoryGroupCreate(name="Casa", is_income=False)
        )
        first = await CategoryService.create(
            db, family.id, CategoryCreate(name="Super", group_id=group.id)
        )

        first.deleted_at = datetime.now(timezone.utc)
        await db.commit()

        again = await CategoryService.create(
            db, family.id, CategoryCreate(name="Super", group_id=group.id)
        )
        assert again.id != first.id
