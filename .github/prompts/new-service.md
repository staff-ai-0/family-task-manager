# Prompt Template: New Service Layer

Use this template when creating new service classes for business logic in the Family Task Manager.

## Checklist

- [ ] Define service class with clear responsibilities
- [ ] Implement business logic methods
- [ ] Add proper error handling
- [ ] Use database transactions for multi-step operations
- [ ] Validate permissions and access control
- [ ] Add logging for important operations
- [ ] Write comprehensive unit tests
- [ ] Document complex business rules

## Template Structure

### 1. Create Service in `app/services/[name]_service.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import logging

from app.models.[name] import [Model]
from app.schemas.[name] import [CreateSchema], [UpdateSchema]
from app.core.exceptions import (
    NotFoundException,
    PermissionDeniedError,
    ValidationError
)

logger = logging.getLogger(__name__)

class [ServiceName]:
    """
    Service for [resource] business logic
    
    This service handles all business operations related to [resources],
    including creation, updates, validation, and complex business rules.
    """
    
    @staticmethod
    async def create(
        data: [CreateSchema],
        family_id: UUID,
        created_by: UUID,
        db: AsyncSession
    ) -> [Model]:
        """
        Create a new [resource]
        
        Args:
            data: [Resource] creation data
            family_id: Family UUID
            created_by: User ID creating the resource
            db: Database session
        
        Returns:
            [Model]: Created [resource]
        
        Raises:
            ValidationError: If data validation fails
        """
        logger.info(f"Creating [resource] for family {family_id}")
        
        # Validate business rules
        await [ServiceName]._validate_creation(data, family_id, db)
        
        # Create instance
        async with db.begin():
            instance = [Model](
                **data.dict(),
                family_id=family_id,
                created_by=created_by
            )
            db.add(instance)
            await db.flush()
            await db.refresh(instance)
        
        logger.info(f"Created [resource] {instance.id}")
        return instance
    
    @staticmethod
    async def get_by_id(
        resource_id: UUID,
        db: AsyncSession,
        load_relations: bool = False
    ) -> Optional[[Model]]:
        """
        Get [resource] by ID
        
        Args:
            resource_id: [Resource] UUID
            db: Database session
            load_relations: Whether to eagerly load relationships
        
        Returns:
            [Model] or None if not found
        """
        query = select([Model]).filter([Model].id == resource_id)
        
        if load_relations:
            query = query.options(
                selectinload([Model].family),
                selectinload([Model].user)
            )
        
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def list_by_family(
        family_id: UUID,
        skip: int = 0,
        limit: int = 100,
        db: AsyncSession
    ) -> List[[Model]]:
        """
        List all [resources] for a family
        
        Args:
            family_id: Family UUID
            skip: Number of records to skip
            limit: Maximum number of records to return
            db: Database session
        
        Returns:
            List of [resources]
        """
        query = (
            select([Model])
            .filter([Model].family_id == family_id)
            .offset(skip)
            .limit(limit)
            .order_by([Model].created_at.desc())
        )
        
        result = await db.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def update(
        resource_id: UUID,
        data: [UpdateSchema],
        user_id: UUID,
        db: AsyncSession
    ) -> [Model]:
        """
        Update a [resource]
        
        Args:
            resource_id: [Resource] UUID
            data: Update data
            user_id: User performing the update
            db: Database session
        
        Returns:
            [Model]: Updated [resource]
        
        Raises:
            NotFoundException: If [resource] not found
            PermissionDeniedError: If user doesn't have permission
        """
        # Get existing resource
        instance = await [ServiceName].get_by_id(resource_id, db)
        if not instance:
            raise NotFoundException(f"[Resource] {resource_id} not found")
        
        # Validate permissions
        await [ServiceName]._validate_access(instance, user_id, db)
        
        # Update fields
        async with db.begin():
            update_data = data.dict(exclude_unset=True)
            for field, value in update_data.items():
                setattr(instance, field, value)
            
            await db.flush()
            await db.refresh(instance)
        
        logger.info(f"Updated [resource] {resource_id}")
        return instance
    
    @staticmethod
    async def delete(
        resource_id: UUID,
        user_id: UUID,
        db: AsyncSession
    ) -> None:
        """
        Delete a [resource]
        
        Args:
            resource_id: [Resource] UUID
            user_id: User performing the deletion
            db: Database session
        
        Raises:
            NotFoundException: If [resource] not found
            PermissionDeniedError: If user doesn't have permission
        """
        instance = await [ServiceName].get_by_id(resource_id, db)
        if not instance:
            raise NotFoundException(f"[Resource] {resource_id} not found")
        
        # Validate permissions (usually parent only)
        await [ServiceName]._validate_delete_permission(instance, user_id, db)
        
        async with db.begin():
            await db.delete(instance)
        
        logger.info(f"Deleted [resource] {resource_id}")
    
    # Private validation methods
    
    @staticmethod
    async def _validate_creation(
        data: [CreateSchema],
        family_id: UUID,
        db: AsyncSession
    ) -> None:
        """Validate [resource] creation business rules"""
        # Add custom validation logic
        pass
    
    @staticmethod
    async def _validate_access(
        instance: [Model],
        user_id: UUID,
        db: AsyncSession
    ) -> None:
        """Validate user has access to [resource]"""
        from app.models.user import User
        
        user = await db.get(User, user_id)
        if not user:
            raise PermissionDeniedError("User not found")
        
        if instance.family_id != user.family_id:
            raise PermissionDeniedError(
                "You don't have access to this [resource]"
            )
    
    @staticmethod
    async def _validate_delete_permission(
        instance: [Model],
        user_id: UUID,
        db: AsyncSession
    ) -> None:
        """Validate user can delete [resource] (usually parents only)"""
        from app.models.user import User, UserRole
        
        user = await db.get(User, user_id)
        if not user:
            raise PermissionDeniedError("User not found")
        
        if user.role != UserRole.PARENT:
            raise PermissionDeniedError(
                "Only parents can delete [resources]"
            )
        
        if instance.family_id != user.family_id:
            raise PermissionDeniedError(
                "You don't have access to this [resource]"
            )
```

## Task Service Example

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
from uuid import UUID
from datetime import datetime
import logging

from app.models.task import Task, TaskStatus
from app.models.user import User
from app.models.consequence import Consequence
from app.schemas.task import TaskCreateRequest, TaskUpdateRequest
from app.core.exceptions import ValidationError, PermissionDeniedError
from app.services.points_service import PointsService

logger = logging.getLogger(__name__)

class TaskService:
    """Service for task business logic"""
    
    @staticmethod
    async def complete_task(
        task_id: UUID,
        user_id: UUID,
        db: AsyncSession
    ) -> Task:
        """
        Complete a task and award points
        
        This is a complex business operation that:
        1. Marks task as completed
        2. Awards points to user
        3. Logs point transaction
        4. Resolves related consequences if applicable
        
        Args:
            task_id: Task UUID
            user_id: User completing the task
            db: Database session
        
        Returns:
            Task: Completed task
        
        Raises:
            NotFoundException: If task not found
            PermissionDeniedError: If user can't complete this task
            ValidationError: If task already completed
        """
        logger.info(f"User {user_id} completing task {task_id}")
        
        # Get task
        task = await db.get(Task, task_id)
        if not task:
            raise NotFoundException(f"Task {task_id} not found")
        
        # Validate user can complete this task
        if task.assigned_to != user_id:
            raise PermissionDeniedError(
                "You can only complete tasks assigned to you"
            )
        
        # Validate task can be completed
        if not task.can_complete:
            raise ValidationError(
                f"Task cannot be completed in status {task.status}"
            )
        
        async with db.begin():
            # Mark as completed
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            
            # Award points
            await PointsService.award_points(
                user_id=user_id,
                points=task.points,
                task_id=task_id,
                db=db
            )
            
            # Resolve consequence if this was a default task
            if task.is_default and task.consequence_id:
                consequence = await db.get(Consequence, task.consequence_id)
                if consequence and consequence.active:
                    consequence.active = False
                    consequence.resolved_at = datetime.utcnow()
                    logger.info(f"Resolved consequence {consequence.id}")
            
            await db.flush()
            await db.refresh(task)
        
        logger.info(f"Completed task {task_id}, awarded {task.points} points")
        return task
    
    @staticmethod
    async def can_access_extra_tasks(
        user_id: UUID,
        family_id: UUID,
        db: AsyncSession
    ) -> bool:
        """
        Check if user has completed all default tasks for today
        
        Args:
            user_id: User UUID
            family_id: Family UUID
            db: Database session
        
        Returns:
            bool: True if user can access extra tasks
        """
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        # Get default tasks for today
        query = select(Task).filter(
            and_(
                Task.assigned_to == user_id,
                Task.family_id == family_id,
                Task.is_default == True,
                Task.due_date >= today_start
            )
        )
        
        result = await db.execute(query)
        default_tasks = result.scalars().all()
        
        # Check all are completed
        completed = [
            t for t in default_tasks 
            if t.status == TaskStatus.COMPLETED
        ]
        
        can_access = len(completed) == len(default_tasks)
        logger.info(
            f"User {user_id} can access extra tasks: {can_access} "
            f"({len(completed)}/{len(default_tasks)} default tasks complete)"
        )
        
        return can_access
```

## Service Tests

```python
import pytest
from uuid import uuid4
from datetime import datetime, timedelta

from app.services.[name]_service import [ServiceName]
from app.core.exceptions import NotFoundException, PermissionDeniedError

@pytest.mark.asyncio
async def test_create_[resource]_success(db_session, test_family, test_user):
    """Test successful [resource] creation"""
    data = [CreateSchema](
        title="Test [Resource]",
        description="Test description"
    )
    
    result = await [ServiceName].create(
        data=data,
        family_id=test_family.id,
        created_by=test_user.id,
        db=db_session
    )
    
    assert result.id is not None
    assert result.title == "Test [Resource]"
    assert result.family_id == test_family.id

@pytest.mark.asyncio
async def test_get_[resource]_not_found(db_session):
    """Test getting non-existent [resource]"""
    result = await [ServiceName].get_by_id(
        resource_id=uuid4(),
        db=db_session
    )
    
    assert result is None

@pytest.mark.asyncio
async def test_update_[resource]_permission_denied(
    db_session, 
    test_[resource], 
    other_user
):
    """Test updating [resource] from different family"""
    data = [UpdateSchema](title="Updated Title")
    
    with pytest.raises(PermissionDeniedError):
        await [ServiceName].update(
            resource_id=test_[resource].id,
            data=data,
            user_id=other_user.id,
            db=db_session
        )
```

---

**Created**: December 11, 2025
