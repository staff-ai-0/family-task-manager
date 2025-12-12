# Prompt Template: New Database Model

Use this template when creating new SQLAlchemy models for the Family Task Manager.

## Checklist

- [ ] Define model structure and relationships
- [ ] Add proper constraints and indexes
- [ ] Create Alembic migration
- [ ] Add model methods and properties
- [ ] Create corresponding Pydantic schemas
- [ ] Write model tests
- [ ] Update documentation

## Template Structure

### 1. Create Model in `app/models/[name].py`

```python
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base

# Define enums if needed
class [Status]Enum(str, enum.Enum):
    """Enum for [resource] status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"

class [ModelName](Base):
    """
    [Model description]
    
    Attributes:
        id: Primary key (UUID)
        [field_name]: [Field description]
        created_at: Timestamp of creation
        updated_at: Timestamp of last update
    """
    __tablename__ = "[table_name]"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Foreign keys
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    
    # Data fields
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SQLEnum([Status]Enum), nullable=False, default=[Status]Enum.ACTIVE)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Numeric fields
    points = Column(Integer, nullable=False, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    family = relationship("Family", back_populates="[plural_name]")
    user = relationship("User", back_populates="[plural_name]")
    
    # Indexes (add to __table_args__ if needed)
    __table_args__ = (
        # Composite index for common queries
        # Index('idx_[table]_family_status', 'family_id', 'status'),
    )
    
    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id}, title={self.title})>"
    
    @property
    def is_valid(self) -> bool:
        """Check if [resource] is valid"""
        return self.is_active and self.status == [Status]Enum.ACTIVE
```

## Common Model Patterns

### Task Model (Example)

```python
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base

class TaskFrequency(str, enum.Enum):
    """Task frequency options"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ONE_TIME = "one_time"

class TaskStatus(str, enum.Enum):
    """Task status options"""
    PENDING = "pending"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"

class Task(Base):
    """
    Task model representing family tasks
    
    Tasks can be default (obligatory) or extra (optional).
    Default tasks must be completed to avoid consequences.
    """
    __tablename__ = "tasks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Foreign keys
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id"), nullable=False, index=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    consequence_id = Column(UUID(as_uuid=True), ForeignKey("consequences.id"), nullable=True)
    
    # Task details
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    points = Column(Integer, nullable=False, default=10)
    
    # Task type and frequency
    is_default = Column(Boolean, nullable=False, default=False)
    frequency = Column(SQLEnum(TaskFrequency), nullable=False, default=TaskFrequency.ONE_TIME)
    
    # Status and dates
    status = Column(SQLEnum(TaskStatus), nullable=False, default=TaskStatus.PENDING)
    due_date = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    family = relationship("Family", back_populates="tasks")
    assigned_user = relationship("User", foreign_keys=[assigned_to], back_populates="assigned_tasks")
    creator = relationship("User", foreign_keys=[created_by], back_populates="created_tasks")
    consequence = relationship("Consequence", back_populates="task")
    transactions = relationship("PointTransaction", back_populates="task")
    
    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_task_family_status', 'family_id', 'status'),
        Index('idx_task_user_status', 'assigned_to', 'status'),
        Index('idx_task_due_date', 'due_date'),
    )
    
    def __repr__(self):
        return f"<Task(id={self.id}, title={self.title}, status={self.status})>"
    
    @property
    def is_overdue(self) -> bool:
        """Check if task is overdue"""
        return (
            self.status == TaskStatus.PENDING 
            and self.due_date < datetime.utcnow()
        )
    
    @property
    def can_complete(self) -> bool:
        """Check if task can be completed"""
        return self.status == TaskStatus.PENDING
    
    def complete(self) -> None:
        """Mark task as completed"""
        if not self.can_complete:
            raise ValueError("Task cannot be completed in current status")
        
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.utcnow()
```

### Reward Model (Example)

```python
class RewardCategory(str, enum.Enum):
    """Reward categories"""
    SCREEN_TIME = "screen_time"
    TREATS = "treats"
    ACTIVITIES = "activities"
    PRIVILEGES = "privileges"
    OTHER = "other"

class Reward(Base):
    """
    Reward model representing family rewards
    
    Rewards can be redeemed with points earned from completing tasks.
    """
    __tablename__ = "rewards"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Foreign keys
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Reward details
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    points_cost = Column(Integer, nullable=False)
    category = Column(SQLEnum(RewardCategory), nullable=False, default=RewardCategory.OTHER)
    icon = Column(String(50), nullable=True)  # Icon identifier
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    family = relationship("Family", back_populates="rewards")
    creator = relationship("User", back_populates="created_rewards")
    redemptions = relationship("PointTransaction", back_populates="reward")
    
    __table_args__ = (
        Index('idx_reward_family_active', 'family_id', 'is_active'),
    )
    
    def __repr__(self):
        return f"<Reward(id={self.id}, title={self.title}, points={self.points_cost})>"
```

### 2. Create Alembic Migration

```bash
# Generate migration
alembic revision --autogenerate -m "Add [table_name] table"

# Review and edit migration file in migrations/versions/
# Ensure proper indexes and constraints are included

# Apply migration
alembic upgrade head
```

Example migration file:

```python
"""Add tasks table

Revision ID: abc123def456
Revises: previous_revision
Create Date: 2025-12-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'abc123def456'
down_revision = 'previous_revision'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create enum types
    op.execute("CREATE TYPE taskstatus AS ENUM ('pending', 'completed', 'overdue', 'cancelled')")
    op.execute("CREATE TYPE taskfrequency AS ENUM ('daily', 'weekly', 'monthly', 'one_time')")
    
    # Create table
    op.create_table(
        'tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('assigned_to', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('frequency', sa.Enum('daily', 'weekly', 'monthly', 'one_time', name='taskfrequency'), nullable=False),
        sa.Column('status', sa.Enum('pending', 'completed', 'overdue', 'cancelled', name='taskstatus'), nullable=False),
        sa.Column('due_date', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['family_id'], ['families.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('idx_task_family_status', 'tasks', ['family_id', 'status'])
    op.create_index('idx_task_user_status', 'tasks', ['assigned_to', 'status'])
    op.create_index('idx_task_due_date', 'tasks', ['due_date'])

def downgrade() -> None:
    op.drop_index('idx_task_due_date', table_name='tasks')
    op.drop_index('idx_task_user_status', table_name='tasks')
    op.drop_index('idx_task_family_status', table_name='tasks')
    op.drop_table('tasks')
    op.execute("DROP TYPE taskstatus")
    op.execute("DROP TYPE taskfrequency")
```

### 3. Update Relationship in Related Models

```python
# In app/models/user.py
class User(Base):
    # ... existing fields ...
    
    # Add new relationship
    assigned_tasks = relationship("Task", foreign_keys="Task.assigned_to", back_populates="assigned_user")
    created_tasks = relationship("Task", foreign_keys="Task.created_by", back_populates="creator")

# In app/models/family.py
class Family(Base):
    # ... existing fields ...
    
    # Add new relationship
    tasks = relationship("Task", back_populates="family")
```

### 4. Create Tests in `tests/test_models/test_[name].py`

```python
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from app.models.[name] import [ModelName], [Status]Enum

@pytest.mark.asyncio
async def test_create_[model](db_session):
    """Test creating a [model]"""
    [model] = [ModelName](
        family_id=uuid4(),
        user_id=uuid4(),
        title="Test [Model]",
        description="Test description",
        status=[Status]Enum.ACTIVE
    )
    
    db_session.add([model])
    await db_session.commit()
    await db_session.refresh([model])
    
    assert [model].id is not None
    assert [model].title == "Test [Model]"
    assert [model].created_at is not None

@pytest.mark.asyncio
async def test_[model]_relationships(db_session, test_family, test_user):
    """Test [model] relationships"""
    [model] = [ModelName](
        family_id=test_family.id,
        user_id=test_user.id,
        title="Test [Model]"
    )
    
    db_session.add([model])
    await db_session.commit()
    await db_session.refresh([model])
    
    assert [model].family.id == test_family.id
    assert [model].user.id == test_user.id

def test_[model]_property():
    """Test [model] property"""
    [model] = [ModelName](
        status=[Status]Enum.ACTIVE,
        is_active=True
    )
    
    assert [model].is_valid is True
```

---

**Created**: December 11, 2025
