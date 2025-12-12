---
applyTo: "app/services/**/*.py,app/models/**/*.py,app/schemas/**/*.py,app/api/**/*.py,app/core/**/*.py"
---

# Backend Logic & Business Rules Guidelines

## 🚨 MANDATORY: Code Quality and Maintenance Rules

### 🧹 **MANDATORY: Garbage Collection Rule**

**WHEN making ANY code changes, you MUST clean up deprecated/unused code:**

1. **🔍 Identify Deprecated Code**: Look for unused imports, functions, classes, variables
2. **🗑️ Remove Dead Code**: Delete commented-out code blocks, unused methods, redundant patterns
3. **📝 Clean Imports**: Remove unused imports and organize them properly
4. **🔄 Refactor Duplicates**: Consolidate duplicate logic into reusable functions
5. **📚 Update Documentation**: Remove references to deleted features, update examples

### 📖 **MANDATORY: Documentation Maintenance Rule**

**WHEN making ANY behavioral or component changes, you MUST maintain GitHub Copilot instructions:**

1. **📋 Read Current Instructions**: Review `.github/copilot-instructions.md` for affected sections
2. **🔄 Update Implementation Details**: Modify sections that describe changed behavior
3. **➕ Add New Patterns**: Document new components, services, or architectural decisions
4. **🗑️ Remove Obsolete Guidance**: Delete instructions for deprecated features or patterns
5. **✅ Verify Accuracy**: Ensure instructions match actual codebase implementation
6. **📝 Document Lessons Learned**: Add critical fixes, common pitfalls, or important discoveries

## 🎯 Core Business Logic Rules

### Task Management

**Default Tasks vs Extra Tasks**:
```python
# ALWAYS check is_default flag before allowing access to extra tasks
async def can_access_extra_tasks(user_id: UUID, family_id: UUID) -> bool:
    """Check if user has completed all default tasks for today"""
    default_tasks = await get_default_tasks_for_today(user_id, family_id)
    completed = [t for t in default_tasks if t.status == TaskStatus.COMPLETED]
    return len(completed) == len(default_tasks)
```

**Task Completion Logic**:
```python
# ALWAYS award points when task is completed
# ALWAYS log transaction for audit trail
# ALWAYS check for consequence removal if it was a default task

async def complete_task(task_id: UUID, user_id: UUID) -> TaskCompletionResult:
    task = await get_task(task_id)
    
    # Validate ownership
    if task.assigned_to != user_id:
        raise PermissionDeniedError("Task not assigned to this user")
    
    # Mark as completed
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    
    # Award points
    user = await get_user(user_id)
    user.points += task.points
    
    # Log transaction
    transaction = PointTransaction(
        user_id=user_id,
        task_id=task_id,
        points=task.points,
        transaction_type=TransactionType.TASK_COMPLETION,
        timestamp=datetime.utcnow()
    )
    await save_transaction(transaction)
    
    # Check consequence removal
    if task.is_default and task.consequence_id:
        await resolve_consequence(task.consequence_id)
    
    return TaskCompletionResult(task=task, points_awarded=task.points)
```

### Points & Rewards System

**Reward Redemption Logic**:
```python
# ALWAYS verify sufficient points
# ALWAYS check no active consequences
# ALWAYS deduct points and log transaction
# ALWAYS require parent approval for high-value rewards

async def redeem_reward(
    reward_id: UUID, 
    user_id: UUID,
    parent_id: Optional[UUID] = None
) -> RedemptionResult:
    reward = await get_reward(reward_id)
    user = await get_user(user_id)
    
    # Check sufficient points
    if user.points < reward.points_cost:
        raise InsufficientPointsError(
            f"Need {reward.points_cost} points, have {user.points}"
        )
    
    # Check active consequences
    active_consequences = await get_active_consequences(user_id)
    if active_consequences and ConsequenceType.REWARDS_BLOCKED in [c.restriction_type for c in active_consequences]:
        raise ConsequenceActiveError("Cannot redeem rewards with active consequences")
    
    # Check parent approval for high-value rewards
    if reward.points_cost >= 100 and not parent_id:
        return RedemptionResult(
            status=RedemptionStatus.PENDING_APPROVAL,
            reward=reward,
            requires_parent_approval=True
        )
    
    # Deduct points
    user.points -= reward.points_cost
    
    # Log transaction
    transaction = PointTransaction(
        user_id=user_id,
        reward_id=reward_id,
        points=-reward.points_cost,
        transaction_type=TransactionType.REWARD_REDEMPTION,
        approved_by=parent_id,
        timestamp=datetime.utcnow()
    )
    await save_transaction(transaction)
    
    return RedemptionResult(
        status=RedemptionStatus.SUCCESS,
        reward=reward,
        remaining_points=user.points
    )
```

### Consequence System

**Consequence Triggering**:
```python
# ALWAYS trigger consequences when default tasks are overdue
# ALWAYS check daily/weekly for missed default tasks
# ALWAYS notify parents when consequence is triggered

async def check_and_trigger_consequences(user_id: UUID, family_id: UUID):
    """Background job to check for overdue default tasks"""
    default_tasks = await get_default_tasks(user_id, family_id)
    overdue_tasks = [
        t for t in default_tasks 
        if t.status != TaskStatus.COMPLETED and t.due_date < datetime.utcnow()
    ]
    
    if overdue_tasks:
        for task in overdue_tasks:
            consequence = Consequence(
                title=f"Missed task: {task.title}",
                description=f"You didn't complete your default task on time",
                severity=ConsequenceSeverity.MEDIUM,
                restriction_type=RestrictionType.SCREEN_TIME,
                duration_days=1,
                triggered_by_task=task.id,
                user_id=user_id,
                active=True,
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow() + timedelta(days=1)
            )
            await save_consequence(consequence)
            
            # Notify parents
            await notify_parents(
                family_id=family_id,
                message=f"{user.name} has a new consequence for missing {task.title}"
            )
```

**Consequence Resolution**:
```python
# ALWAYS allow manual resolution by parents
# ALWAYS auto-resolve when duration expires
# ALWAYS log resolution event

async def resolve_consequence(consequence_id: UUID, resolved_by: Optional[UUID] = None):
    consequence = await get_consequence(consequence_id)
    
    if not consequence.active:
        raise ConsequenceAlreadyResolvedError()
    
    consequence.active = False
    consequence.resolved_at = datetime.utcnow()
    consequence.resolved_by = resolved_by
    
    await save_consequence(consequence)
    
    # Notify user
    await notify_user(
        user_id=consequence.user_id,
        message="Your consequence has been resolved! You can now access all features."
    )
```

### Family & User Management

**Role-Based Access Control**:
```python
# ALWAYS check user role before allowing operations
# PARENTS can: create/edit tasks, create rewards, approve redemptions, resolve consequences
# CHILDREN can: complete tasks, request rewards
# TEENS can: complete tasks, request rewards, self-assign extra tasks

def require_parent_role(current_user: User = Depends(get_current_user)):
    """Dependency for parent-only endpoints"""
    if current_user.role != UserRole.PARENT:
        raise HTTPException(
            status_code=403, 
            detail="This operation requires parent privileges"
        )
    return current_user

def require_teen_or_parent(current_user: User = Depends(get_current_user)):
    """Dependency for teen/parent operations"""
    if current_user.role not in [UserRole.TEEN, UserRole.PARENT]:
        raise HTTPException(
            status_code=403,
            detail="This operation requires teen or parent privileges"
        )
    return current_user
```

**Family Isolation**:
```python
# ALWAYS filter by family_id to prevent cross-family data access
# ALWAYS validate user belongs to family before operations

async def get_family_tasks(
    family_id: UUID,
    current_user: User = Depends(get_current_user)
) -> List[Task]:
    # Verify user belongs to this family
    if current_user.family_id != family_id:
        raise ForbiddenError("You don't have access to this family")
    
    tasks = await db.query(Task).filter(
        Task.family_id == family_id
    ).all()
    
    return tasks
```

## Database Operations

### Transaction Management

**ALWAYS use database transactions for multi-step operations**:
```python
from sqlalchemy.ext.asyncio import AsyncSession

async def transfer_points(
    from_user_id: UUID,
    to_user_id: UUID,
    points: int,
    session: AsyncSession
):
    """Transfer points between users (atomic operation)"""
    async with session.begin():
        from_user = await session.get(User, from_user_id)
        to_user = await session.get(User, to_user_id)
        
        if from_user.points < points:
            raise InsufficientPointsError()
        
        from_user.points -= points
        to_user.points += points
        
        # Log both transactions
        await session.add(PointTransaction(
            user_id=from_user_id,
            points=-points,
            transaction_type=TransactionType.TRANSFER_OUT
        ))
        await session.add(PointTransaction(
            user_id=to_user_id,
            points=points,
            transaction_type=TransactionType.TRANSFER_IN
        ))
```

### Query Optimization

**ALWAYS use eager loading for related data**:
```python
from sqlalchemy.orm import selectinload

async def get_user_with_tasks(user_id: UUID) -> User:
    """Efficiently load user with all related tasks"""
    result = await db.execute(
        select(User)
        .options(selectinload(User.tasks))
        .filter(User.id == user_id)
    )
    return result.scalar_one()
```

## Error Handling

### Custom Exceptions

```python
# Define domain-specific exceptions
class FamilyAppException(Exception):
    """Base exception for all family app errors"""
    pass

class InsufficientPointsError(FamilyAppException):
    """Raised when user doesn't have enough points"""
    pass

class ConsequenceActiveError(FamilyAppException):
    """Raised when trying to perform action while under consequence"""
    pass

class PermissionDeniedError(FamilyAppException):
    """Raised when user doesn't have permission for operation"""
    pass
```

### Exception Handlers

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(InsufficientPointsError)
async def insufficient_points_handler(request: Request, exc: InsufficientPointsError):
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "error": {
                "code": "INSUFFICIENT_POINTS",
                "message": str(exc)
            }
        }
    )

@app.exception_handler(ConsequenceActiveError)
async def consequence_active_handler(request: Request, exc: ConsequenceActiveError):
    return JSONResponse(
        status_code=403,
        content={
            "success": False,
            "error": {
                "code": "CONSEQUENCE_ACTIVE",
                "message": str(exc)
            }
        }
    )
```

## Validation & Data Integrity

### Pydantic Schemas

**ALWAYS validate input data with Pydantic**:
```python
from pydantic import BaseModel, Field, validator

class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=100)
    description: str = Field(..., max_length=500)
    points: int = Field(..., ge=1, le=1000)
    is_default: bool = False
    frequency: TaskFrequency
    assigned_to: UUID
    due_date: datetime
    
    @validator('due_date')
    def due_date_must_be_future(cls, v):
        if v < datetime.utcnow():
            raise ValueError('Due date must be in the future')
        return v
    
    @validator('points')
    def points_must_be_reasonable(cls, v, values):
        # Default tasks should have lower points
        if values.get('is_default') and v > 50:
            raise ValueError('Default tasks should have 50 points or less')
        return v
```

## Background Jobs

### Scheduled Tasks

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=23, minute=59)
async def daily_consequence_check():
    """Run at end of day to check for incomplete default tasks"""
    all_families = await get_all_families()
    
    for family in all_families:
        users = await get_family_members(family.id)
        for user in users:
            if user.role == UserRole.CHILD or user.role == UserRole.TEEN:
                await check_and_trigger_consequences(user.id, family.id)

@scheduler.scheduled_job('cron', hour=0, minute=0)
async def reset_daily_tasks():
    """Reset daily tasks at midnight"""
    await reset_all_daily_tasks()
```

## Testing Guidelines

### Service Layer Tests

```python
import pytest
from datetime import datetime, timedelta

@pytest.mark.asyncio
async def test_complete_task_awards_points(db_session):
    # Setup
    user = await create_test_user(points=0)
    task = await create_test_task(
        assigned_to=user.id,
        points=50,
        is_default=True
    )
    
    # Execute
    result = await complete_task(task.id, user.id)
    
    # Assert
    assert result.task.status == TaskStatus.COMPLETED
    assert result.points_awarded == 50
    
    updated_user = await get_user(user.id)
    assert updated_user.points == 50
    
    transactions = await get_user_transactions(user.id)
    assert len(transactions) == 1
    assert transactions[0].points == 50

@pytest.mark.asyncio
async def test_cannot_redeem_reward_with_insufficient_points(db_session):
    # Setup
    user = await create_test_user(points=50)
    reward = await create_test_reward(points_cost=100)
    
    # Execute & Assert
    with pytest.raises(InsufficientPointsError):
        await redeem_reward(reward.id, user.id)
```

## Performance Optimization

### Caching Strategies

```python
from functools import lru_cache
import redis.asyncio as redis

# Cache family configurations
@lru_cache(maxsize=100)
async def get_family_config(family_id: UUID) -> FamilyConfig:
    return await db.query(FamilyConfig).filter(
        FamilyConfig.family_id == family_id
    ).first()

# Redis caching for frequently accessed data
async def get_user_points(user_id: UUID) -> int:
    """Get user points with Redis caching"""
    cache_key = f"user_points:{user_id}"
    
    # Try cache first
    cached_points = await redis_client.get(cache_key)
    if cached_points:
        return int(cached_points)
    
    # Fallback to database
    user = await get_user(user_id)
    await redis_client.setex(cache_key, 300, user.points)  # Cache for 5 minutes
    return user.points
```

## Security Best Practices

### Password Management

```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """ALWAYS hash passwords before storing"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)
```

### Input Sanitization

```python
from bleach import clean

def sanitize_html_input(text: str) -> str:
    """Remove potentially dangerous HTML/JS"""
    return clean(text, tags=[], strip=True)
```

---

**Last Updated**: December 11, 2025
