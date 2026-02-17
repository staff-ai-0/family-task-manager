"""
Task Service

Business logic for task management operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.models import Task, User, Family, PointTransaction, Consequence
from app.models.task import TaskStatus, TaskFrequency
from app.models.consequence import ConsequenceSeverity, RestrictionType
from app.schemas.task import TaskCreate, TaskUpdate, TaskBulkCreate, TaskRegenerateRequest
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.services.base_service import (
    BaseFamilyService,
    verify_user_in_family,
    get_user_by_id,
)
from app.services.points_service import PointsService


class TaskService(BaseFamilyService[Task]):
    """Service for task-related operations"""

    model = Task

    @staticmethod
    async def create_task(
        db: AsyncSession,
        task_data: TaskCreate,
        family_id: UUID,
        created_by: UUID,
    ) -> Task:
        """Create a new task"""
        # Verify user exists and belongs to family
        await verify_user_in_family(db, task_data.assigned_to, family_id)

        # Create task
        task = Task(
            title=task_data.title,
            description=task_data.description,
            points=task_data.points,
            is_default=task_data.is_default,
            frequency=task_data.frequency,
            assigned_to=task_data.assigned_to,
            created_by=created_by,
            family_id=family_id,
            due_date=task_data.due_date,
            status=TaskStatus.PENDING,
        )

        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_task(db: AsyncSession, task_id: UUID, family_id: UUID) -> Task:
        """Get a task by ID"""
        return await TaskService.get_by_id(db, task_id, family_id)

    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        family_id: UUID,
        user_id: Optional[UUID] = None,
        status: Optional[TaskStatus] = None,
        is_default: Optional[bool] = None,
    ) -> List[Task]:
        """List tasks with optional filters"""
        query = select(Task).where(Task.family_id == family_id)

        if user_id:
            query = query.where(Task.assigned_to == user_id)
        if status:
            query = query.where(Task.status == status)
        if is_default is not None:
            query = query.where(Task.is_default == is_default)

        query = query.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def update_task(
        db: AsyncSession,
        task_id: UUID,
        task_data: TaskUpdate,
        family_id: UUID,
    ) -> Task:
        """Update task details"""
        update_fields = task_data.model_dump(exclude_unset=True)
        return await TaskService.update_by_id(db, task_id, family_id, update_fields)

    @staticmethod
    async def complete_task(
        db: AsyncSession,
        task_id: UUID,
        family_id: UUID,
        user_id: UUID,
    ) -> Task:
        """Mark task as completed and award points"""
        task = await TaskService.get_task(db, task_id, family_id)

        # Validate task can be completed
        if not task.can_complete:
            raise ValidationException(
                f"Task cannot be completed. Current status: {task.status.value}"
            )

        # Verify user is the assigned user
        if task.assigned_to != user_id:
            raise ForbiddenException("Only the assigned user can complete this task")

        # Mark task as completed
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()

        # Award points using PointsService
        await PointsService.award_points_for_task(
            db=db,
            user_id=user_id,
            task_id=task.id,
            points=task.points,
        )

        # Refresh task to get updated state
        await db.refresh(task)

        return task

    @staticmethod
    async def check_overdue_tasks(db: AsyncSession, family_id: UUID) -> List[Task]:
        """Check for overdue tasks and update their status"""
        now = datetime.utcnow()

        query = select(Task).where(
            and_(
                Task.family_id == family_id,
                Task.status == TaskStatus.PENDING,
                Task.due_date.isnot(None),
                Task.due_date < now,
            )
        )

        tasks = (await db.execute(query)).scalars().all()

        for task in tasks:
            task.status = TaskStatus.OVERDUE

        if tasks:
            await db.commit()

        return list(tasks)

    @staticmethod
    async def trigger_consequences_for_overdue(
        db: AsyncSession, family_id: UUID
    ) -> List[Consequence]:
        """Trigger consequences for overdue default tasks"""
        # Find overdue default tasks without active consequences
        # Check if task already has a consequence by looking for existing Consequence records
        query = select(Task).where(
            and_(
                Task.family_id == family_id,
                Task.status == TaskStatus.OVERDUE,
                Task.is_default == True,
            )
        )

        overdue_tasks = (await db.execute(query)).scalars().all()

        # Filter out tasks that already have consequences
        tasks_without_consequences = []
        for task in overdue_tasks:
            consequence_check = await db.execute(
                select(Consequence).where(Consequence.triggered_by_task_id == task.id)
            )
            if not consequence_check.scalar_one_or_none():
                tasks_without_consequences.append(task)

        consequences = []

        for task in tasks_without_consequences:
            # Create consequence
            consequence = Consequence(
                title=f"Incomplete task: {task.title}",
                description=f"Task '{task.title}' was not completed by the deadline",
                severity=ConsequenceSeverity.LOW,
                restriction_type=RestrictionType.EXTRA_TASKS,
                duration_days=1,
                triggered_by_task_id=task.id,
                applied_to_user=task.assigned_to,
                family_id=family_id,
            )
            consequence.apply_consequence()

            db.add(consequence)
            consequences.append(consequence)

        if consequences:
            await db.commit()

        return consequences

    @staticmethod
    async def delete_task(db: AsyncSession, task_id: UUID, family_id: UUID) -> None:
        """Delete a task"""
        await TaskService.delete_by_id(db, task_id, family_id)

    @staticmethod
    async def get_user_pending_tasks_count(db: AsyncSession, user_id: UUID) -> int:
        """Get count of pending tasks for a user"""
        query = (
            select(func.count())
            .select_from(Task)
            .where(
                and_(
                    Task.assigned_to == user_id,
                    Task.status == TaskStatus.PENDING,
                )
            )
        )
        result = await db.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def bulk_create_tasks(
        db: AsyncSession,
        task_data: TaskBulkCreate,
        family_id: UUID,
        created_by: UUID,
    ) -> List[Task]:
        """Create the same task for multiple users at once"""
        tasks = []
        
        for user_id in task_data.assigned_to:
            # Verify each user belongs to the family
            await verify_user_in_family(db, user_id, family_id)
            
            task = Task(
                title=task_data.title,
                description=task_data.description,
                points=task_data.points,
                is_default=task_data.is_default,
                frequency=task_data.frequency,
                assigned_to=user_id,
                created_by=created_by,
                family_id=family_id,
                due_date=task_data.due_date,
                status=TaskStatus.PENDING,
            )
            db.add(task)
            tasks.append(task)
        
        await db.commit()
        
        # Refresh all tasks to get their IDs
        for task in tasks:
            await db.refresh(task)
        
        return tasks

    @staticmethod
    async def duplicate_task(
        db: AsyncSession,
        task_id: UUID,
        family_id: UUID,
        created_by: UUID,
        assigned_to: Optional[UUID] = None,
        include_due_date: bool = False,
    ) -> Task:
        """Duplicate an existing task"""
        original = await TaskService.get_task(db, task_id, family_id)
        
        # Use original assignee if not specified
        target_user = assigned_to or original.assigned_to
        await verify_user_in_family(db, target_user, family_id)
        
        new_task = Task(
            title=original.title,
            description=original.description,
            points=original.points,
            is_default=original.is_default,
            frequency=original.frequency,
            assigned_to=target_user,
            created_by=created_by,
            family_id=family_id,
            due_date=original.due_date if include_due_date else None,
            status=TaskStatus.PENDING,
        )
        
        db.add(new_task)
        await db.commit()
        await db.refresh(new_task)
        return new_task

    @staticmethod
    async def regenerate_tasks(
        db: AsyncSession,
        request: TaskRegenerateRequest,
        family_id: UUID,
        created_by: UUID,
    ) -> List[Task]:
        """Regenerate tasks based on frequency - creates new pending tasks from completed ones"""
        # Find completed or cancelled tasks with the specified frequency
        query = select(Task).where(
            and_(
                Task.family_id == family_id,
                Task.frequency == request.frequency,
                Task.status.in_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]),
            )
        )
        
        if request.user_ids:
            query = query.where(Task.assigned_to.in_(request.user_ids))
        
        completed_tasks = (await db.execute(query)).scalars().all()
        
        new_tasks = []
        seen_templates = set()  # Track (title, assigned_to) to avoid duplicates
        
        for task in completed_tasks:
            template_key = (task.title, task.assigned_to)
            if template_key in seen_templates:
                continue
            seen_templates.add(template_key)
            
            # Check if there's already a pending task with same title for this user
            existing_query = select(Task).where(
                and_(
                    Task.family_id == family_id,
                    Task.title == task.title,
                    Task.assigned_to == task.assigned_to,
                    Task.status == TaskStatus.PENDING,
                )
            )
            existing = (await db.execute(existing_query)).scalar_one_or_none()
            
            if existing:
                continue  # Don't create duplicate pending task
            
            # Create new task instance
            new_task = Task(
                title=task.title,
                description=task.description,
                points=task.points,
                is_default=task.is_default,
                frequency=task.frequency,
                assigned_to=task.assigned_to,
                created_by=created_by,
                family_id=family_id,
                due_date=None,  # Parent can set new due dates
                status=TaskStatus.PENDING,
            )
            db.add(new_task)
            new_tasks.append(new_task)
        
        if new_tasks:
            await db.commit()
            for task in new_tasks:
                await db.refresh(task)
        
        return new_tasks
