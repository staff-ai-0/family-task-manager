# Multi-Tenant Patterns - Family Task Manager

**Architecture**: Family-based tenant isolation  
**Rule**: Every family's data MUST be completely isolated from other families  
**Last Updated**: January 25, 2026

---

## 🎯 Core Principle

> **CRITICAL**: Every entity with family-specific data MUST have a `family_id` foreign key.  
> Every service method MUST accept `family_id` as the first parameter.  
> Every database query MUST filter by `family_id`.

Violating these rules creates **security vulnerabilities** that allow data leakage between families.

---

## 📋 Multi-Tenant Checklist

When creating or modifying family-owned entities:

- [ ] Model has `family_id: Mapped[UUID]` column
- [ ] `family_id` column is NOT NULL
- [ ] `family_id` column has index for performance
- [ ] `family_id` has foreign key to `families.id`
- [ ] Foreign key has CASCADE delete (optional, based on requirements)
- [ ] Repository methods accept `family_id` as first parameter
- [ ] ALL queries filter by `family_id`
- [ ] Service methods accept `family_id` as first parameter
- [ ] API routes extract `family_id` from `current_user.family_id`
- [ ] Tests verify tenant isolation (data not visible to other families)

---

## 1. Database Models with Family ID

### ✅ Complete Example: Task Model

```python
# backend/app/models/task.py
from sqlalchemy import String, Integer, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from app.core.database import Base

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class TaskFrequency(str, Enum):
    ONE_TIME = "ONE_TIME"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"

class Task(Base):
    """Task model - family-owned entity.
    
    CRITICAL: All tasks belong to a family and are isolated from other families.
    """
    __tablename__ = "tasks"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4
    )
    
    # CRITICAL: Family isolation - MUST be present and NOT NULL
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # Performance: Index for filtering
    )
    
    # Task ownership
    assigned_to: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # Task details
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    points: Mapped[int] = mapped_column(Integer, default=10)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Status and frequency
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus, name="task_status"),
        default=TaskStatus.PENDING
    )
    frequency: Mapped[TaskFrequency] = mapped_column(
        SQLEnum(TaskFrequency, name="task_frequency"),
        default=TaskFrequency.ONE_TIME
    )
    
    # Dates
    due_date: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    
    # Relationships
    family: Mapped["Family"] = relationship(back_populates="tasks")
    assigned_user: Mapped["User"] = relationship(
        foreign_keys=[assigned_to],
        back_populates="assigned_tasks"
    )
    creator: Mapped["User"] = relationship(
        foreign_keys=[created_by],
        back_populates="created_tasks"
    )
```

**Key Points**:
- `family_id` is NOT NULL (required for every task)
- Indexed for performance (frequent filtering)
- CASCADE delete (when family deleted, tasks deleted)
- Relationships use `back_populates` for bidirectional access

---

### ✅ Complete Example: Reward Model

```python
# backend/app/models/reward.py
from sqlalchemy import String, Integer, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from app.core.database import Base

class RewardCategory(str, Enum):
    PRIVILEGE = "PRIVILEGE"
    ITEM = "ITEM"
    ACTIVITY = "ACTIVITY"
    OTHER = "OTHER"

class Reward(Base):
    """Reward model - family-owned entity.
    
    Each family defines their own reward catalog.
    """
    __tablename__ = "rewards"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    
    # CRITICAL: Family isolation
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # Reward details
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    points_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[RewardCategory] = mapped_column(
        SQLEnum(RewardCategory, name="reward_category"),
        default=RewardCategory.OTHER
    )
    icon: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Dates
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    
    # Relationships
    family: Mapped["Family"] = relationship(back_populates="rewards")
    creator: Mapped["User"] = relationship(back_populates="created_rewards")
```

---

## 2. Repository Layer with Family Filtering

### ✅ Complete Example: Task Repository

```python
# backend/app/repositories/task_repository.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import joinedload
from uuid import UUID
from typing import List, Optional
from datetime import datetime
from app.models.task import Task, TaskStatus

class TaskRepository:
    """Task repository with family-based tenant isolation.
    
    CRITICAL: All methods accept family_id as first parameter and filter by it.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_all_by_family(
        self,
        family_id: UUID,
        status: Optional[TaskStatus] = None,
        assigned_to: Optional[UUID] = None,
        is_default: Optional[bool] = None
    ) -> List[Task]:
        """Get all tasks for a specific family with optional filters.
        
        Args:
            family_id: REQUIRED - Family to query tasks for
            status: Optional status filter
            assigned_to: Optional user filter
            is_default: Optional default task filter
            
        Returns:
            List of tasks belonging to the family
            
        CRITICAL: ALWAYS filters by family_id
        """
        # Start with family filter
        query = select(Task).where(Task.family_id == family_id)
        
        # Add optional filters
        if status is not None:
            query = query.where(Task.status == status)
        
        if assigned_to is not None:
            query = query.where(Task.assigned_to == assigned_to)
        
        if is_default is not None:
            query = query.where(Task.is_default == is_default)
        
        # Eager load relationships to avoid N+1 queries
        query = query.options(
            joinedload(Task.assigned_user),
            joinedload(Task.family)
        )
        
        # Order by creation date
        query = query.order_by(Task.created_at.desc())
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
    
    async def get_by_id(
        self,
        family_id: UUID,
        task_id: UUID
    ) -> Optional[Task]:
        """Get a specific task by ID, ensuring it belongs to the family.
        
        Args:
            family_id: REQUIRED - Family the task must belong to
            task_id: Task ID to retrieve
            
        Returns:
            Task if found and belongs to family, None otherwise
            
        CRITICAL: Includes family_id check for security
        """
        query = select(Task).where(
            Task.id == task_id,
            Task.family_id == family_id  # Security: Verify family ownership
        ).options(
            joinedload(Task.assigned_user),
            joinedload(Task.family)
        )
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def create(
        self,
        family_id: UUID,
        task_data: dict
    ) -> Task:
        """Create a new task for a specific family.
        
        Args:
            family_id: REQUIRED - Family to create task for
            task_data: Task attributes
            
        Returns:
            Created task
            
        CRITICAL: Explicitly sets family_id
        """
        task = Task(
            family_id=family_id,  # Always set family_id
            **task_data
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task
    
    async def update(
        self,
        family_id: UUID,
        task_id: UUID,
        updates: dict
    ) -> Optional[Task]:
        """Update a task, ensuring it belongs to the family.
        
        Args:
            family_id: REQUIRED - Family the task must belong to
            task_id: Task to update
            updates: Fields to update
            
        Returns:
            Updated task if found and belongs to family, None otherwise
            
        CRITICAL: Filters by both task_id and family_id
        """
        # Find task with family check
        task = await self.get_by_id(family_id, task_id)
        if not task:
            return None
        
        # Apply updates
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
        
        task.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(task)
        return task
    
    async def delete(
        self,
        family_id: UUID,
        task_id: UUID
    ) -> bool:
        """Delete a task, ensuring it belongs to the family.
        
        Args:
            family_id: REQUIRED - Family the task must belong to
            task_id: Task to delete
            
        Returns:
            True if deleted, False if not found or wrong family
            
        CRITICAL: Verifies family ownership before deletion
        """
        result = await self.db.execute(
            delete(Task).where(
                Task.id == task_id,
                Task.family_id == family_id  # Security check
            )
        )
        await self.db.commit()
        return result.rowcount > 0
    
    async def complete_task(
        self,
        family_id: UUID,
        task_id: UUID,
        completed_by: UUID
    ) -> Optional[Task]:
        """Mark a task as completed.
        
        Args:
            family_id: REQUIRED - Family the task belongs to
            task_id: Task to complete
            completed_by: User completing the task
            
        Returns:
            Completed task if successful, None otherwise
        """
        task = await self.get_by_id(family_id, task_id)
        if not task:
            return None
        
        # Verify user belongs to same family (security check)
        if task.assigned_to != completed_by:
            return None
        
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        task.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(task)
        return task
```

**Key Points**:
- `family_id` is ALWAYS the first parameter
- ALL queries include `family_id` filter
- Even `get_by_id` requires `family_id` (security)
- `create` explicitly sets `family_id`
- `update` and `delete` verify family ownership

---

## 3. Service Layer with Family Context

### ✅ Complete Example: Task Service

```python
# backend/app/services/task_service.py
from uuid import UUID
from typing import List, Optional
from datetime import datetime
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse
from app.core.exceptions import (
    NotFoundException,
    PermissionDeniedException,
    ValidationException
)
from app.models.task import TaskStatus

class TaskService:
    """Task service with business logic.
    
    CRITICAL: All methods accept family_id to enforce tenant isolation.
    """
    
    def __init__(
        self,
        task_repo: TaskRepository,
        user_repo: UserRepository
    ):
        self.task_repo = task_repo
        self.user_repo = user_repo
    
    async def get_family_tasks(
        self,
        family_id: UUID,
        status: Optional[TaskStatus] = None,
        assigned_to: Optional[UUID] = None
    ) -> List[TaskResponse]:
        """Get all tasks for a family with optional filters.
        
        Business logic: Transforms domain models to response schemas.
        """
        tasks = await self.task_repo.get_all_by_family(
            family_id=family_id,
            status=status,
            assigned_to=assigned_to
        )
        return [TaskResponse.from_orm(task) for task in tasks]
    
    async def get_task_by_id(
        self,
        family_id: UUID,
        task_id: UUID
    ) -> TaskResponse:
        """Get a specific task by ID.
        
        Business logic: Validates task exists and belongs to family.
        """
        task = await self.task_repo.get_by_id(family_id, task_id)
        if not task:
            raise NotFoundException(
                f"Task {task_id} not found in family {family_id}"
            )
        return TaskResponse.from_orm(task)
    
    async def create_task(
        self,
        family_id: UUID,
        task_create: TaskCreate,
        created_by: UUID
    ) -> TaskResponse:
        """Create a new task.
        
        Business logic: Validates user and family relationship.
        """
        # Validate creator belongs to family
        creator = await self.user_repo.get_by_id(family_id, created_by)
        if not creator:
            raise PermissionDeniedException(
                f"User {created_by} not in family {family_id}"
            )
        
        # Validate assigned user belongs to family
        assigned_user = await self.user_repo.get_by_id(
            family_id,
            task_create.assigned_to
        )
        if not assigned_user:
            raise ValidationException(
                f"Cannot assign task to user outside family"
            )
        
        # Create task
        task_data = task_create.dict()
        task_data["created_by"] = created_by
        
        task = await self.task_repo.create(family_id, task_data)
        return TaskResponse.from_orm(task)
    
    async def complete_task(
        self,
        family_id: UUID,
        task_id: UUID,
        user_id: UUID
    ) -> TaskResponse:
        """Complete a task and award points.
        
        Business logic:
        - Validates user can complete task
        - Awards points
        - Updates task status
        - Creates point transaction record
        """
        # Get task
        task = await self.task_repo.get_by_id(family_id, task_id)
        if not task:
            raise NotFoundException(
                f"Task {task_id} not found in family {family_id}"
            )
        
        # Business rule: Only assigned user can complete
        if task.assigned_to != user_id:
            raise PermissionDeniedException(
                "Can only complete tasks assigned to you"
            )
        
        # Business rule: Can't complete already completed task
        if task.status == TaskStatus.COMPLETED:
            raise ValidationException("Task already completed")
        
        # Complete task
        completed_task = await self.task_repo.complete_task(
            family_id,
            task_id,
            user_id
        )
        
        # Business logic: Award points
        await self._award_points_for_task(
            family_id,
            user_id,
            task_id,
            task.points
        )
        
        return TaskResponse.from_orm(completed_task)
    
    async def _award_points_for_task(
        self,
        family_id: UUID,
        user_id: UUID,
        task_id: UUID,
        points: int
    ) -> None:
        """Internal business logic: Award points for task completion."""
        # Update user points
        user = await self.user_repo.get_by_id(family_id, user_id)
        user.points += points
        await self.user_repo.update(user)
        
        # Create transaction record (implementation in points service)
        # await self.points_service.create_transaction(...)
```

**Key Points**:
- Service methods accept `family_id` first
- Business logic validates family context
- Exceptions include context for debugging
- Internal methods also require `family_id`

---

## 4. API Layer with Family Injection

### ✅ Complete Example: Task API Routes

```python
# backend/app/api/routes/tasks.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from uuid import UUID
from typing import List, Optional
from app.api.dependencies import get_current_user, get_task_service
from app.models.user import User
from app.services.task_service import TaskService
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse
from app.core.exceptions import (
    NotFoundException,
    PermissionDeniedException,
    ValidationException
)
from app.models.task import TaskStatus

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.get("/", response_model=List[TaskResponse])
async def get_tasks(
    status: Optional[TaskStatus] = Query(None, description="Filter by status"),
    assigned_to: Optional[UUID] = Query(None, description="Filter by assigned user"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service)
):
    """Get all tasks for the current user's family.
    
    Family context is automatically injected from authenticated user.
    
    Query Parameters:
        - status: Optional task status filter
        - assigned_to: Optional user ID filter
        
    Returns:
        List of tasks visible to the user's family
    """
    try:
        # Extract family_id from authenticated user (tenant isolation)
        family_id = current_user.family_id
        
        # Pass to service layer
        tasks = await task_service.get_family_tasks(
            family_id=family_id,
            status=status,
            assigned_to=assigned_to
        )
        return tasks
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service)
):
    """Get a specific task by ID.
    
    Automatically verifies task belongs to user's family.
    """
    try:
        task = await task_service.get_task_by_id(
            family_id=current_user.family_id,  # Security boundary
            task_id=task_id
        )
        return task
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_create: TaskCreate,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service)
):
    """Create a new task for the family.
    
    Requires PARENT role (checked in dependency).
    Task automatically associated with user's family.
    """
    try:
        task = await task_service.create_task(
            family_id=current_user.family_id,  # Automatic family association
            task_create=task_create,
            created_by=current_user.id
        )
        return task
    except PermissionDeniedException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service)
):
    """Mark a task as complete and award points.
    
    Validates:
    - Task exists and belongs to user's family
    - User is assigned to the task
    - Task not already completed
    """
    try:
        task = await task_service.complete_task(
            family_id=current_user.family_id,  # Security boundary
            task_id=task_id,
            user_id=current_user.id
        )
        return task
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionDeniedException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service)
):
    """Delete a task.
    
    Requires PARENT role (checked in dependency).
    Validates task belongs to user's family before deletion.
    """
    try:
        await task_service.delete_task(
            family_id=current_user.family_id,  # Security check
            task_id=task_id
        )
        return None
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionDeniedException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
```

**Key Points**:
- Family ID extracted from `current_user.family_id`
- NEVER accept `family_id` as path/query parameter
- Service layer handles all validation
- Exceptions mapped to HTTP status codes
- Clear error messages include context

---

## 5. Testing Tenant Isolation

### ✅ Complete Example: Tenant Isolation Tests

```python
# backend/tests/test_task_tenant_isolation.py
import pytest
from uuid import uuid4
from app.services.task_service import TaskService
from app.models.task import TaskStatus

@pytest.mark.asyncio
async def test_tasks_isolated_between_families(
    task_service: TaskService,
    test_family_1_id: UUID,
    test_family_2_id: UUID,
    test_user_family_1_id: UUID,
    test_user_family_2_id: UUID
):
    """CRITICAL: Verify tasks are completely isolated between families.
    
    This test ensures no data leakage between tenants.
    """
    
    # Create task for family 1
    task_data_f1 = {
        "title": "Family 1 Task",
        "description": "This belongs to family 1",
        "points": 50,
        "assigned_to": test_user_family_1_id,
        "status": TaskStatus.PENDING
    }
    task_f1 = await task_service.create_task(
        family_id=test_family_1_id,
        task_data=task_data_f1
    )
    
    # Create task for family 2
    task_data_f2 = {
        "title": "Family 2 Task",
        "description": "This belongs to family 2",
        "points": 30,
        "assigned_to": test_user_family_2_id,
        "status": TaskStatus.PENDING
    }
    task_f2 = await task_service.create_task(
        family_id=test_family_2_id,
        task_data=task_data_f2
    )
    
    # VERIFY: Family 1 can see only their task
    family_1_tasks = await task_service.get_family_tasks(test_family_1_id)
    assert len(family_1_tasks) == 1
    assert family_1_tasks[0].id == task_f1.id
    assert family_1_tasks[0].title == "Family 1 Task"
    
    # CRITICAL: Verify family 1 CANNOT see family 2's task
    family_1_task_ids = [t.id for t in family_1_tasks]
    assert task_f2.id not in family_1_task_ids
    
    # VERIFY: Family 2 can see only their task
    family_2_tasks = await task_service.get_family_tasks(test_family_2_id)
    assert len(family_2_tasks) == 1
    assert family_2_tasks[0].id == task_f2.id
    assert family_2_tasks[0].title == "Family 2 Task"
    
    # CRITICAL: Verify family 2 CANNOT see family 1's task
    family_2_task_ids = [t.id for t in family_2_tasks]
    assert task_f1.id not in family_2_task_ids
    
    # VERIFY: Direct access with wrong family_id returns None
    task_from_wrong_family = await task_service.get_task_by_id(
        family_id=test_family_2_id,  # Wrong family
        task_id=task_f1.id  # Family 1's task
    )
    assert task_from_wrong_family is None

@pytest.mark.asyncio
async def test_cannot_update_other_family_task(
    task_service: TaskService,
    test_family_1_id: UUID,
    test_family_2_id: UUID,
    test_user_family_1_id: UUID
):
    """CRITICAL: Verify families cannot update other families' tasks."""
    
    # Create task for family 1
    task_data = {
        "title": "Family 1 Task",
        "points": 50,
        "assigned_to": test_user_family_1_id
    }
    task = await task_service.create_task(test_family_1_id, task_data)
    
    # CRITICAL: Attempt to update from family 2 should fail
    result = await task_service.update_task(
        family_id=test_family_2_id,  # Wrong family
        task_id=task.id,
        updates={"title": "Hacked title"}
    )
    
    # Verify update failed
    assert result is None
    
    # Verify original task unchanged
    original_task = await task_service.get_task_by_id(test_family_1_id, task.id)
    assert original_task.title == "Family 1 Task"

@pytest.mark.asyncio
async def test_cannot_delete_other_family_task(
    task_service: TaskService,
    test_family_1_id: UUID,
    test_family_2_id: UUID,
    test_user_family_1_id: UUID
):
    """CRITICAL: Verify families cannot delete other families' tasks."""
    
    # Create task for family 1
    task_data = {
        "title": "Family 1 Task",
        "points": 50,
        "assigned_to": test_user_family_1_id
    }
    task = await task_service.create_task(test_family_1_id, task_data)
    
    # CRITICAL: Attempt to delete from family 2 should fail
    delete_result = await task_service.delete_task(
        family_id=test_family_2_id,  # Wrong family
        task_id=task.id
    )
    
    # Verify deletion failed
    assert delete_result is False
    
    # Verify task still exists for family 1
    existing_task = await task_service.get_task_by_id(test_family_1_id, task.id)
    assert existing_task is not None
    assert existing_task.title == "Family 1 Task"
```

**Key Points**:
- Test MUST verify data visible to owning family
- Test MUST verify data NOT visible to other families
- Test both list operations and direct access
- Test create, read, update, and delete operations
- Use descriptive assertions that explain what's being verified

---

## 6. Authentication & Security (Production Proxy)

When running behind a reverse proxy (e.g., Nginx, Traefik) with HTTPS, special care must be taken with cookies and CSRF protection to avoid **infinite login loops**.

### ✅ Auth Cookie Security Flags

In production, authentication cookies (`access_token`) MUST be configured with:
- `httpOnly: true` - Prevent XSS access
- `secure: true` - **MANDATORY** for HTTPS/Proxy environments. If `false` or conditional, some browsers will reject the cookie when served over a proxy that doesn't propagate the protocol correctly.
- `sameSite: "Lax"` - Standard for cross-site navigation

```typescript
// frontend/src/pages/api/auth/login.ts
const tokenCookie = buildCookie("access_token", result.access_token, {
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
    maxAge: 60 * 60 * 24 * 7,
    secure: true, // ALWAYS true in production behind proxy
});
```

### ✅ CSRF Protection in Middleware

Middleware MUST allow the specific production domain in the `Origin` header check. A common mistake is strictly checking against the internal `host` header, which might differ from the external proxy domain.

```typescript
// frontend/src/middleware.ts
const allowedHosts = ["family.agent-ia.mx", host]; // Include production domain
const originHost = origin.replace(/^https?:\/\//, "");

if (!allowedHosts.includes(originHost)) {
    // Block only if not in allowed list
}
```

### ✅ Backend API URLs

Internal server-side requests (Astro SSR to FastAPI) SHOULD use the **internal Docker network name** (e.g., `http://backend:8000`) instead of the public URL to avoid unnecessary round-trips and potential DNS/Proxy issues.

```typescript
// Use internal backend URL for server-side requests
const apiUrl = process.env.API_BASE_URL || "http://backend:8000";
```

---

## 🚫 Common Mistakes

### Mistake 4: Conditional `secure` flag based on `import.meta.env.PROD`
Behind some proxies, `import.meta.env.PROD` might be true but the cookie still fails if the proxy-client handshake is HTTPS but the proxy-server is HTTP. **Fix**: Force `secure: true` if the site is intended for HTTPS.

### Mistake 5: Rigid CSRF check in Middleware
❌ **WRONG**: `if (origin !== \`https://\${host}\`)` - This fails if `host` is "localhost:3000" but `origin` is "https://family.agent-ia.mx".
✅ **CORRECT**: Use an allowed list of hosts including the production domain.

---

## 📚 Summary

**Multi-Tenant Rules** (MANDATORY):
1. Models: Every family-owned entity has `family_id` NOT NULL with index
2. Repository: ALL methods accept `family_id` first, ALL queries filter by it
3. Service: ALL methods accept `family_id` first
4. API: Extract `family_id` from `current_user.family_id`, NEVER from request
5. Tests: MUST verify tenant isolation (data not visible to other families)

Violating these rules creates **critical security vulnerabilities**.

For more patterns, see:
- `.github/memory-bank/systemPatterns.md` - Code examples
- `.github/instructions/02-clean-architecture.md` - Architecture layers
- `.github/instructions/04-testing-standards.md` - Testing patterns
