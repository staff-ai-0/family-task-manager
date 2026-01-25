# System Patterns

**Purpose**: Established code patterns with complete, copy-paste-able examples from the Family Task Manager codebase.

**Last Updated**: January 25, 2026

---

## Multi-Tenant Patterns (Family-Based Isolation)

### Pattern 1: Entity with Family ID

**When to use**: Every model that stores family-specific data

**Rule**: MUST have `family_id` foreign key, MUST NOT be nullable

**Code Example**:
```python
from sqlalchemy import ForeignKey, String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID, uuid4
from app.core.database import Base

class Task(Base):
    __tablename__ = "tasks"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    
    # CRITICAL: Family isolation
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Task data
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    points: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    
    # Relationships
    family: Mapped["Family"] = relationship(back_populates="tasks")
    assigned_user: Mapped["User"] = relationship(back_populates="assigned_tasks")
```

**Key Points**:
- `family_id` is always NOT NULL
- Index on `family_id` for query performance
- CASCADE delete removes all family data when family is deleted
- Relationship to Family model for eager loading

---

### Pattern 2: Repository with Family Filtering

**When to use**: ALL repository methods that query family data

**Rule**: First parameter MUST be `family_id: UUID`, ALL queries MUST filter by `family_id`

**Code Example**:
```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import List
from app.models.task import Task

class TaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_all_by_family(
        self,
        family_id: UUID,
        status: str | None = None,
        assigned_to: UUID | None = None
    ) -> List[Task]:
        """Get all tasks for a specific family with optional filters.
        
        CRITICAL: Always filters by family_id for tenant isolation.
        """
        query = select(Task).where(Task.family_id == family_id)
        
        if status:
            query = query.where(Task.status == status)
        
        if assigned_to:
            query = query.where(Task.assigned_to == assigned_to)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(self, family_id: UUID, task_id: UUID) -> Task | None:
        """Get a specific task, ensuring it belongs to the family.
        
        CRITICAL: Both family_id and task_id required for security.
        """
        query = select(Task).where(
            Task.id == task_id,
            Task.family_id == family_id  # Security check
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def create(self, family_id: UUID, task_data: dict) -> Task:
        """Create a new task for a specific family."""
        task = Task(
            family_id=family_id,  # Always set family_id
            **task_data
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task
```

**Key Points**:
- `family_id` is ALWAYS the first parameter
- NEVER query without family_id filtering
- Even get_by_id includes family_id check (security)
- Create methods explicitly set family_id

---

### Pattern 3: Service Layer with Family Context

**When to use**: All service methods that handle business logic

**Rule**: Accept `family_id: UUID` as first parameter, pass to repository

**Code Example**:
```python
from uuid import UUID
from typing import List
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskResponse
from app.core.exceptions import NotFoundException, PermissionDeniedException

class TaskService:
    def __init__(self, task_repo: TaskRepository):
        self.task_repo = task_repo
    
    async def get_family_tasks(
        self,
        family_id: UUID,
        status: str | None = None
    ) -> List[TaskResponse]:
        """Get all tasks for a family with optional status filter.
        
        Business logic: Filters and transforms tasks for response.
        """
        tasks = await self.task_repo.get_all_by_family(
            family_id=family_id,
            status=status
        )
        return [TaskResponse.from_orm(task) for task in tasks]
    
    async def complete_task(
        self,
        family_id: UUID,
        task_id: UUID,
        user_id: UUID
    ) -> TaskResponse:
        """Complete a task and award points.
        
        Business logic: Validates permissions, awards points, updates status.
        """
        # Get task with family_id check
        task = await self.task_repo.get_by_id(family_id, task_id)
        if not task:
            raise NotFoundException(f"Task {task_id} not found in family {family_id}")
        
        # Validate user can complete this task
        if task.assigned_to != user_id:
            raise PermissionDeniedException("Can only complete your own tasks")
        
        # Update task status
        task.status = "COMPLETED"
        task.completed_at = datetime.utcnow()
        
        # Award points (business logic)
        await self._award_points(family_id, user_id, task.points)
        
        await self.task_repo.update(task)
        return TaskResponse.from_orm(task)
    
    async def _award_points(
        self,
        family_id: UUID,
        user_id: UUID,
        points: int
    ) -> None:
        """Internal method to award points (business logic)."""
        # Implementation here
        pass
```

**Key Points**:
- Service methods accept family_id first
- Business logic validates family context
- Exceptions include family context for debugging
- Internal methods also accept family_id

---

### Pattern 4: API Route with Family Injection

**When to use**: All API endpoints that access family data

**Rule**: Extract family_id from current user, pass to service

**Code Example**:
```python
from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from typing import List
from app.api.dependencies import get_current_user, get_task_service
from app.models.user import User
from app.services.task_service import TaskService
from app.schemas.task import TaskResponse, TaskCreate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.get("/", response_model=List[TaskResponse])
async def get_tasks(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service)
):
    """Get all tasks for the current user's family.
    
    Family context is injected from authenticated user.
    """
    # Extract family_id from current user (multi-tenant isolation)
    family_id = current_user.family_id
    
    # Pass to service layer
    tasks = await task_service.get_family_tasks(
        family_id=family_id,
        status=status
    )
    return tasks

@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service)
):
    """Mark a task as complete and award points.
    
    Validates that task belongs to user's family.
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
```

**Key Points**:
- Family ID comes from `current_user.family_id`
- NEVER accept family_id as query/path parameter
- Service layer handles family validation
- Exceptions mapped to appropriate HTTP status codes

---

## Clean Architecture Patterns

### Pattern 5: Layer Separation

**API Layer** → HTTP concerns only, no business logic
**Service Layer** → Business rules, orchestration
**Repository Layer** → Database queries only
**Models Layer** → Database entities

**Code Example (Complete Flow)**:

```python
# ============= MODELS LAYER =============
# backend/app/models/reward.py
from sqlalchemy import String, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID, uuid4
from app.core.database import Base

class Reward(Base):
    __tablename__ = "rewards"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(ForeignKey("families.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200))
    points_cost: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    family: Mapped["Family"] = relationship(back_populates="rewards")


# ============= REPOSITORY LAYER =============
# backend/app/repositories/reward_repository.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import List
from app.models.reward import Reward

class RewardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_active_rewards(self, family_id: UUID) -> List[Reward]:
        """Database query only - no business logic."""
        query = select(Reward).where(
            Reward.family_id == family_id,
            Reward.is_active == True
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def create(self, family_id: UUID, reward_data: dict) -> Reward:
        """Create reward - no business logic."""
        reward = Reward(family_id=family_id, **reward_data)
        self.db.add(reward)
        await self.db.commit()
        await self.db.refresh(reward)
        return reward


# ============= SERVICE LAYER =============
# backend/app/services/reward_service.py
from uuid import UUID
from typing import List
from app.repositories.reward_repository import RewardRepository
from app.repositories.user_repository import UserRepository
from app.schemas.reward import RewardResponse, RewardCreate
from app.core.exceptions import InsufficientPointsException

class RewardService:
    def __init__(
        self,
        reward_repo: RewardRepository,
        user_repo: UserRepository
    ):
        self.reward_repo = reward_repo
        self.user_repo = user_repo
    
    async def get_available_rewards(
        self,
        family_id: UUID,
        user_id: UUID
    ) -> List[RewardResponse]:
        """Business logic: Get rewards user can afford."""
        rewards = await self.reward_repo.get_active_rewards(family_id)
        user = await self.user_repo.get_by_id(family_id, user_id)
        
        # Business logic: Mark which rewards are affordable
        return [
            RewardResponse.from_orm(reward, can_afford=(reward.points_cost <= user.points))
            for reward in rewards
        ]
    
    async def redeem_reward(
        self,
        family_id: UUID,
        user_id: UUID,
        reward_id: UUID
    ) -> dict:
        """Business logic: Validate and process redemption."""
        reward = await self.reward_repo.get_by_id(family_id, reward_id)
        user = await self.user_repo.get_by_id(family_id, user_id)
        
        # Business rule: Check sufficient points
        if user.points < reward.points_cost:
            raise InsufficientPointsException(
                f"Need {reward.points_cost}, have {user.points}"
            )
        
        # Business logic: Deduct points
        user.points -= reward.points_cost
        await self.user_repo.update(user)
        
        # Business logic: Create transaction record
        await self._create_transaction_record(
            family_id, user_id, reward_id, -reward.points_cost
        )
        
        return {"success": True, "remaining_points": user.points}


# ============= API LAYER =============
# backend/app/api/routes/rewards.py
from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from typing import List
from app.api.dependencies import get_current_user, get_reward_service
from app.models.user import User
from app.services.reward_service import RewardService
from app.schemas.reward import RewardResponse
from app.core.exceptions import InsufficientPointsException

router = APIRouter(prefix="/api/rewards", tags=["rewards"])

@router.get("/", response_model=List[RewardResponse])
async def get_rewards(
    current_user: User = Depends(get_current_user),
    reward_service: RewardService = Depends(get_reward_service)
):
    """HTTP endpoint - delegates to service layer."""
    rewards = await reward_service.get_available_rewards(
        family_id=current_user.family_id,
        user_id=current_user.id
    )
    return rewards

@router.post("/{reward_id}/redeem")
async def redeem_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    reward_service: RewardService = Depends(get_reward_service)
):
    """HTTP endpoint - handles HTTP concerns only."""
    try:
        result = await reward_service.redeem_reward(
            family_id=current_user.family_id,
            user_id=current_user.id,
            reward_id=reward_id
        )
        return result
    except InsufficientPointsException as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
```

**Key Points**:
- Models: Database schema only
- Repository: Queries only, no business logic
- Service: Business rules, orchestration, validation
- API: HTTP concerns, status codes, auth

---

## Testing Patterns

### Pattern 6: Tenant Isolation Test

**When to use**: EVERY test that creates family-specific data

**Rule**: MUST verify data visible to owning family, NOT visible to other families

**Code Example**:
```python
import pytest
from uuid import uuid4
from app.services.task_service import TaskService

@pytest.mark.asyncio
async def test_task_isolation_between_families(
    task_service: TaskService,
    test_family_1: UUID,
    test_family_2: UUID,
    test_user_family_1: UUID
):
    """CRITICAL: Verify tasks are isolated between families."""
    
    # Create task for family 1
    task_data = {
        "title": "Family 1 Task",
        "points": 50,
        "assigned_to": test_user_family_1
    }
    task = await task_service.create_task(test_family_1, task_data)
    
    # Verify task visible to family 1
    family_1_tasks = await task_service.get_family_tasks(test_family_1)
    assert len(family_1_tasks) == 1
    assert family_1_tasks[0].id == task.id
    
    # CRITICAL: Verify task NOT visible to family 2
    family_2_tasks = await task_service.get_family_tasks(test_family_2)
    assert len(family_2_tasks) == 0
    
    # Verify direct access from family 2 fails
    task_from_family_2 = await task_service.get_task(test_family_2, task.id)
    assert task_from_family_2 is None
```

**Key Points**:
- Create data for family 1
- Verify visible to family 1
- **CRITICAL**: Verify NOT visible to family 2
- Test both list and direct access

---

## Type Safety Patterns (SQLAlchemy 2.0)

### Pattern 7: Proper Type Conversion

**When to use**: Passing SQLAlchemy Column objects to service methods

**Rule**: Convert Column types to Python types explicitly

**Code Example**:
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.models.user import User

# ❌ WRONG: Passing Column object directly
async def get_user_wrong(db: AsyncSession, user_id: UUID):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    # This will cause type errors if user.id is passed to typed methods
    return user.id  # Type: Column[UUID], not UUID

# ✅ CORRECT: Explicit type conversion
async def get_user_correct(db: AsyncSession, user_id: UUID) -> UUID:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    # Convert to Python type explicitly
    return UUID(str(user.id))  # Type: UUID

# ✅ BEST: Use Mapped[] syntax in models
class User(Base):
    __tablename__ = "users"
    
    # This automatically provides proper type hints
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(ForeignKey("families.id"))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
```

**Key Points**:
- Use `Mapped[]` syntax in all models
- Explicit type conversion when passing to service methods
- See `.github/instructions/04-python-type-safety.instructions.md`

---

## Summary

These patterns are **mandatory** for all new code:

1. **Multi-tenant**: Every entity has `family_id`, every query filters by `family_id`
2. **Clean Architecture**: API → Service → Repository → Models
3. **Tenant Isolation Tests**: Every test verifies data isolation
4. **Type Safety**: Use `Mapped[]` syntax, explicit conversions

For detailed implementation guides, see:
- `.github/instructions/01-multi-tenant-patterns.md`
- `.github/instructions/02-clean-architecture.md`
- `.github/instructions/03-domain-driven-design.md`
- `.github/instructions/04-testing-standards.md`
- `.github/instructions/04-python-type-safety.instructions.md`
