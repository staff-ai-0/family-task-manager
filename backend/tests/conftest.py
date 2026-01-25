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

from app.main import app
from app.core.database import Base, get_db

# Test database URL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://familyapp:familyapp123@localhost:5433/familyapp_test",
)


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create test database engine"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


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
        # Clean up all data after test
        for table in reversed(Base.metadata.sorted_tables):
            if table.name != "alembic_version":
                await session.execute(table.delete())
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
