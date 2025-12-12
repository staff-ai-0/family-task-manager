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
from app.schemas.task import TaskCreate, TaskUpdate
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)


class TaskService:
    """Service for task-related operations"""

    @staticmethod
    async def create_task(
        db: AsyncSession,
        task_data: TaskCreate,
        family_id: UUID,
        created_by: UUID,
    ) -> Task:
        """Create a new task"""
        # Verify user exists and belongs to family
        user_query = select(User).where(
            and_(User.id == task_data.assigned_to, User.family_id == family_id)
        )
        user = (await db.execute(user_query)).scalar_one_or_none()
        if not user:
            raise NotFoundException("User not found or does not belong to this family")

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
        query = select(Task).where(
            and_(Task.id == task_id, Task.family_id == family_id)
        )
        task = (await db.execute(query)).scalar_one_or_none()
        if not task:
            raise NotFoundException("Task not found")
        return task

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
        task = await TaskService.get_task(db, task_id, family_id)
        
        # Update fields if provided
        update_fields = task_data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(task, field, value)
        
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)
        return task

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
        
        # Get user for point balance
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        
        # Mark task as completed
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        
        # Award points
        transaction = PointTransaction.create_task_completion(
            user_id=user_id,
            task_id=task.id,
            points=task.points,
            balance_before=user.points,
        )
        user.points += task.points
        
        db.add(transaction)
        await db.commit()
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
        query = select(Task).where(
            and_(
                Task.family_id == family_id,
                Task.status == TaskStatus.OVERDUE,
                Task.is_default == True,
                Task.consequence_id.is_(None),
            )
        )
        
        overdue_tasks = (await db.execute(query)).scalars().all()
        consequences = []
        
        for task in overdue_tasks:
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
            
            # Link consequence to task
            task.consequence_id = consequence.id
            
            db.add(consequence)
            consequences.append(consequence)
        
        if consequences:
            await db.commit()
        
        return consequences

    @staticmethod
    async def delete_task(db: AsyncSession, task_id: UUID, family_id: UUID) -> None:
        """Delete a task"""
        task = await TaskService.get_task(db, task_id, family_id)
        await db.delete(task)
        await db.commit()

    @staticmethod
    async def get_user_pending_tasks_count(
        db: AsyncSession, user_id: UUID
    ) -> int:
        """Get count of pending tasks for a user"""
        query = select(func.count()).select_from(Task).where(
            and_(
                Task.assigned_to == user_id,
                Task.status == TaskStatus.PENDING,
            )
        )
        result = await db.execute(query)
        return result.scalar() or 0
