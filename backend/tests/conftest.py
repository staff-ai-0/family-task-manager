"""
Pytest configuration and fixtures for Family Task Manager tests
"""

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from httpx import AsyncClient, ASGITransport
import os
import asyncpg

from app.main import app
from app.core.database import Base, get_db

# Test database URL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test",
)

# Pure asyncpg DSN (no +asyncpg prefix, no SQLAlchemy)
_PG_DSN = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


async def _drop_all_pg(pg: asyncpg.Connection) -> None:
    """Drop all tables and custom enum types via a raw asyncpg connection."""
    await pg.execute("SET client_min_messages TO WARNING")
    # Drop each user table individually (handles empty schema gracefully)
    tables = await pg.fetch(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
    )
    for row in tables:
        await pg.execute(f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE')
    # Drop leftover custom enum types
    types_ = await pg.fetch(
        "SELECT typname FROM pg_type "
        "JOIN pg_namespace ON pg_namespace.oid = pg_type.typnamespace "
        "WHERE typtype = 'e' AND nspname = 'public'"
    )
    for row in types_:
        await pg.execute(f'DROP TYPE IF EXISTS "{row["typname"]}" CASCADE')


@pytest_asyncio.fixture(scope="session")
async def test_engine_session():
    """Create test database engine at session scope with proper enum handling."""
    # Step 1: Clean up old tables/types using a direct asyncpg connection
    pg = await asyncpg.connect(_PG_DSN)
    try:
        await _drop_all_pg(pg)
    finally:
        await pg.close()

    # Step 2: Create schema via SQLAlchemy with proper enum type creation
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    
    # Create all enum types first before creating tables
    async with engine.connect() as conn:
        # Enable AUTOCOMMIT mode so each DDL statement commits immediately
        # This is needed so asyncpg's prepared-statement cache sees the enum types
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        
        # Create enum types explicitly
        enum_types = [
            ("userrole", ["PARENT", "CHILD", "TEEN"]),
            ("taskstatus", ["PENDING", "COMPLETED", "OVERDUE", "CANCELLED"]),
            ("taskfrequency", ["DAILY", "WEEKLY", "MONTHLY", "ONE_TIME"]),
            ("transactiontype", ["TASK_COMPLETED", "REWARD_REDEEMED", "PARENT_ADJUSTMENT", "BONUS", "PENALTY", "TRANSFER"]),
            ("rewardcategory", ["SCREEN_TIME", "TREATS", "ACTIVITIES", "PRIVILEGES", "MONEY", "TOYS"]),
            ("assignmentstatus", ["pending", "completed", "overdue", "cancelled"]),
            ("invitationstatus", ["PENDING", "ACCEPTED", "REJECTED", "EXPIRED"]),
            ("restrictiontype", ["SCREEN_TIME", "REWARDS", "EXTRA_TASKS", "ALLOWANCE", "ACTIVITIES", "CUSTOM"]),
            ("consequenceseverity", ["LOW", "MEDIUM", "HIGH"]),
        ]
        
        for enum_name, values in enum_types:
            try:
                values_sql = ", ".join(f"'{v}'" for v in values)
                from sqlalchemy import text
                await conn.execute(text(f"CREATE TYPE {enum_name} AS ENUM ({values_sql})"))
            except Exception:
                # Enum might already exist, that's OK
                pass
        
        # Now create all tables
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Teardown: clean up
    await engine.dispose()
    pg2 = await asyncpg.connect(_PG_DSN)
    try:
        await _drop_all_pg(pg2)
    finally:
        await pg2.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine(test_engine_session):
    """Per-function engine that yields the session engine."""
    yield test_engine_session



@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test"""
    async_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session
        # Rollback any uncommitted changes
        await session.rollback()
        # Clean up all data after test (keep schema intact)
        for table in reversed(Base.metadata.sorted_tables):
            # Skip alembic_version table; it tracks migrations
            if table.name != "alembic_version":
                try:
                    await session.execute(table.delete())
                except Exception:
                    # Table might not exist if schema is being rebuilt
                    pass
        await session.commit()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test client with overridden database session"""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()


# Test data fixtures


@pytest_asyncio.fixture
async def test_family(db_session: AsyncSession):
    """Create a test family"""
    from app.models.family import Family

    family = Family(name="Test Family")
    db_session.add(family)
    await db_session.commit()
    await db_session.refresh(family)
    return family


@pytest_asyncio.fixture
async def test_parent_user(db_session: AsyncSession, test_family):
    """Create a test parent user"""
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    user = User(
        email="parent@test.com",
        password_hash=get_password_hash("password123"),
        name="Test Parent",
        role=UserRole.PARENT,
        family_id=test_family.id,
        email_verified=True,
        points=0,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_child_user(db_session: AsyncSession, test_family):
    """Create a test child user"""
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    user = User(
        email="child@test.com",
        password_hash=get_password_hash("password123"),
        name="Test Child",
        role=UserRole.CHILD,
        family_id=test_family.id,
        email_verified=True,
        points=100,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_task(
    db_session: AsyncSession, test_family, test_child_user, test_parent_user
):
    """Create a test task"""
    from app.models.task import Task, TaskStatus, TaskFrequency
    from datetime import date

    task = Task(
        family_id=test_family.id,
        assigned_to=test_child_user.id,
        created_by=test_parent_user.id,
        title="Clean Your Room",
        description="Make your bed and pick up toys",
        points=50,
        is_default=True,
        frequency=TaskFrequency.DAILY,
        status=TaskStatus.PENDING,
        due_date=date.today(),
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest_asyncio.fixture
async def test_reward(db_session: AsyncSession, test_family, test_parent_user):
    """Create a test reward"""
    from app.models.reward import Reward, RewardCategory

    reward = Reward(
        family_id=test_family.id,
        title="30 Minutes Screen Time",
        description="Extra time for games or TV",
        points_cost=100,
        category=RewardCategory.SCREEN_TIME,
        icon="🎮",
        is_active=True,
    )
    db_session.add(reward)
    await db_session.commit()
    await db_session.refresh(reward)
    return reward


# Budget test convenience aliases
# These match the parameter names used in test_budget_allocation.py

@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, test_parent_user) -> dict:
    """Return Authorization headers for test_parent_user (email_verified=True)."""
    response = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def db(db_session: AsyncSession) -> AsyncSession:
    """Alias for db_session, used in budget tests."""
    return db_session


@pytest_asyncio.fixture
async def family_id(test_family):
    """Return just the family UUID, used in budget tests."""
    return test_family.id
