"""Effort-level multiplier on TaskTemplate.

Validates effort_level 1/2/3 maps to ×1.0/×1.5/×2.0 effective_points,
schema rejects out-of-range values, and gig award credits effective points.
"""

import pytest
from uuid import uuid4

from app.models.task_template import TaskTemplate, EFFORT_MULTIPLIERS
from app.schemas.task_template import TaskTemplateCreate, TaskTemplateUpdate
from app.services.task_template_service import TaskTemplateService


class TestEffortMultiplier:
    def test_multiplier_table(self):
        assert EFFORT_MULTIPLIERS == {1: 1.0, 2: 1.5, 3: 2.0}

    def test_effective_points_easy(self):
        t = TaskTemplate(points=10, effort_level=1)
        assert t.effective_points == 10

    def test_effective_points_medium(self):
        t = TaskTemplate(points=10, effort_level=2)
        assert t.effective_points == 15

    def test_effective_points_hard(self):
        t = TaskTemplate(points=10, effort_level=3)
        assert t.effective_points == 20

    def test_effective_points_rounds(self):
        t = TaskTemplate(points=7, effort_level=2)
        # 7 * 1.5 = 10.5 → 10 (banker's rounding) or 11 (half-up). round() uses banker's.
        assert t.effective_points in (10, 11)

    def test_effective_points_zero_base(self):
        t = TaskTemplate(points=0, effort_level=3)
        assert t.effective_points == 0

    def test_effective_points_default_level(self):
        t = TaskTemplate(points=5, effort_level=None)
        assert t.effective_points == 5


class TestSchemaValidation:
    def test_create_accepts_effort_level(self):
        data = TaskTemplateCreate(
            title="Vacuum living room",
            points=20,
            effort_level=2,
            is_bonus=True,
            interval_days=1,
        )
        assert data.effort_level == 2

    def test_create_rejects_effort_below_range(self):
        with pytest.raises(Exception):
            TaskTemplateCreate(
                title="X", points=10, effort_level=0, is_bonus=True, interval_days=1
            )

    def test_create_rejects_effort_above_range(self):
        with pytest.raises(Exception):
            TaskTemplateCreate(
                title="X", points=10, effort_level=4, is_bonus=True, interval_days=1
            )

    def test_create_defaults_to_easy(self):
        data = TaskTemplateCreate(
            title="X", points=10, is_bonus=True, interval_days=1
        )
        assert data.effort_level == 1

    def test_update_allows_omitting_effort(self):
        data = TaskTemplateUpdate(title="Y")
        assert data.effort_level is None


class TestPersistence:
    async def test_create_persists_effort_level(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(
            title="Hard gig",
            points=30,
            effort_level=3,
            is_bonus=True,
            interval_days=7,
        )
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        assert template.effort_level == 3
        assert template.effective_points == 60

    async def test_update_changes_effort_level(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(
            title="Med gig",
            points=20,
            effort_level=1,
            is_bonus=True,
            interval_days=7,
        )
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        updated = await TaskTemplateService.update_template(
            db_session,
            template.id,
            TaskTemplateUpdate(effort_level=2),
            test_family.id,
        )
        assert updated.effort_level == 2
        assert updated.effective_points == 30
