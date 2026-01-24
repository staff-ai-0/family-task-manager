---
applyTo: "app/api/**/*.py,app/services/**/*.py,app/models/**/*.py"
---

# Python Type Safety & SQLAlchemy Best Practices

## 🔴 CRITICAL: Type Safety Issues to ALWAYS Avoid

### Issue 1: SQLAlchemy Column vs Python Type Mismatch

**❌ WRONG - This causes LSP errors:**
```python
from app.models import User

@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # ERROR: Passing Column[UUID] to function expecting UUID
    user = await AuthService.get_user_by_id(db, user_id)
    
    # ERROR: current_user.family_id is Column[UUID], not UUID
    if user.family_id != current_user.family_id:  # Type error!
        raise HTTPException(status_code=403, detail="...")
```

**✅ CORRECT - Explicit type conversion:**
```python
from uuid import UUID
from sqlalchemy import select

@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await AuthService.get_user_by_id(db, user_id)
    
    # Convert SQLAlchemy column to Python UUID for comparison
    current_family_id = UUID(str(current_user.family_id))
    user_family_id = UUID(str(user.family_id))
    
    if user_family_id != current_family_id:
        raise HTTPException(status_code=403, detail="...")
```

**✅ BETTER - Use service layer with proper typing:**
```python
@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Let service handle type conversions internally
    user = await AuthService.get_family_user(
        db=db,
        user_id=user_id,
        family_id=current_user.family_id
    )
    return user
```

### Issue 2: Boolean Column Evaluation

**❌ WRONG - SQLAlchemy Column[bool] can't be used in conditionals:**
```python
# ERROR: ColumnElement[bool].__bool__ returns NoReturn
if current_user.family_id != family_id:  # This works
    raise HTTPException(...)

# But the condition itself might cause issues in some contexts
```

**✅ CORRECT - Explicit comparison:**
```python
from sqlalchemy import and_, or_

# In queries, use SQLAlchemy operators
query = select(Task).where(
    and_(
        Task.family_id == family_id,
        Task.is_active == True  # Explicit comparison
    )
)

# In Python code, access the value properly
is_active = bool(task.is_active)  # Convert to Python bool
if is_active:
    # Do something
```

### Issue 3: Service Method Type Annotations

**❌ WRONG - Missing or incorrect return types:**
```python
class TaskService:
    @staticmethod
    async def get_task(db: AsyncSession, task_id, family_id):  # Missing types
        query = select(Task).where(...)
        return (await db.execute(query)).scalar_one_or_none()
```

**✅ CORRECT - Complete type annotations:**
```python
from typing import Optional
from uuid import UUID

class TaskService:
    @staticmethod
    async def get_task(
        db: AsyncSession,
        task_id: UUID,
        family_id: UUID
    ) -> Optional[Task]:
        """
        Get a task by ID for a specific family.
        
        Args:
            db: Database session
            task_id: Task UUID
            family_id: Family UUID for access control
            
        Returns:
            Task if found, None otherwise
            
        Raises:
            NotFoundException: If task not found or not in family
        """
        query = select(Task).where(
            and_(
                Task.id == task_id,
                Task.family_id == family_id
            )
        )
        result = (await db.execute(query)).scalar_one_or_none()
        if not result:
            raise NotFoundException("Task not found")
        return result
```

## 🎯 Best Practices for Type Safety

### 1. Model Property Access

**✅ Use properties for type conversion:**
```python
# In models/user.py
from sqlalchemy import Column, UUID as SQLAlchemyUUID
from uuid import UUID
from sqlalchemy.orm import Mapped, mapped_column

class User(Base):
    __tablename__ = "users"
    
    # Modern SQLAlchemy 2.0 style
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(ForeignKey("families.id"))
    points: Mapped[int] = mapped_column(default=0)
    
    # Or legacy style with proper typing
    # id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4)
    # family_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("families.id"))
    
    @property
    def family_uuid(self) -> UUID:
        """Get family_id as Python UUID"""
        return UUID(str(self.family_id)) if self.family_id else None
```

### 2. Service Layer Type Safety

**✅ Create type-safe service methods:**
```python
from typing import List, Optional
from uuid import UUID

class TaskService:
    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        family_id: UUID,
        user_id: Optional[UUID] = None,
        status: Optional[TaskStatus] = None,
        is_default: Optional[bool] = None,
    ) -> List[Task]:
        """List tasks with optional filters."""
        query = select(Task).where(Task.family_id == family_id)
        
        if user_id is not None:
            query = query.where(Task.assigned_to == user_id)
        if status is not None:
            query = query.where(Task.status == status)
        if is_default is not None:
            query = query.where(Task.is_default == is_default)
        
        result = await db.execute(query)
        return list(result.scalars().all())
```

### 3. Route Handler Type Safety

**✅ Proper typing in route handlers:**
```python
from fastapi import APIRouter, Depends, status
from typing import List
from uuid import UUID

router = APIRouter()

@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[UUID] = Query(None),
    status: Optional[TaskStatus] = Query(None),
) -> List[Task]:
    """
    List tasks for current user's family.
    
    Returns:
        List of tasks matching filters
    """
    # Access model properties - these are already properly typed
    tasks = await TaskService.list_tasks(
        db=db,
        family_id=current_user.family_id,  # This is fine if using Mapped[]
        user_id=user_id,
        status=status
    )
    return tasks
```

## 🔧 Migration Guide: Fix Existing Type Issues

### Step 1: Update Models to Use Mapped[]

**Before (legacy SQLAlchemy):**
```python
from sqlalchemy import Column, String, Integer, UUID as SQLAlchemyUUID

class User(Base):
    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True)
    name = Column(String(100))
    points = Column(Integer, default=0)
```

**After (SQLAlchemy 2.0 recommended):**
```python
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    points: Mapped[int] = mapped_column(default=0)
```

### Step 2: Add Type Conversion Helpers

**Create a utility module `app/core/type_utils.py`:**
```python
from uuid import UUID
from typing import Any, Optional

def to_uuid(value: Any) -> Optional[UUID]:
    """
    Safely convert SQLAlchemy Column or any value to UUID.
    
    Args:
        value: Column[UUID], UUID, str, or None
        
    Returns:
        Python UUID or None
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))

def safe_bool(value: Any) -> bool:
    """
    Safely convert SQLAlchemy Column[bool] to Python bool.
    
    Args:
        value: Column[bool], bool, or any truthy value
        
    Returns:
        Python bool
    """
    return bool(value)
```

**Usage in routes:**
```python
from app.core.type_utils import to_uuid

@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await AuthService.get_user_by_id(db, user_id)
    
    # Use helper for safe comparison
    current_family = to_uuid(current_user.family_id)
    user_family = to_uuid(user.family_id)
    
    if user_family != current_family:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return user
```

### Step 3: Update Service Method Signatures

**Add proper type hints to all service methods:**
```python
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

class TaskService:
    @staticmethod
    async def get_task(
        db: AsyncSession,
        task_id: UUID,
        family_id: UUID
    ) -> Task:
        """Type hints make intent clear and enable LSP checking."""
        ...
    
    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        family_id: UUID,
        filters: Optional[dict] = None
    ) -> List[Task]:
        """Return type annotation is critical."""
        ...
```

## 🚨 Common Pitfalls to Avoid

### Pitfall 1: Direct Column Comparison
```python
# ❌ WRONG
if task.family_id != current_user.family_id:  # Type error possible
    ...

# ✅ CORRECT
if str(task.family_id) != str(current_user.family_id):  # Safe comparison
    ...

# ✅ BETTER
from app.core.type_utils import to_uuid
if to_uuid(task.family_id) != to_uuid(current_user.family_id):
    ...
```

### Pitfall 2: Passing Column to Function
```python
# ❌ WRONG
result = await service_method(
    db=db,
    user_id=current_user.id,  # Column[UUID] passed as UUID
    family_id=current_user.family_id,  # Type error
)

# ✅ CORRECT
from uuid import UUID

result = await service_method(
    db=db,
    user_id=UUID(str(current_user.id)),
    family_id=UUID(str(current_user.family_id)),
)
```

### Pitfall 3: Boolean Conditionals
```python
# ❌ WRONG
if task.is_active and task.is_default:  # Might fail with ColumnElement
    ...

# ✅ CORRECT
if task.is_active == True and task.is_default == True:  # Explicit comparison
    ...

# ✅ BETTER (in queries)
query = select(Task).where(
    and_(
        Task.is_active == True,
        Task.is_default == True
    )
)
```

## 📋 Pre-Commit Checklist for Type Safety

Before committing code, verify:

- [ ] All service methods have complete type annotations
- [ ] All route handlers specify return types
- [ ] SQLAlchemy Column values are converted when passed to functions expecting Python types
- [ ] Boolean columns use explicit comparison (== True/False)
- [ ] UUID columns are converted to UUID type when needed
- [ ] No `Any` types unless absolutely necessary
- [ ] LSP (Pylance/mypy) shows no type errors
- [ ] All model classes use `Mapped[]` syntax (SQLAlchemy 2.0+)

## 🔍 LSP Configuration

**Ensure your `pyproject.toml` or LSP config includes:**
```toml
[tool.pylance]
typeCheckingMode = "strict"
reportMissingTypeStubs = false
reportUnknownMemberType = false

[tool.mypy]
plugins = ["sqlalchemy.ext.mypy.plugin"]
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
```

## 🎓 Additional Resources

- [SQLAlchemy 2.0 Type Mapping](https://docs.sqlalchemy.org/en/20/orm/mapping_api.html#mapped-column)
- [FastAPI Response Models](https://fastapi.tiangolo.com/tutorial/response-model/)
- [Python Type Hints Best Practices](https://docs.python.org/3/library/typing.html)

---

**Last Updated**: January 23, 2026
**Reason**: Added to prevent LSP type errors found in forensic code review
