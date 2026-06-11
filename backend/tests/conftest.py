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
            ("transactiontype", ["TASK_COMPLETED", "REWARD_REDEEMED", "PARENT_ADJUSTMENT", "BONUS", "PENALTY", "TRANSFER", "GIG_APPROVED"]),
            ("rewardcategory", ["SCREEN_TIME", "TREATS", "ACTIVITIES", "PRIVILEGES", "MONEY", "TOYS"]),
            ("assignmentstatus", ["pending", "claimed", "completed", "overdue", "cancelled"]),
            ("approval_status", ["none", "pending", "approved", "rejected"]),
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
async def test_teen_user(db_session: AsyncSession, test_family):
    """Create a test teen user (used for non-parent permission tests)."""
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    user = User(
        email="teen@test.local",
        password_hash=get_password_hash("password123"),
        name="Test Teen",
        role=UserRole.TEEN,
        family_id=test_family.id,
        email_verified=True,
        points=0,
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


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Disable the global rate limiter by default so its in-memory counters don't
    bleed across tests. The dedicated rate-limit test re-enables it explicitly."""
    try:
        from app.core.rate_limiter import limiter
        limiter.reset()
        limiter.enabled = False
    except Exception:
        pass
    yield


@pytest_asyncio.fixture
async def db(db_session: AsyncSession) -> AsyncSession:
    """Alias for db_session, used in budget tests."""
    return db_session


@pytest_asyncio.fixture
async def family_id(test_family):
    """Return just the family UUID, used in budget tests."""
    return test_family.id


@pytest_asyncio.fixture
async def sample_family(db_session: AsyncSession):
    """Create a sample family for subscription/state-transition tests."""
    from app.models.family import Family

    fam = Family(name="Sample Family", join_code="ABCDEF")
    db_session.add(fam)
    await db_session.commit()
    await db_session.refresh(fam)
    return fam


# Task template factories for gig gating tests


@pytest_asyncio.fixture
async def mandatory_template_factory(db_session: AsyncSession):
    """Factory for a mandatory (is_bonus=False) task template."""
    from uuid import uuid4
    from app.models.task_template import TaskTemplate, AssignmentType

    async def _make(*, family, points: int = 0, title: str = "Brush teeth"):
        t = TaskTemplate(
            id=uuid4(), title=title, points=points, interval_days=1,
            assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
            family_id=family.id,
        )
        db_session.add(t)
        await db_session.commit()
        return t

    return _make


@pytest_asyncio.fixture
async def gig_template_factory(db_session: AsyncSession):
    """Factory for a gig (is_bonus=True) task template."""
    from uuid import uuid4
    from app.models.task_template import TaskTemplate, AssignmentType

    async def _make(*, family, points: int = 20, title: str = "Learn topic"):
        t = TaskTemplate(
            id=uuid4(), title=title, points=points, interval_days=7,
            assignment_type=AssignmentType.AUTO, is_bonus=True, is_active=True,
            family_id=family.id,
        )
        db_session.add(t)
        await db_session.commit()
        return t

    return _make


# ---------------------------------------------------------------------------
# Shared fixtures for scanner-v2 tasks (T4+)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def family(db: AsyncSession):
    """A fresh family for scanner-v2 service tests."""
    from app.models.family import Family
    fam = Family(name="Test Family")
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


@pytest_asyncio.fixture
async def other_family(db: AsyncSession):
    """A second family for tenant-isolation tests."""
    from app.models.family import Family
    fam = Family(name="Other Family")
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


@pytest_asyncio.fixture
async def transaction(db: AsyncSession, family):
    """A minimal BudgetTransaction attached to the shared family fixture."""
    from app.models.budget import BudgetAccount, BudgetTransaction
    from datetime import date
    acct = BudgetAccount(family_id=family.id, name="Cash", type="checking",
                         currency="MXN")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)
    tx = BudgetTransaction(
        family_id=family.id, account_id=acct.id, date=date.today(),
        amount=-10000,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


@pytest_asyncio.fixture
async def transaction_factory(db: AsyncSession, family):
    """Factory that creates BudgetTransaction rows for the shared family."""
    from app.models.budget import BudgetAccount, BudgetTransaction
    acct = BudgetAccount(family_id=family.id, name="F", type="checking",
                         currency="MXN")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)

    async def _make(**kwargs):
        tx = BudgetTransaction(
            family_id=kwargs.get("family_id", family.id),
            account_id=acct.id,
            date=kwargs.get("date"),
            amount=kwargs.get("amount", -10000),
        )
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        return tx

    return _make


# ---------------------------------------------------------------------------
# Fixtures for Task 5: AccountMatchingService
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def user(db: AsyncSession, family):
    """A minimal PARENT user belonging to the shared family fixture."""
    from app.models.user import User, UserRole
    u = User(
        email="acct-match-test@example.com",
        name="Test Parent",
        role=UserRole.PARENT,
        family_id=family.id,
        email_verified=True,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
async def account_factory(db: AsyncSession):
    """Factory that creates BudgetAccount rows with optional card_last4."""
    from app.models.budget import BudgetAccount

    async def _make(family_id, *, name: str = "Test Account",
                    card_last4: str | None = None,
                    currency: str = "MXN",
                    account_type: str = "checking",
                    closed: bool = False):
        acct = BudgetAccount(
            family_id=family_id,
            name=name,
            type=account_type,
            currency=currency,
            card_last4=card_last4,
            closed=closed,
        )
        db.add(acct)
        await db.commit()
        await db.refresh(acct)
        return acct

    return _make


@pytest_asyncio.fixture
async def transaction_factory_for_account(db: AsyncSession, family):
    """Factory that creates a BudgetTransaction on a specific account.

    The ``user_id`` kwarg is persisted as ``created_by_id`` so the per-user
    last-used fallback in AccountMatchingService (Strategy 3a) actually
    exercises the filter path under test.
    """
    from app.models.budget import BudgetTransaction
    from datetime import date as date_type

    async def _make(account_id, *, user_id=None, amount: int = -10000):
        tx = BudgetTransaction(
            family_id=family.id,
            account_id=account_id,
            date=date_type.today(),
            amount=amount,
            created_by_id=user_id,
        )
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        return tx

    return _make


# ---------------------------------------------------------------------------
# Fixtures for Task 6: DuplicateGuardService
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def payee(db: AsyncSession, family):
    """A BudgetPayee belonging to the shared family fixture."""
    from app.models.budget import BudgetPayee
    p = BudgetPayee(family_id=family.id, name="Test Payee")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@pytest_asyncio.fixture
async def transaction_factory_with_payee(db: AsyncSession, family):
    """Factory: creates a BudgetTransaction with a specific payee + amount.

    If created_at is provided, the timestamp is forced after flush because
    the column uses server_default=now() — SQLAlchemy only populates it on
    INSERT, so we override it with a direct UPDATE after the flush.
    """
    from app.models.budget import BudgetAccount, BudgetTransaction
    from datetime import date as date_type

    acct = BudgetAccount(
        family_id=family.id, name="DupGuard Account",
        type="checking", currency="MXN",
    )
    db.add(acct)
    await db.commit()
    await db.refresh(acct)

    async def _make(family_id, payee_id, *, amount: int = -10000,
                    created_at=None, date=None, receipt_image_path=None):
        tx = BudgetTransaction(
            family_id=family_id,
            account_id=acct.id,
            date=date if date is not None else date_type.today(),
            amount=amount,
            payee_id=payee_id,
            receipt_image_path=receipt_image_path,
        )
        db.add(tx)
        await db.flush()          # assigns PK + server_default created_at
        if created_at is not None:
            # Override the server-generated timestamp with the requested value
            from sqlalchemy import update
            from app.models.budget import BudgetTransaction as _BT
            await db.execute(
                update(_BT)
                .where(_BT.id == tx.id)
                .values(created_at=created_at)
            )
        await db.commit()
        await db.refresh(tx)
        return tx

    return _make
