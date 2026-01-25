# IMPLEMENTATION PLAN - CODE IMPROVEMENTS
## Family Task Manager Refactoring Guide

**Based on:** FORENSIC_CODE_REVIEW.md  
**Start Date:** January 23, 2026  
**Estimated Duration:** 4-8 weeks (depending on team capacity)

---

## QUICK START GUIDE

### Prerequisites

1. Read `FORENSIC_CODE_REVIEW.md` for full context
2. Create feature branch: `git checkout -b refactor/code-consolidation`
3. Ensure all tests pass: `pytest`
4. Back up database (if applying to production)

### Implementation Order

Follow phases in order. Each phase is independently deployable.

---

## PHASE 1: QUICK WINS (WEEK 1-2)

**Goal:** Eliminate 200+ lines of duplicate exception handling and authorization checks  
**Risk Level:** LOW  
**Estimated Time:** 9 hours

### Task 1.1: Global Exception Handlers (2 hours)

**File:** `app/core/exception_handlers.py` (NEW)

```python
"""
Global exception handlers for FastAPI application.
Eliminates the need for try-catch blocks in route handlers.
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from typing import Dict, Any

from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ForbiddenException,
    UnauthorizedException,
    InsufficientPointsError,
    ConsequenceActiveError,
    TaskAlreadyCompletedError,
)


def create_error_response(
    status_code: int,
    message: str,
    error_type: str,
    details: Dict[str, Any] = None
) -> JSONResponse:
    """Create standardized error response"""
    content = {
        "error": error_type,
        "message": message,
        "status_code": status_code
    }
    if details:
        content["details"] = details
    
    return JSONResponse(
        status_code=status_code,
        content=content
    )


async def not_found_handler(request: Request, exc: NotFoundException) -> JSONResponse:
    """Handle 404 Not Found errors"""
    return create_error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        message=str(exc),
        error_type="not_found"
    )


async def validation_handler(request: Request, exc: ValidationException) -> JSONResponse:
    """Handle 400 Bad Request validation errors"""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=str(exc),
        error_type="validation_error"
    )


async def forbidden_handler(request: Request, exc: ForbiddenException) -> JSONResponse:
    """Handle 403 Forbidden errors"""
    return create_error_response(
        status_code=status.HTTP_403_FORBIDDEN,
        message=str(exc),
        error_type="forbidden"
    )


async def unauthorized_handler(request: Request, exc: UnauthorizedException) -> JSONResponse:
    """Handle 401 Unauthorized errors"""
    return create_error_response(
        status_code=status.HTTP_401_UNAUTHORIZED,
        message=str(exc),
        error_type="unauthorized",
        details={"www_authenticate": "Bearer"}
    )


async def insufficient_points_handler(
    request: Request, 
    exc: InsufficientPointsError
) -> JSONResponse:
    """Handle insufficient points errors"""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=str(exc),
        error_type="insufficient_points"
    )


async def consequence_active_handler(
    request: Request, 
    exc: ConsequenceActiveError
) -> JSONResponse:
    """Handle active consequence restriction errors"""
    return create_error_response(
        status_code=status.HTTP_403_FORBIDDEN,
        message=str(exc),
        error_type="consequence_active"
    )


async def task_already_completed_handler(
    request: Request,
    exc: TaskAlreadyCompletedError
) -> JSONResponse:
    """Handle task already completed errors"""
    return create_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=str(exc),
        error_type="task_already_completed"
    )


def register_exception_handlers(app):
    """Register all exception handlers with FastAPI app"""
    app.add_exception_handler(NotFoundException, not_found_handler)
    app.add_exception_handler(ValidationException, validation_handler)
    app.add_exception_handler(ForbiddenException, forbidden_handler)
    app.add_exception_handler(UnauthorizedException, unauthorized_handler)
    app.add_exception_handler(InsufficientPointsError, insufficient_points_handler)
    app.add_exception_handler(ConsequenceActiveError, consequence_active_handler)
    app.add_exception_handler(TaskAlreadyCompletedError, task_already_completed_handler)
```

**Update:** `app/main.py`

```python
from app.core.exception_handlers import register_exception_handlers

app = FastAPI(title="Family Task Manager")

# Register exception handlers
register_exception_handlers(app)
```

**Testing:**
```bash
pytest tests/test_exception_handlers.py -v
```

**Rollout:**
1. Add exception handlers
2. Test manually with Postman/curl
3. Update one route file as proof of concept
4. If successful, update remaining route files
5. Remove all try-catch blocks

**Success Criteria:**
- All routes work without try-catch blocks
- Error responses are consistent
- Tests pass

---

### Task 1.2: Family Authorization Dependency (2 hours)

**Update:** `app/core/dependencies.py`

Add these functions at the end:

```python
async def verify_family_access(
    resource_family_id: UUID,
    current_user: User = Depends(get_current_user)
) -> None:
    """
    Verify user has access to family-scoped resource.
    
    Raises:
        ForbiddenException: If user doesn't belong to resource's family
    """
    if resource_family_id != current_user.family_id:
        raise ForbiddenException(
            "Access denied: resource belongs to different family"
        )


async def get_family_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Get user and verify family membership.
    
    Args:
        user_id: User ID to fetch
        current_user: Currently authenticated user
        db: Database session
        
    Returns:
        User object if found and in same family
        
    Raises:
        NotFoundException: If user not found
        ForbiddenException: If user not in same family
    """
    from app.services import AuthService
    
    user = await AuthService.get_user_by_id(db, user_id)
    await verify_family_access(user.family_id, current_user)
    return user


async def verify_family_id(
    family_id: UUID,
    current_user: User = Depends(get_current_user)
) -> UUID:
    """
    Verify family ID matches current user's family.
    
    Raises:
        ForbiddenException: If family_id doesn't match
    """
    if family_id != current_user.family_id:
        raise ForbiddenException("You can only access your own family")
    return family_id
```

**Example Usage - Update:** `app/api/routes/users.py`

```python
# BEFORE (lines 39-56):
@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user by ID (must be in same family)"""
    try:
        user = await AuthService.get_user_by_id(db, user_id)
        # Verify same family
        if user.family_id != current_user.family_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only access users in your family"
            )
        return user
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

# AFTER:
@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user: User = Depends(get_family_user)):
    """Get user by ID (must be in same family)"""
    return user
```

**Files to Update:**
1. `app/api/routes/users.py` - 4 endpoints
2. `app/api/routes/families.py` - 4 endpoints

**Testing:**
```bash
pytest tests/test_dependencies.py::test_family_authorization -v
```

---

### Task 1.3: Base Pydantic Schemas (3 hours)

**File:** `app/schemas/base.py` (NEW)

```python
"""
Base Pydantic schemas for consistent response structure.
Reduces duplication across all schema files.
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID


class TimestampMixin(BaseModel):
    """Mixin for created_at/updated_at timestamps"""
    created_at: datetime
    updated_at: datetime


class BaseResponse(BaseModel):
    """Base response schema with ORM configuration"""
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=False,
        str_strip_whitespace=True,
    )


class EntityResponse(BaseResponse, TimestampMixin):
    """
    Base for entity responses with ID and timestamps.
    Use for any entity that has id, created_at, updated_at.
    """
    id: UUID


class FamilyEntityResponse(EntityResponse):
    """
    Base for family-scoped entity responses.
    Use for entities that belong to a family.
    """
    family_id: UUID


class TitleDescriptionMixin(BaseModel):
    """Mixin for entities with title and description fields"""
    title: str
    description: str | None = None


class MessageResponse(BaseModel):
    """Standard message response"""
    message: str
    success: bool = True
```

**Update Schemas to Use Base Classes:**

**Example:** `app/schemas/task.py`

```python
# BEFORE (lines 54-68):
class TaskResponse(TaskBase):
    """Schema for task response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    status: TaskStatus
    assigned_to: UUID
    created_by: Optional[UUID]
    family_id: UUID
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    consequence_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

# AFTER:
from app.schemas.base import FamilyEntityResponse

class TaskResponse(TaskBase, FamilyEntityResponse):
    """Schema for task response"""
    status: TaskStatus
    assigned_to: UUID
    created_by: Optional[UUID]
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    consequence_id: Optional[UUID] = None
```

**Files to Update:**
1. `app/schemas/user.py` - UserResponse
2. `app/schemas/task.py` - TaskResponse
3. `app/schemas/reward.py` - RewardResponse
4. `app/schemas/consequence.py` - ConsequenceResponse
5. `app/schemas/points.py` - PointTransactionResponse
6. `app/schemas/family.py` - FamilyResponse

**Testing:**
```bash
pytest tests/test_schemas.py -v
```

---

### Task 1.4: Validation Constants (2 hours)

**File:** `app/schemas/validation.py` (NEW)

```python
"""
Validation constants and field factories.
Centralizes all validation limits for consistency.
"""
from pydantic import Field
from typing import Optional


class Limits:
    """Validation limits for all schemas"""
    
    # String lengths
    TITLE_MIN = 1
    TITLE_MAX = 200
    NAME_MIN = 1
    NAME_MAX = 100
    DESCRIPTION_MAX = 1000
    EMAIL_MAX = 255
    PASSWORD_MIN = 8
    PASSWORD_MAX = 100
    REASON_MIN = 1
    REASON_MAX = 500
    ICON_MAX = 50
    
    # Numeric ranges
    TASK_POINTS_MIN = 0
    TASK_POINTS_MAX = 1000
    REWARD_POINTS_MIN = 1
    REWARD_POINTS_MAX = 10000
    ADJUSTMENT_POINTS_MIN = -1000
    ADJUSTMENT_POINTS_MAX = 1000
    TRANSFER_POINTS_MIN = 1
    TRANSFER_POINTS_MAX = 1000
    CONSEQUENCE_DAYS_MIN = 1
    CONSEQUENCE_DAYS_MAX = 30
    
    # List/Query limits
    TRANSACTION_HISTORY_LIMIT = 50
    LIST_DEFAULT_LIMIT = 100
    LIST_MAX_LIMIT = 500


class ErrorMessages:
    """Standard error messages"""
    TITLE_TOO_SHORT = f"Title must be at least {Limits.TITLE_MIN} character"
    TITLE_TOO_LONG = f"Title cannot exceed {Limits.TITLE_MAX} characters"
    PASSWORD_TOO_SHORT = f"Password must be at least {Limits.PASSWORD_MIN} characters"
    INSUFFICIENT_POINTS = "Insufficient points"
    INVALID_DATE = "Date must be in the future"


# Field factory functions
def title_field(
    description: str = "Title of the item",
    **kwargs
) -> str:
    """Standard title field with consistent validation"""
    return Field(
        ...,
        min_length=Limits.TITLE_MIN,
        max_length=Limits.TITLE_MAX,
        description=description,
        **kwargs
    )


def description_field(
    description: str = "Optional description",
    **kwargs
) -> Optional[str]:
    """Standard description field"""
    return Field(
        None,
        max_length=Limits.DESCRIPTION_MAX,
        description=description,
        **kwargs
    )


def name_field(
    description: str = "Name",
    **kwargs
) -> str:
    """Standard name field"""
    return Field(
        ...,
        min_length=Limits.NAME_MIN,
        max_length=Limits.NAME_MAX,
        description=description,
        **kwargs
    )


def points_field(
    default: int = ...,
    min_val: int = Limits.TASK_POINTS_MIN,
    max_val: int = Limits.TASK_POINTS_MAX,
    description: str = "Point value",
    **kwargs
) -> int:
    """Standard points field with configurable limits"""
    return Field(
        default,
        ge=min_val,
        le=max_val,
        description=description,
        **kwargs
    )
```

**Update Schemas:**

```python
# BEFORE (task.py line 19-21):
title: str = Field(..., min_length=1, max_length=200)
description: Optional[str] = Field(None, max_length=1000)
points: int = Field(10, ge=0, le=1000)

# AFTER:
from app.schemas.validation import title_field, description_field, points_field

title: str = title_field(description="Task title")
description: Optional[str] = description_field()
points: int = points_field(default=10)
```

**Files to Update:**
1. `app/schemas/task.py`
2. `app/schemas/reward.py`
3. `app/schemas/consequence.py`
4. `app/schemas/user.py`
5. `app/schemas/family.py`
6. `app/schemas/points.py`

---

### Phase 1 Testing & Deployment

**Testing Checklist:**
```bash
# Run full test suite
pytest tests/ -v --cov=app --cov-report=html

# Test specific areas
pytest tests/test_exception_handlers.py -v
pytest tests/test_dependencies.py -v
pytest tests/test_schemas.py -v

# Manual testing
python scripts/manual_test_phase1.py
```

**Deployment Steps:**
1. Merge to staging branch
2. Deploy to staging environment
3. Run integration tests
4. Monitor for errors (24 hours)
5. If stable, merge to main

**Success Metrics:**
- All tests pass
- Code coverage maintains or improves
- No new errors in logs
- 200+ lines of code removed

---

## PHASE 2: SERVICE LAYER REFACTORING (WEEK 3-4)

**Goal:** Create generic base service, eliminate duplicate CRUD operations  
**Risk Level:** MEDIUM  
**Estimated Time:** 9 hours

### Task 2.1: Generic Base Service (4 hours)

**File:** `app/services/base_service.py` (NEW)

```python
"""
Generic base service for CRUD operations.
Reduces duplication across all service classes.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, delete
from typing import TypeVar, Generic, Type, Optional, List, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel

from app.core.database import Base
from app.core.exceptions import NotFoundException

# Type variables
ModelType = TypeVar('ModelType', bound=Base)
CreateSchemaType = TypeVar('CreateSchemaType', bound=BaseModel)
UpdateSchemaType = TypeVar('UpdateSchemaType', bound=BaseModel)


class BaseService(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Generic base service providing common CRUD operations.
    
    Usage:
        class TaskService(BaseService[Task, TaskCreate, TaskUpdate]):
            model = Task
            
            # Add business-specific methods here
    """
    
    model: Type[ModelType]
    
    @classmethod
    def _get_model_name(cls) -> str:
        """Get human-readable model name for errors"""
        return cls.model.__name__ if hasattr(cls, 'model') else "Resource"
    
    @classmethod
    async def get_by_id(
        cls,
        db: AsyncSession,
        entity_id: UUID,
        family_id: Optional[UUID] = None,
        raise_if_not_found: bool = True
    ) -> Optional[ModelType]:
        """
        Get entity by ID with optional family filtering.
        
        Args:
            db: Database session
            entity_id: UUID of entity
            family_id: Optional family_id for access control
            raise_if_not_found: Raise NotFoundException if not found
            
        Returns:
            Entity if found, None if not found and raise_if_not_found=False
            
        Raises:
            NotFoundException: If entity not found and raise_if_not_found=True
        """
        query = select(cls.model).where(cls.model.id == entity_id)
        
        # Add family filter if model has family_id and it's provided
        if family_id is not None and hasattr(cls.model, 'family_id'):
            query = query.where(cls.model.family_id == family_id)
        
        result = (await db.execute(query)).scalar_one_or_none()
        
        if result is None and raise_if_not_found:
            raise NotFoundException(f"{cls._get_model_name()} not found")
        
        return result
    
    @classmethod
    async def list_all(
        cls,
        db: AsyncSession,
        family_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
        filters: Optional[dict] = None
    ) -> List[ModelType]:
        """
        List entities with optional filtering.
        
        Args:
            db: Database session
            family_id: Optional family_id filter
            limit: Maximum results to return
            offset: Number of results to skip
            filters: Additional filter conditions (field: value)
            
        Returns:
            List of entities
        """
        query = select(cls.model)
        
        # Add family filter
        if family_id is not None and hasattr(cls.model, 'family_id'):
            query = query.where(cls.model.family_id == family_id)
        
        # Add custom filters
        if filters:
            for field, value in filters.items():
                if value is not None and hasattr(cls.model, field):
                    query = query.where(getattr(cls.model, field) == value)
        
        # Apply pagination
        query = query.limit(limit).offset(offset)
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        create_data: CreateSchemaType,
        **extra_fields
    ) -> ModelType:
        """
        Create new entity.
        
        Args:
            db: Database session
            create_data: Pydantic schema with creation data
            **extra_fields: Additional fields to set (e.g. family_id, created_by)
            
        Returns:
            Created entity
        """
        # Convert Pydantic model to dict
        data = create_data.model_dump()
        
        # Add extra fields
        data.update(extra_fields)
        
        # Create instance
        entity = cls.model(**data)
        
        db.add(entity)
        await db.commit()
        await db.refresh(entity)
        
        return entity
    
    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        entity_id: UUID,
        update_data: UpdateSchemaType,
        family_id: Optional[UUID] = None
    ) -> ModelType:
        """
        Update entity.
        
        Args:
            db: Database session
            entity_id: UUID of entity to update
            update_data: Pydantic schema with update data
            family_id: Optional family_id for access control
            
        Returns:
            Updated entity
            
        Raises:
            NotFoundException: If entity not found
        """
        entity = await cls.get_by_id(db, entity_id, family_id)
        
        # Update fields from Pydantic model
        update_fields = update_data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(entity, field, value)
        
        # Update timestamp if model has updated_at
        if hasattr(entity, 'updated_at'):
            entity.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(entity)
        
        return entity
    
    @classmethod
    async def delete(
        cls,
        db: AsyncSession,
        entity_id: UUID,
        family_id: Optional[UUID] = None
    ) -> None:
        """
        Delete entity.
        
        Args:
            db: Database session
            entity_id: UUID of entity to delete
            family_id: Optional family_id for access control
            
        Raises:
            NotFoundException: If entity not found
        """
        entity = await cls.get_by_id(db, entity_id, family_id)
        await db.delete(entity)
        await db.commit()
    
    @classmethod
    async def count(
        cls,
        db: AsyncSession,
        family_id: Optional[UUID] = None,
        filters: Optional[dict] = None
    ) -> int:
        """
        Count entities with optional filtering.
        
        Args:
            db: Database session
            family_id: Optional family_id filter
            filters: Additional filter conditions
            
        Returns:
            Count of entities
        """
        query = select(func.count()).select_from(cls.model)
        
        # Add family filter
        if family_id is not None and hasattr(cls.model, 'family_id'):
            query = query.where(cls.model.family_id == family_id)
        
        # Add custom filters
        if filters:
            for field, value in filters.items():
                if value is not None and hasattr(cls.model, field):
                    query = query.where(getattr(cls.model, field) == value)
        
        result = await db.execute(query)
        return result.scalar() or 0
    
    @classmethod
    async def exists(
        cls,
        db: AsyncSession,
        entity_id: UUID,
        family_id: Optional[UUID] = None
    ) -> bool:
        """Check if entity exists"""
        entity = await cls.get_by_id(db, entity_id, family_id, raise_if_not_found=False)
        return entity is not None
```

**Update Services to Inherit:**

**Example:** `app/services/task_service.py`

```python
# Add at top
from app.services.base_service import BaseService

# BEFORE:
class TaskService:
    """Service for task-related operations"""
    
    @staticmethod
    async def get_task(db: AsyncSession, task_id: UUID, family_id: UUID) -> Task:
        query = select(Task).where(
            and_(Task.id == task_id, Task.family_id == family_id)
        )
        task = (await db.execute(query)).scalar_one_or_none()
        if not task:
            raise NotFoundException("Task not found")
        return task

# AFTER:
class TaskService(BaseService[Task, TaskCreate, TaskUpdate]):
    """Service for task-related operations"""
    model = Task
    
    # Alias for backward compatibility
    @classmethod
    async def get_task(
        cls,
        db: AsyncSession,
        task_id: UUID,
        family_id: UUID
    ) -> Task:
        """Get task by ID (alias for get_by_id)"""
        return await cls.get_by_id(db, task_id, family_id)
```

**Services to Update:**
1. `app/services/task_service.py`
2. `app/services/reward_service.py`
3. `app/services/consequence_service.py`
4. `app/services/family_service.py`

**Note:** Keep business-specific methods, only replace generic CRUD

---

### Task 2.2: Standardize Method Names (2 hours)

**Create:** `NAMING_CONVENTIONS.md`

```markdown
# Service Method Naming Conventions

## Patterns

### Single Entity Operations
- `get_by_id(entity_id)` - Get single entity by ID
- `get_X(x_id)` - Legacy alias, use get_by_id
- `create(data)` - Create new entity
- `update(entity_id, data)` - Update entity
- `delete(entity_id)` - Delete entity
- `exists(entity_id)` - Check if exists

### Collection Operations  
- `list_all()` - List all entities
- `list_X()` - Legacy alias, use list_all
- `count()` - Count entities

### Queries
- `find_by_X(value)` - Find by specific field
- `search(query)` - Full-text search

### Business Operations
- `<verb>_<noun>()` - e.g., complete_task(), redeem_reward()
- `check_<condition>()` - e.g., check_overdue_tasks()
- `calculate_<value>()` - e.g., calculate_points()

## Examples

```python
# Good
await TaskService.get_by_id(db, task_id, family_id)
await TaskService.list_all(db, family_id)
await TaskService.complete_task(db, task_id, user_id)

# Avoid
await TaskService.getTask(db, task_id)  # camelCase
await TaskService.get_all_tasks(db)  # use list_all
await TaskService.completeTask(db, task_id)  # camelCase
```
```

**Refactor Method Names:**
- Update service methods to follow convention
- Keep old names as @deprecated aliases temporarily
- Update all calling code
- Remove deprecated aliases after 1 release

---

### Task 2.3: Query Filter Models (3 hours)

**File:** `app/schemas/filters.py` (NEW)

```python
"""
Query filter models for list endpoints.
Provides type-safe filtering with pagination.
"""
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

from app.models.task import TaskStatus, TaskFrequency
from app.models.reward import RewardCategory
from app.models.consequence import ConsequenceSeverity, RestrictionType
from app.models.point_transaction import TransactionType
from app.schemas.validation import Limits


class PaginationParams(BaseModel):
    """Base pagination parameters"""
    limit: int = Field(
        Limits.LIST_DEFAULT_LIMIT,
        ge=1,
        le=Limits.LIST_MAX_LIMIT,
        description="Maximum number of results"
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of results to skip"
    )


class SortParams(BaseModel):
    """Base sorting parameters"""
    sort_by: Optional[str] = Field(None, description="Field to sort by")
    sort_desc: bool = Field(False, description="Sort in descending order")


class TaskFilters(PaginationParams, SortParams):
    """Filters for task list endpoint"""
    user_id: Optional[UUID] = Field(None, description="Filter by assigned user")
    status: Optional[TaskStatus] = Field(None, description="Filter by status")
    is_default: Optional[bool] = Field(None, description="Filter by default tasks")
    frequency: Optional[TaskFrequency] = Field(None, description="Filter by frequency")
    overdue_only: bool = Field(False, description="Show only overdue tasks")


class RewardFilters(PaginationParams, SortParams):
    """Filters for reward list endpoint"""
    category: Optional[RewardCategory] = Field(None, description="Filter by category")
    is_active: Optional[bool] = Field(True, description="Filter by active status")
    max_points: Optional[int] = Field(None, description="Maximum points cost")
    min_points: Optional[int] = Field(None, description="Minimum points cost")
    affordable_only: bool = Field(False, description="Only show affordable rewards")


class ConsequenceFilters(PaginationParams, SortParams):
    """Filters for consequence list endpoint"""
    user_id: Optional[UUID] = Field(None, description="Filter by user")
    active_only: bool = Field(False, description="Show only active consequences")
    severity: Optional[ConsequenceSeverity] = Field(None, description="Filter by severity")
    restriction_type: Optional[RestrictionType] = Field(None, description="Filter by type")


class TransactionFilters(PaginationParams, SortParams):
    """Filters for transaction history endpoint"""
    user_id: Optional[UUID] = Field(None, description="Filter by user")
    transaction_type: Optional[TransactionType] = Field(None, description="Filter by type")
    min_points: Optional[int] = Field(None, description="Minimum point value")
    max_points: Optional[int] = Field(None, description="Maximum point value")
```

**Update Routes:**

```python
# BEFORE (tasks.py lines 31-47):
@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[UUID] = Query(None, description="Filter by assigned user"),
    status: Optional[TaskStatus] = Query(None, description="Filter by status"),
    is_default: Optional[bool] = Query(None, description="Filter by default tasks"),
):
    """List all tasks"""
    tasks = await TaskService.list_tasks(
        db,
        family_id=current_user.family_id,
        user_id=user_id,
        status=status,
        is_default=is_default,
    )
    return tasks

# AFTER:
from app.schemas.filters import TaskFilters

@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    filters: TaskFilters = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tasks with filtering and pagination"""
    tasks = await TaskService.list_tasks(
        db,
        family_id=current_user.family_id,
        filters=filters
    )
    return tasks
```

---

### Phase 2 Testing & Deployment

Same process as Phase 1.

---

## PHASE 3: ADVANCED FEATURES (WEEK 5-6)

**Goal:** Add Pydantic validators, API versioning, better responses  
**Risk Level:** LOW-MEDIUM  
**Estimated Time:** 11 hours

### Task 3.1: Pydantic Custom Validators (4 hours)

**Update schemas with validators:**

**Example:** `app/schemas/task.py`

```python
from pydantic import field_validator, model_validator
from datetime import datetime, timezone

class TaskCreate(TaskBase):
    assigned_to: UUID
    due_date: Optional[datetime] = None
    
    @field_validator('due_date')
    @classmethod
    def validate_due_date_future(cls, v):
        """Ensure due date is in the future"""
        if v and v < datetime.now(timezone.utc):
            raise ValueError('Due date must be in the future')
        return v
    
    @model_validator(mode='after')
    def validate_default_task_requirements(self):
        """Default tasks must have a due date"""
        if self.is_default and not self.due_date:
            raise ValueError('Default tasks must have a due date')
        return self
```

**Validators to Add:**
1. Task due dates in future
2. Password strength (AuthService)
3. Point limits based on role
4. Consequence duration matches severity
5. Email domain whitelist (optional)

---

### Task 3.2: API Versioning (3 hours)

**Update:** `app/api/__init__.py`

```python
from fastapi import APIRouter

# API v1 router
api_v1_router = APIRouter(prefix="/api/v1")

# Include all route modules
from app.api.routes import (
    auth,
    users,
    families,
    tasks,
    rewards,
    consequences,
)

api_v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(users.router, prefix="/users", tags=["Users"])
api_v1_router.include_router(families.router, prefix="/families", tags=["Families"])
api_v1_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_v1_router.include_router(rewards.router, prefix="/rewards", tags=["Rewards"])
api_v1_router.include_router(consequences.router, prefix="/consequences", tags=["Consequences"])
```

**Update:** `app/main.py`

```python
from app.api import api_v1_router

app = FastAPI(title="Family Task Manager API")

# Include API v1
app.include_router(api_v1_router)
```

---

### Task 3.3: Standard Response Models (2 hours)

**File:** `app/schemas/responses.py` (NEW)

```python
"""Standard API response models"""
from pydantic import BaseModel
from typing import Generic, TypeVar, List, Optional

T = TypeVar('T')


class MessageResponse(BaseModel):
    """Simple message response"""
    message: str
    success: bool = True


class ErrorResponse(BaseModel):
    """Error response with details"""
    error: str
    message: str
    status_code: int
    details: Optional[dict] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response"""
    items: List[T]
    total: int
    limit: int
    offset: int
    has_more: bool
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        limit: int,
        offset: int
    ):
        """Create paginated response"""
        return cls(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(items) < total
        )


class BulkOperationResponse(BaseModel):
    """Response for bulk operations"""
    success_count: int
    failure_count: int
    total: int
    errors: List[str] = []
```

**Usage:**

```python
from app.schemas.responses import PaginatedResponse, MessageResponse

@router.get("/", response_model=PaginatedResponse[TaskResponse])
async def list_tasks_paginated(...):
    tasks = await TaskService.list_tasks(...)
    total = await TaskService.count(...)
    
    return PaginatedResponse.create(
        items=tasks,
        total=total,
        limit=filters.limit,
        offset=filters.offset
    )

@router.post("/logout", response_model=MessageResponse)
async def logout(...):
    return MessageResponse(
        message="Logged out successfully"
    )
```

---

### Task 3.4: OpenAPI Documentation (2 hours)

**Update route files to add OpenAPI metadata:**

```python
# tasks.py
router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
    responses={
        404: {"description": "Task not found"},
        403: {"description": "Access denied"},
    }
)

@router.post(
    "/",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new task",
    description="Create a new task and assign it to a family member. Requires parent role.",
    response_description="The created task",
    responses={
        201: {
            "description": "Task created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "title": "Clean your room",
                        "points": 50,
                        "status": "pending"
                    }
                }
            }
        }
    }
)
async def create_task(...):
    """
    Create a new task.
    
    - **title**: Task title (required)
    - **points**: Points awarded on completion (0-1000)
    - **assigned_to**: User ID to assign task to
    - **due_date**: Optional due date
    """
    ...
```

---

## PHASE 4: ARCHITECTURE IMPROVEMENTS (WEEK 7-8)

**Goal:** Repository pattern, Unit of Work, performance optimization  
**Risk Level:** MEDIUM-HIGH  
**Estimated Time:** 22 hours

This phase is optional and should be evaluated after Phase 3.

---

## TESTING STRATEGY

### Unit Tests

**Create test files for new modules:**

```bash
tests/
├── test_exception_handlers.py
├── test_base_service.py
├── test_validation.py
├── test_filters.py
└── test_responses.py
```

**Example:** `tests/test_exception_handlers.py`

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import NotFoundException, ValidationException
from app.core.exception_handlers import register_exception_handlers


@pytest.fixture
def app():
    app = FastAPI()
    register_exception_handlers(app)
    
    @app.get("/test/not-found")
    async def test_not_found():
        raise NotFoundException("Test not found")
    
    @app.get("/test/validation")
    async def test_validation():
        raise ValidationException("Test validation error")
    
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_not_found_handler(client):
    response = client.get("/test/not-found")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert "Test not found" in response.json()["message"]


def test_validation_handler(client):
    response = client.get("/test/validation")
    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"
```

### Integration Tests

**Test complete workflows:**

```python
async def test_task_creation_and_completion_workflow():
    """Test full task lifecycle"""
    # 1. Parent creates task
    # 2. Child lists tasks and sees it
    # 3. Child completes task
    # 4. Verify points awarded
    # 5. Verify transaction created
    pass
```

### Performance Tests

**Add performance benchmarks:**

```python
async def test_list_tasks_performance():
    """Ensure list endpoint handles large datasets"""
    # Create 1000 tasks
    # Time the list operation
    # Assert < 100ms response time
    pass
```

---

## ROLLBACK PLAN

### If Phase 1 Fails

1. Revert exception handler registration in `main.py`
2. Restore try-catch blocks in routes
3. Remove new files
4. Deploy previous version

### If Phase 2 Fails

1. Revert service inheritance
2. Keep old service methods
3. Remove base_service.py
4. Deploy previous version

### General Rollback

```bash
# Tag before each phase
git tag phase-1-start
git tag phase-1-complete

# Rollback if needed
git reset --hard phase-1-start
git push --force
```

---

## MONITORING & METRICS

### Track These Metrics

**Code Quality:**
- Lines of code
- Duplicate code percentage
- Cyclomatic complexity
- Test coverage

**Performance:**
- Response times (p50, p95, p99)
- Database query count per endpoint
- Cache hit rates (Phase 4)

**Errors:**
- Exception rates by type
- 4xx/5xx error rates
- Failed validation rates

**Developer Experience:**
- Time to add new endpoint
- Code review feedback
- Bug reports

---

## COMMUNICATION PLAN

### Stakeholder Updates

**Weekly:** Status email with:
- Completed tasks
- Current progress
- Blockers
- Next week goals

**Post-Phase:** Summary report with:
- Metrics improvement
- Issues encountered
- Lessons learned
- Next phase recommendation

### Team Updates

**Daily:** Stand-up with:
- Yesterday's work
- Today's plan
- Blockers

**Code Reviews:**
- All PRs require 1 approval
- Run tests before review
- Follow review checklist

---

## SUCCESS CRITERIA

### Phase 1 Success

- [ ] Exception handlers working
- [ ] All try-catch blocks removed
- [ ] Family auth centralized
- [ ] Base schemas in use
- [ ] Validation constants applied
- [ ] Tests passing
- [ ] 200+ lines removed

### Phase 2 Success

- [ ] Base service created
- [ ] 4+ services inheriting
- [ ] Method names standardized
- [ ] Filter models implemented
- [ ] Tests passing
- [ ] 150+ lines removed

### Phase 3 Success

- [ ] Validators added
- [ ] API versioned
- [ ] Response models standardized
- [ ] OpenAPI docs improved
- [ ] Tests passing

### Phase 4 Success

- [ ] Repository pattern implemented
- [ ] Unit of Work working
- [ ] Performance improved
- [ ] Caching functional
- [ ] Tests passing

### Overall Success

- [ ] 30-40% code reduction
- [ ] Test coverage >85%
- [ ] No performance regression
- [ ] Developer satisfaction improved
- [ ] Documentation complete

---

## APPENDIX

### Useful Commands

```bash
# Run specific test file
pytest tests/test_exception_handlers.py -v

# Run with coverage
pytest --cov=app --cov-report=html

# Check code quality
flake8 app/
black app/ --check
isort app/ --check-only

# Count lines of code
cloc app/ --exclude-dir=__pycache__

# Find duplicate code
pylint app/ --disable=all --enable=duplicate-code
```

### Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/)
- FORENSIC_CODE_REVIEW.md

---

**Document Version:** 1.0  
**Last Updated:** January 23, 2026  
**Maintainer:** Development Team
