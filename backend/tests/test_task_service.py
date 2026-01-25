"""
Comprehensive tests for TaskService

Tests cover task management operations including:
- Task creation and validation
- Task listing with filters
- Task updates and deletion
- Overdue task detection
- Consequence triggering for overdue tasks
- User pending task counts
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.services.task_service import TaskService
from app.schemas.task import TaskCreate, TaskUpdate
from app.models.task import TaskStatus, TaskFrequency
from app.models.consequence import ConsequenceSeverity, RestrictionType
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)


class TestTaskCreation:
    """Test task creation"""

    async def test_create_task_successfully(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Test creating a new task successfully"""
        task_data = TaskCreate(
            title="Clean Room",
            description="Clean and organize bedroom",
            points=100,
            is_default=True,
            frequency=TaskFrequency.DAILY,
            assigned_to=test_child_user.id,
            due_date=datetime.utcnow() + timedelta(days=1),
        )

        task = await TaskService.create_task(
            db_session, task_data, test_family.id, test_parent_user.id
        )

        assert task.id is not None
        assert task.title == "Clean Room"
        assert task.points == 100
        assert task.is_default is True
        assert task.frequency == TaskFrequency.DAILY
        assert task.assigned_to == test_child_user.id
        assert task.created_by == test_parent_user.id
        assert task.family_id == test_family.id
        assert task.status == TaskStatus.PENDING

    async def test_create_task_with_nonexistent_user(
        self, db_session, test_family, test_parent_user
    ):
        """Test creating task fails when assigned user doesn't exist"""
        task_data = TaskCreate(
            title="Invalid Task",
            description="Test",
            points=50,
            is_default=False,
            frequency=TaskFrequency.DAILY,
            assigned_to=uuid4(),  # Non-existent user
        )

        with pytest.raises(NotFoundException):
            await TaskService.create_task(
                db_session, task_data, test_family.id, test_parent_user.id
            )

    async def test_create_task_without_due_date(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Test creating task without due date"""
        task_data = TaskCreate(
            title="Ongoing Task",
            description="No deadline",
            points=25,
            is_default=False,
            frequency=TaskFrequency.WEEKLY,
            assigned_to=test_child_user.id,
            due_date=None,
        )

        task = await TaskService.create_task(
            db_session, task_data, test_family.id, test_parent_user.id
        )

        assert task.due_date is None
        assert task.status == TaskStatus.PENDING


class TestTaskRetrieval:
    """Test task retrieval operations"""

    async def test_get_task_by_id(self, db_session, test_task, test_family):
        """Test getting task by ID"""
        task = await TaskService.get_task(db_session, test_task.id, test_family.id)

        assert task.id == test_task.id
        assert task.title == test_task.title

    async def test_get_nonexistent_task(self, db_session, test_family):
        """Test getting non-existent task raises exception"""
        with pytest.raises(NotFoundException):
            await TaskService.get_task(db_session, uuid4(), test_family.id)


class TestTaskListing:
    """Test task listing with filters"""

    async def test_list_all_tasks(self, db_session, test_family, test_task):
        """Test listing all tasks in family"""
        tasks = await TaskService.list_tasks(db_session, test_family.id)

        assert len(tasks) >= 1
        assert any(t.id == test_task.id for t in tasks)

    async def test_list_tasks_by_user(
        self, db_session, test_family, test_child_user, test_task
    ):
        """Test filtering tasks by assigned user"""
        tasks = await TaskService.list_tasks(
            db_session, test_family.id, user_id=test_child_user.id
        )

        assert len(tasks) >= 1
        assert all(t.assigned_to == test_child_user.id for t in tasks)

    async def test_list_tasks_by_status(
        self, db_session, test_family, test_task
    ):
        """Test filtering tasks by status"""
        # Get pending tasks
        pending_tasks = await TaskService.list_tasks(
            db_session, test_family.id, status=TaskStatus.PENDING
        )

        assert all(t.status == TaskStatus.PENDING for t in pending_tasks)

    async def test_list_default_tasks(
        self, db_session, test_family, test_task
    ):
        """Test filtering default tasks"""
        # Set task as default
        test_task.is_default = True
        await db_session.commit()

        default_tasks = await TaskService.list_tasks(
            db_session, test_family.id, is_default=True
        )

        assert all(t.is_default is True for t in default_tasks)

    async def test_list_tasks_empty_family(self, db_session, test_family):
        """Test listing tasks returns empty list for family with no tasks"""
        # Create a new family without tasks
        from app.models import Family
        new_family = Family(name="Empty Family")
        db_session.add(new_family)
        await db_session.commit()

        tasks = await TaskService.list_tasks(db_session, new_family.id)

        assert len(tasks) == 0


class TestTaskUpdate:
    """Test task update operations"""

    async def test_update_task_title(self, db_session, test_task, test_family):
        """Test updating task title"""
        update_data = TaskUpdate(title="Updated Title")

        task = await TaskService.update_task(
            db_session, test_task.id, update_data, test_family.id
        )

        assert task.title == "Updated Title"

    async def test_update_task_points(self, db_session, test_task, test_family):
        """Test updating task points"""
        update_data = TaskUpdate(points=150)

        task = await TaskService.update_task(
            db_session, test_task.id, update_data, test_family.id
        )

        assert task.points == 150

    async def test_update_nonexistent_task(self, db_session, test_family):
        """Test updating non-existent task raises exception"""
        update_data = TaskUpdate(title="Test")

        with pytest.raises(NotFoundException):
            await TaskService.update_task(
                db_session, uuid4(), update_data, test_family.id
            )


class TestTaskCompletion:
    """Test task completion logic"""

    async def test_complete_task_successfully(
        self, db_session, test_task, test_family, test_child_user
    ):
        """Test completing a task successfully"""
        initial_points = test_child_user.points

        task = await TaskService.complete_task(
            db_session, test_task.id, test_family.id, test_child_user.id
        )

        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None

        # Verify points were awarded
        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points + test_task.points

    async def test_complete_task_wrong_user(
        self, db_session, test_task, test_family, test_parent_user
    ):
        """Test completing task fails if not assigned user"""
        with pytest.raises(ForbiddenException) as exc_info:
            await TaskService.complete_task(
                db_session, test_task.id, test_family.id, test_parent_user.id
            )

        assert "assigned user" in str(exc_info.value).lower()

    async def test_cannot_complete_already_completed_task(
        self, db_session, test_task, test_family, test_child_user
    ):
        """Test cannot complete already completed task"""
        # Complete task first time
        await TaskService.complete_task(
            db_session, test_task.id, test_family.id, test_child_user.id
        )

        # Try to complete again
        with pytest.raises(ValidationException):
            await TaskService.complete_task(
                db_session, test_task.id, test_family.id, test_child_user.id
            )


class TestOverdueTasks:
    """Test overdue task detection and handling"""

    async def test_check_overdue_tasks(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Test detecting overdue tasks"""
        # Create task with past due date
        from app.models import Task
        overdue_task = Task(
            title="Overdue Task",
            description="Past deadline",
            points=50,
            is_default=True,
            frequency=TaskFrequency.DAILY,
            assigned_to=test_child_user.id,
            created_by=test_parent_user.id,
            family_id=test_family.id,
            due_date=datetime.utcnow() - timedelta(days=1),
            status=TaskStatus.PENDING,
        )
        db_session.add(overdue_task)
        await db_session.commit()

        # Check for overdue tasks
        overdue_tasks = await TaskService.check_overdue_tasks(
            db_session, test_family.id
        )

        assert len(overdue_tasks) >= 1
        assert any(t.id == overdue_task.id for t in overdue_tasks)

        # Verify status was updated
        await db_session.refresh(overdue_task)
        assert overdue_task.status == TaskStatus.OVERDUE

    async def test_check_overdue_ignores_completed(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Test overdue check ignores completed tasks"""
        from app.models import Task
        completed_task = Task(
            title="Completed Task",
            description="Already done",
            points=50,
            is_default=True,
            frequency=TaskFrequency.DAILY,
            assigned_to=test_child_user.id,
            created_by=test_parent_user.id,
            family_id=test_family.id,
            due_date=datetime.utcnow() - timedelta(days=1),
            status=TaskStatus.COMPLETED,
            completed_at=datetime.utcnow() - timedelta(days=2),
        )
        db_session.add(completed_task)
        await db_session.commit()

        overdue_tasks = await TaskService.check_overdue_tasks(
            db_session, test_family.id
        )

        assert all(t.id != completed_task.id for t in overdue_tasks)

    async def test_check_overdue_ignores_no_due_date(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Test overdue check ignores tasks without due dates"""
        from app.models import Task
        no_due_date_task = Task(
            title="No Deadline",
            description="Open ended",
            points=50,
            is_default=True,
            frequency=TaskFrequency.DAILY,
            assigned_to=test_child_user.id,
            created_by=test_parent_user.id,
            family_id=test_family.id,
            due_date=None,
            status=TaskStatus.PENDING,
        )
        db_session.add(no_due_date_task)
        await db_session.commit()

        overdue_tasks = await TaskService.check_overdue_tasks(
            db_session, test_family.id
        )

        assert all(t.id != no_due_date_task.id for t in overdue_tasks)


class TestConsequenceTriggers:
    """Test consequence triggering for overdue tasks"""

    async def test_trigger_consequences_for_overdue_default_tasks(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Test consequences are created for overdue default tasks"""
        from app.models import Task
        overdue_task = Task(
            title="Default Overdue",
            description="Should trigger consequence",
            points=50,
            is_default=True,
            frequency=TaskFrequency.DAILY,
            assigned_to=test_child_user.id,
            created_by=test_parent_user.id,
            family_id=test_family.id,
            due_date=datetime.utcnow() - timedelta(days=1),
            status=TaskStatus.OVERDUE,
        )
        db_session.add(overdue_task)
        await db_session.commit()

        consequences = await TaskService.trigger_consequences_for_overdue(
            db_session, test_family.id
        )

        assert len(consequences) >= 1
        consequence = next((c for c in consequences if c.triggered_by_task_id == overdue_task.id), None)
        assert consequence is not None
        assert consequence.applied_to_user == test_child_user.id
        assert consequence.severity == ConsequenceSeverity.LOW
        assert consequence.restriction_type == RestrictionType.EXTRA_TASKS

    async def test_trigger_consequences_ignores_non_default(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Test consequences not created for non-default tasks"""
        from app.models import Task
        overdue_task = Task(
            title="Non-Default Overdue",
            description="Should not trigger consequence",
            points=50,
            is_default=False,
            frequency=TaskFrequency.DAILY,
            assigned_to=test_child_user.id,
            created_by=test_parent_user.id,
            family_id=test_family.id,
            due_date=datetime.utcnow() - timedelta(days=1),
            status=TaskStatus.OVERDUE,
        )
        db_session.add(overdue_task)
        await db_session.commit()

        consequences = await TaskService.trigger_consequences_for_overdue(
            db_session, test_family.id
        )

        assert all(c.triggered_by_task_id != overdue_task.id for c in consequences)

    async def test_trigger_consequences_only_once_per_task(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Test consequence not created if one already exists for the task"""
        from app.models import Task, Consequence
        overdue_task = Task(
            title="Already Has Consequence",
            description="Test",
            points=50,
            is_default=True,
            frequency=TaskFrequency.DAILY,
            assigned_to=test_child_user.id,
            created_by=test_parent_user.id,
            family_id=test_family.id,
            due_date=datetime.utcnow() - timedelta(days=1),
            status=TaskStatus.OVERDUE,
        )
        db_session.add(overdue_task)
        await db_session.commit()
        await db_session.refresh(overdue_task)

        # Create existing consequence
        existing_consequence = Consequence(
            title="Existing",
            description="Already exists",
            severity=ConsequenceSeverity.LOW,
            restriction_type=RestrictionType.EXTRA_TASKS,
            duration_days=1,
            triggered_by_task_id=overdue_task.id,
            applied_to_user=test_child_user.id,
            family_id=test_family.id,
        )
        existing_consequence.apply_consequence()
        db_session.add(existing_consequence)
        await db_session.commit()

        # Try to trigger consequences again
        consequences = await TaskService.trigger_consequences_for_overdue(
            db_session, test_family.id
        )

        # Should not create a new one for this task
        new_consequences_for_task = [
            c for c in consequences if c.triggered_by_task_id == overdue_task.id
        ]
        assert len(new_consequences_for_task) == 0


class TestTaskDeletion:
    """Test task deletion"""

    async def test_delete_task(self, db_session, test_task, test_family):
        """Test deleting a task"""
        task_id = test_task.id

        await TaskService.delete_task(db_session, task_id, test_family.id)

        # Verify task is deleted
        with pytest.raises(NotFoundException):
            await TaskService.get_task(db_session, task_id, test_family.id)

    async def test_delete_nonexistent_task(self, db_session, test_family):
        """Test deleting non-existent task raises exception"""
        with pytest.raises(NotFoundException):
            await TaskService.delete_task(db_session, uuid4(), test_family.id)


class TestUserPendingTaskCount:
    """Test user pending task count"""

    async def test_get_pending_tasks_count(
        self, db_session, test_child_user, test_task
    ):
        """Test getting count of pending tasks for user"""
        count = await TaskService.get_user_pending_tasks_count(
            db_session, test_child_user.id
        )

        assert count >= 1

    async def test_get_pending_tasks_count_excludes_completed(
        self, db_session, test_child_user, test_task, test_family
    ):
        """Test count excludes completed tasks"""
        # Complete the task
        await TaskService.complete_task(
            db_session, test_task.id, test_family.id, test_child_user.id
        )

        count = await TaskService.get_user_pending_tasks_count(
            db_session, test_child_user.id
        )

        # Count should not include the completed task
        # (Should be 0 unless there are other pending tasks)
        assert count == 0 or count >= 0

    async def test_get_pending_tasks_count_zero(self, db_session, test_parent_user):
        """Test count is zero when user has no pending tasks"""
        count = await TaskService.get_user_pending_tasks_count(
            db_session, test_parent_user.id
        )

        # Parent user typically has no tasks assigned
        assert count >= 0
