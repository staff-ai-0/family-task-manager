#!/usr/bin/env python3
"""
Seed Data Script for Family Task Manager

Creates demo data for testing and development:
- 1 demo family with 2 parents and 2 children
- 5 default tasks and 3 extra tasks
- 5 rewards
- Sample point transactions
"""

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.user import User, UserRole
from app.models.family import Family
from app.models.task import Task, TaskStatus, TaskFrequency
from app.models.reward import Reward, RewardCategory
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.password_reset import PasswordResetToken
from app.models.email_verification import EmailVerificationToken
from app.models.consequence import Consequence
from app.core.security import get_password_hash
from app.core.database import Base

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://familyapp:familyapp123@localhost:5433/familyapp",
)


async def clear_existing_data(session: AsyncSession):
    """Clear all existing data"""
    print("🧹 Clearing existing data...")

    # Delete in correct order (respecting foreign keys)
    tables = [
        "point_transactions",
        "tasks",
        "rewards",
        "consequences",
        "users",
        "families",
    ]

    for table in tables:
        try:
            await session.execute(text(f"DELETE FROM {table}"))
        except Exception as e:
            print(f"Warning: Could not delete from {table}: {e}")

    await session.commit()
    print("✅ Data cleared")


async def create_demo_family(session: AsyncSession):
    """Create a demo family with users"""
    print("\n👨‍👩‍👧‍👦 Creating demo family...")

    # Create family
    family = Family(name="Demo Family")
    session.add(family)
    await session.flush()

    # Create parents
    parent1 = User(
        email="mom@demo.com",
        password_hash=get_password_hash("password123"),
        name="Sarah Johnson",
        role=UserRole.PARENT,
        family_id=family.id,
        email_verified=True,
        points=500,
    )

    parent2 = User(
        email="dad@demo.com",
        password_hash=get_password_hash("password123"),
        name="Mike Johnson",
        role=UserRole.PARENT,
        family_id=family.id,
        email_verified=True,
        points=300,
    )

    # Create children
    child1 = User(
        email="emma@demo.com",
        password_hash=get_password_hash("password123"),
        name="Emma Johnson",
        role=UserRole.CHILD,
        family_id=family.id,
        email_verified=True,
        points=150,
    )

    child2 = User(
        email="lucas@demo.com",
        password_hash=get_password_hash("password123"),
        name="Lucas Johnson",
        role=UserRole.TEEN,
        family_id=family.id,
        email_verified=True,
        points=280,
    )

    session.add_all([parent1, parent2, child1, child2])
    await session.commit()

    print(f"✅ Created family: {family.name}")
    print(f"   Parents: {parent1.name}, {parent2.name}")
    print(f"   Children: {child1.name}, {child2.name}")

    return family, parent1, child1, child2


async def create_demo_tasks(
    session: AsyncSession, family: Family, parent: User, children: list[User]
):
    """Create demo tasks"""
    print("\n📝 Creating demo tasks...")

    tasks_data = [
        # Default tasks (obligatory)
        {
            "title": "Make Your Bed",
            "description": "Make your bed neatly every morning",
            "points": 20,
            "is_default": True,
            "frequency": TaskFrequency.DAILY,
            "assigned_to": children[0],
        },
        {
            "title": "Complete Homework",
            "description": "Finish all homework before dinner",
            "points": 50,
            "is_default": True,
            "frequency": TaskFrequency.DAILY,
            "assigned_to": children[0],
        },
        {
            "title": "Clean Your Room",
            "description": "Pick up toys and organize your space",
            "points": 30,
            "is_default": True,
            "frequency": TaskFrequency.WEEKLY,
            "assigned_to": children[1],
        },
        {
            "title": "Feed the Pet",
            "description": "Give food and water to the family pet",
            "points": 15,
            "is_default": True,
            "frequency": TaskFrequency.DAILY,
            "assigned_to": children[1],
        },
        {
            "title": "Brush Teeth",
            "description": "Brush teeth morning and night",
            "points": 10,
            "is_default": True,
            "frequency": TaskFrequency.DAILY,
            "assigned_to": children[0],
        },
        # Extra tasks (optional)
        {
            "title": "Help With Dishes",
            "description": "Help wash or dry dishes after dinner",
            "points": 40,
            "is_default": False,
            "frequency": TaskFrequency.DAILY,
            "assigned_to": children[1],
        },
        {
            "title": "Vacuum Living Room",
            "description": "Vacuum the living room and hallway",
            "points": 75,
            "is_default": False,
            "frequency": TaskFrequency.WEEKLY,
            "assigned_to": children[1],
        },
        {
            "title": "Help With Laundry",
            "description": "Fold and put away your clean clothes",
            "points": 60,
            "is_default": False,
            "frequency": TaskFrequency.WEEKLY,
            "assigned_to": children[0],
        },
    ]

    tasks = []
    for task_data in tasks_data:
        assigned_to = task_data.pop("assigned_to")
        task = Task(
            family_id=family.id,
            created_by=parent.id,
            assigned_to=assigned_to.id,
            status=TaskStatus.PENDING,
            due_date=date.today(),
            **task_data,
        )
        tasks.append(task)

    session.add_all(tasks)
    await session.commit()

    print(f"✅ Created {len(tasks)} tasks")
    print(f"   Default tasks: {sum(1 for t in tasks if t.is_default)}")
    print(f"   Extra tasks: {sum(1 for t in tasks if not t.is_default)}")

    return tasks


async def create_demo_rewards(session: AsyncSession, family: Family, parent: User):
    """Create demo rewards"""
    print("\n🎁 Creating demo rewards...")

    rewards_data = [
        {
            "title": "30 Minutes Screen Time",
            "description": "Extra 30 minutes for games, TV, or tablet",
            "points_cost": 100,
            "category": RewardCategory.SCREEN_TIME,
            "icon": "🎮",
        },
        {
            "title": "Ice Cream Trip",
            "description": "Trip to get your favorite ice cream",
            "points_cost": 150,
            "category": RewardCategory.TREATS,
            "icon": "🍦",
        },
        {
            "title": "Movie Night Pick",
            "description": "Choose the movie for family movie night",
            "points_cost": 120,
            "category": RewardCategory.PRIVILEGES,
            "icon": "🎬",
        },
        {
            "title": "Later Bedtime",
            "description": "Stay up 30 minutes past bedtime (one night)",
            "points_cost": 200,
            "category": RewardCategory.PRIVILEGES,
            "icon": "🌙",
        },
        {
            "title": "Small Toy/Book",
            "description": "Pick a small toy or book ($10 or less)",
            "points_cost": 500,
            "category": RewardCategory.TOYS,
            "icon": "🎁",
        },
    ]

    rewards = []
    for reward_data in rewards_data:
        reward = Reward(
            family_id=family.id, is_active=True, **reward_data
        )
        rewards.append(reward)

    session.add_all(rewards)
    await session.commit()

    print(f"✅ Created {len(rewards)} rewards")
    for reward in rewards:
        print(f"   {reward.icon} {reward.title} - {reward.points_cost} points")

    return rewards


async def create_demo_transactions(
    session: AsyncSession, users: list[User], tasks: list[Task], rewards: list[Reward]
):
    """Create sample point transactions"""
    print("\n💰 Creating demo transactions...")

    transactions = []
    child = users[2]  # Emma

    # Some completed tasks
    transaction1 = PointTransaction(
        user_id=child.id,
        task_id=tasks[0].id,
        points=tasks[0].points,
        type=TransactionType.TASK_COMPLETED,
        balance_before=0,
        balance_after=tasks[0].points,
    )

    transaction2 = PointTransaction(
        user_id=child.id,
        task_id=tasks[1].id,
        points=tasks[1].points,
        type=TransactionType.TASK_COMPLETED,
        balance_before=tasks[0].points,
        balance_after=tasks[0].points + tasks[1].points,
    )

    # A redeemed reward
    transaction3 = PointTransaction(
        user_id=child.id,
        reward_id=rewards[0].id,
        points=-rewards[0].points_cost,
        type=TransactionType.REWARD_REDEEMED,
        balance_before=tasks[0].points + tasks[1].points,
        balance_after=tasks[0].points + tasks[1].points - rewards[0].points_cost,
    )

    transactions.extend([transaction1, transaction2, transaction3])

    session.add_all(transactions)
    await session.commit()

    print(f"✅ Created {len(transactions)} sample transactions")

    return transactions


async def main():
    """Main seed script"""
    print("=" * 60)
    print("🌱 Family Task Manager - Seed Data Script")
    print("=" * 60)

    # Create engine
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session_maker() as session:
        # Clear existing data
        await clear_existing_data(session)

        # Create demo data
        family, parent, child1, child2 = await create_demo_family(session)
        tasks = await create_demo_tasks(session, family, parent, [child1, child2])
        rewards = await create_demo_rewards(session, family, parent)
        transactions = await create_demo_transactions(
            session, [parent, child1, child2], tasks, rewards
        )

        print("\n" + "=" * 60)
        print("✅ Seed data created successfully!")
        print("=" * 60)
        print("\n📋 Demo Credentials:")
        print("   Parent: mom@demo.com / password123")
        print("   Parent: dad@demo.com / password123")
        print("   Child: emma@demo.com / password123")
        print("   Teen: lucas@demo.com / password123")
        print("\n🚀 Start the app with: ./dev.sh")
        print("   Then login at: http://localhost:8000")
        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
