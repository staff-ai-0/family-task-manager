"""
Tests for TaskTemplateService

Tests template CRUD, toggle active, and listing with filters.
"""

import pytest
from uuid import uuid4

from app.services.task_template_service import TaskTemplateService
from app.schemas.task_template import TaskTemplateCreate, TaskTemplateUpdate
from app.core.exceptions import NotFoundException


class TestTemplateCreation:
    async def test_create_template_basic(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(
            title="Make Your Bed",
            description="Make your bed neatly every morning",
            points=20,
            interval_days=1,
            is_bonus=False,
        )
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        assert template.title == "Make Your Bed"
        assert template.points == 20
        assert template.interval_days == 1
        assert template.is_bonus is False
        assert template.is_active is True
        assert template.family_id == test_family.id
        assert template.created_by == test_parent_user.id

    async def test_create_bonus_template(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(
            title="Help With Dishes",
            points=40,
            interval_days=1,
            is_bonus=True,
        )
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        assert template.is_bonus is True

    async def test_create_weekly_template(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(
            title="Clean Your Room",
            points=30,
            interval_days=7,
            is_bonus=False,
        )
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        assert template.interval_days == 7


class TestTemplateRetrieval:
    async def test_get_template_by_id(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(title="Test Task", points=10)
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        fetched = await TaskTemplateService.get_template(
            db_session, template.id, test_family.id
        )
        assert fetched.id == template.id
        assert fetched.title == "Test Task"

    async def test_get_nonexistent_template_raises(
        self, db_session, test_family
    ):
        with pytest.raises(NotFoundException):
            await TaskTemplateService.get_template(
                db_session, uuid4(), test_family.id
            )

    async def test_get_template_wrong_family_raises(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(title="Test Task", points=10)
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        with pytest.raises(NotFoundException):
            await TaskTemplateService.get_template(
                db_session, template.id, uuid4()
            )


class TestTemplateListing:
    async def test_list_all_templates(
        self, db_session, test_family, test_parent_user
    ):
        for i in range(3):
            data = TaskTemplateCreate(title=f"Task {i}", points=10)
            await TaskTemplateService.create_template(
                db_session, data, test_family.id, test_parent_user.id
            )
        templates = await TaskTemplateService.list_templates(
            db_session, test_family.id
        )
        assert len(templates) == 3

    async def test_list_templates_filter_by_active(
        self, db_session, test_family, test_parent_user
    ):
        active_data = TaskTemplateCreate(title="Active", points=10)
        inactive_data = TaskTemplateCreate(title="Inactive", points=10)
        active = await TaskTemplateService.create_template(
            db_session, active_data, test_family.id, test_parent_user.id
        )
        inactive = await TaskTemplateService.create_template(
            db_session, inactive_data, test_family.id, test_parent_user.id
        )
        await TaskTemplateService.toggle_active(
            db_session, inactive.id, test_family.id
        )

        active_list = await TaskTemplateService.list_templates(
            db_session, test_family.id, is_active=True
        )
        assert len(active_list) == 1
        assert active_list[0].title == "Active"

    async def test_list_templates_filter_by_bonus(
        self, db_session, test_family, test_parent_user
    ):
        regular_data = TaskTemplateCreate(title="Regular", points=10, is_bonus=False)
        bonus_data = TaskTemplateCreate(title="Bonus", points=20, is_bonus=True)
        await TaskTemplateService.create_template(
            db_session, regular_data, test_family.id, test_parent_user.id
        )
        await TaskTemplateService.create_template(
            db_session, bonus_data, test_family.id, test_parent_user.id
        )

        bonus_list = await TaskTemplateService.list_templates(
            db_session, test_family.id, is_bonus=True
        )
        assert len(bonus_list) == 1
        assert bonus_list[0].title == "Bonus"

    async def test_list_templates_family_isolation(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(title="Family A Task", points=10)
        await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        other_family_templates = await TaskTemplateService.list_templates(
            db_session, uuid4()
        )
        assert len(other_family_templates) == 0


class TestTemplateUpdate:
    async def test_update_template_title_and_points(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(title="Old Title", points=10)
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        update_data = TaskTemplateUpdate(title="New Title", points=50)
        updated = await TaskTemplateService.update_template(
            db_session, template.id, update_data, test_family.id
        )
        assert updated.title == "New Title"
        assert updated.points == 50

    async def test_update_template_partial(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(title="Keep Title", points=10, interval_days=1)
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        update_data = TaskTemplateUpdate(interval_days=7)
        updated = await TaskTemplateService.update_template(
            db_session, template.id, update_data, test_family.id
        )
        assert updated.title == "Keep Title"  # Unchanged
        assert updated.interval_days == 7

    async def test_update_nonexistent_raises(
        self, db_session, test_family
    ):
        update_data = TaskTemplateUpdate(title="New")
        with pytest.raises(NotFoundException):
            await TaskTemplateService.update_template(
                db_session, uuid4(), update_data, test_family.id
            )


class TestTemplateToggle:
    async def test_toggle_active_to_inactive(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(title="Toggle Test", points=10)
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        assert template.is_active is True
        toggled = await TaskTemplateService.toggle_active(
            db_session, template.id, test_family.id
        )
        assert toggled.is_active is False

    async def test_toggle_inactive_to_active(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(title="Toggle Test", points=10)
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        await TaskTemplateService.toggle_active(
            db_session, template.id, test_family.id
        )
        toggled = await TaskTemplateService.toggle_active(
            db_session, template.id, test_family.id
        )
        assert toggled.is_active is True


class TestTemplateDeletion:
    async def test_delete_template(
        self, db_session, test_family, test_parent_user
    ):
        data = TaskTemplateCreate(title="To Delete", points=10)
        template = await TaskTemplateService.create_template(
            db_session, data, test_family.id, test_parent_user.id
        )
        await TaskTemplateService.delete_template(
            db_session, template.id, test_family.id
        )
        with pytest.raises(NotFoundException):
            await TaskTemplateService.get_template(
                db_session, template.id, test_family.id
            )

    async def test_delete_nonexistent_raises(
        self, db_session, test_family
    ):
        with pytest.raises(NotFoundException):
            await TaskTemplateService.delete_template(
                db_session, uuid4(), test_family.id
            )
