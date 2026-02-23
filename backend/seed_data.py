#!/usr/bin/env python3
"""
Seed Data Script for Family Task Manager

Creates demo data for testing and development:
- 1 demo family with 2 parents and 2 children
- Task templates (regular + bonus) with weekly shuffle
- 5 rewards
- Sample point transactions
"""

import asyncio
import random
import sys
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.user import User, UserRole
from app.models.family import Family
from app.models.task_template import TaskTemplate
from app.models.task_assignment import TaskAssignment, AssignmentStatus
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
    print("Clearing existing data...")

    # Delete in correct order (respecting foreign keys)
    tables = [
        "point_transactions",
        "task_assignments",
        "task_templates",
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
    print("Data cleared")


async def create_demo_family(session: AsyncSession):
    """Create a demo family with users"""
    print("\nCreating demo family...")

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

    print(f"Created family: {family.name}")
    print(f"   Parents: {parent1.name}, {parent2.name}")
    print(f"   Children: {child1.name}, {child2.name}")

    return family, parent1, parent2, child1, child2


async def create_demo_templates(
    session: AsyncSession, family: Family, parent: User
):
    """Create demo task templates (regular + bonus)"""
    print("\nCreating task templates...")

    templates_data = [
        # Regular daily tasks
        {
            "title": "Make Your Bed",
            "description": "Make your bed neatly every morning",
            "points": 20,
            "interval_days": 1,
            "is_bonus": False,
        },
        {
            "title": "Complete Homework",
            "description": "Finish all homework before dinner",
            "points": 50,
            "interval_days": 1,
            "is_bonus": False,
        },
        {
            "title": "Brush Teeth",
            "description": "Brush teeth morning and night",
            "points": 10,
            "interval_days": 1,
            "is_bonus": False,
        },
        {
            "title": "Feed the Pet",
            "description": "Give food and water to the family pet",
            "points": 15,
            "interval_days": 1,
            "is_bonus": False,
        },
        # Regular tasks every 3 days
        {
            "title": "Take Out Trash",
            "description": "Empty trash cans and take bags to the curb",
            "points": 25,
            "interval_days": 3,
            "is_bonus": False,
        },
        # Regular weekly tasks
        {
            "title": "Clean Your Room",
            "description": "Pick up toys and organize your space",
            "points": 30,
            "interval_days": 7,
            "is_bonus": False,
        },
        # Bonus tasks (optional, require all required tasks done first)
        {
            "title": "Help With Dishes",
            "description": "Help wash or dry dishes after dinner",
            "points": 40,
            "interval_days": 1,
            "is_bonus": True,
        },
        {
            "title": "Vacuum Living Room",
            "description": "Vacuum the living room and hallway",
            "points": 75,
            "interval_days": 7,
            "is_bonus": True,
        },
        {
            "title": "Help With Laundry",
            "description": "Fold and put away your clean clothes",
            "points": 60,
            "interval_days": 7,
            "is_bonus": True,
        },
    ]

    templates = []
    for tdata in templates_data:
        template = TaskTemplate(
            family_id=family.id,
            created_by=parent.id,
            is_active=True,
            **tdata,
        )
        templates.append(template)

    session.add_all(templates)
    await session.commit()

    regular = [t for t in templates if not t.is_bonus]
    bonus = [t for t in templates if t.is_bonus]
    print(f"Created {len(templates)} task templates")
    print(f"   Regular: {len(regular)} (shuffled across members)")
    print(f"   Bonus: {len(bonus)} (assigned to all members)")

    return templates


async def run_shuffle(
    session: AsyncSession,
    family: Family,
    templates: list[TaskTemplate],
    members: list[User],
):
    """Run the shuffle algorithm to create assignments for the current week"""
    print("\nShuffling tasks for the current week...")

    today = date.today()
    week_monday = today - timedelta(days=today.weekday())

    regular_templates = [t for t in templates if not t.is_bonus]
    bonus_templates = [t for t in templates if t.is_bonus]

    assignments = []

    # Expand regular templates into (template, date) instances
    instances = []
    for template in regular_templates:
        current = week_monday
        week_end = week_monday + timedelta(days=6)
        while current <= week_end:
            instances.append((template, current))
            current += timedelta(days=template.interval_days)

    # Shuffle and distribute via round-robin
    random.shuffle(instances)
    for i, (template, assigned_date) in enumerate(instances):
        member = members[i % len(members)]
        assignment = TaskAssignment(
            template_id=template.id,
            assigned_to=member.id,
            family_id=family.id,
            status=AssignmentStatus.PENDING,
            assigned_date=assigned_date,
            week_of=week_monday,
        )
        assignments.append(assignment)

    # Bonus templates: assign to ALL members on their dates
    for template in bonus_templates:
        current = week_monday
        week_end = week_monday + timedelta(days=6)
        while current <= week_end:
            for member in members:
                assignment = TaskAssignment(
                    template_id=template.id,
                    assigned_to=member.id,
                    family_id=family.id,
                    status=AssignmentStatus.PENDING,
                    assigned_date=current,
                    week_of=week_monday,
                )
                assignments.append(assignment)
            current += timedelta(days=template.interval_days)

    # Mark some past assignments as COMPLETED for demo variety
    for assignment in assignments:
        if assignment.assigned_date < today:
            # 70% chance of being completed for past dates
            if random.random() < 0.7:
                assignment.status = AssignmentStatus.COMPLETED
                assignment.completed_at = datetime.combine(
                    assignment.assigned_date, datetime.min.time()
                ).replace(hour=15, minute=30)

    session.add_all(assignments)
    await session.commit()

    completed = sum(1 for a in assignments if a.status == AssignmentStatus.COMPLETED)
    print(f"Created {len(assignments)} assignments for week of {week_monday}")
    print(f"   Regular: {len([a for a in instances])}")
    print(f"   Bonus: {len(assignments) - len(instances)}")
    print(f"   Pre-completed (past dates): {completed}")

    return assignments


async def create_demo_rewards(session: AsyncSession, family: Family, parent: User):
    """Create demo rewards"""
    print("\nCreating demo rewards...")

    rewards_data = [
        {
            "title": "30 Minutes Screen Time",
            "description": "Extra 30 minutes for games, TV, or tablet",
            "points_cost": 100,
            "category": RewardCategory.SCREEN_TIME,
            "icon": "screen",
        },
        {
            "title": "Ice Cream Trip",
            "description": "Trip to get your favorite ice cream",
            "points_cost": 150,
            "category": RewardCategory.TREATS,
            "icon": "treat",
        },
        {
            "title": "Movie Night Pick",
            "description": "Choose the movie for family movie night",
            "points_cost": 120,
            "category": RewardCategory.PRIVILEGES,
            "icon": "movie",
        },
        {
            "title": "Later Bedtime",
            "description": "Stay up 30 minutes past bedtime (one night)",
            "points_cost": 200,
            "category": RewardCategory.PRIVILEGES,
            "icon": "bedtime",
        },
        {
            "title": "Small Toy/Book",
            "description": "Pick a small toy or book ($10 or less)",
            "points_cost": 500,
            "category": RewardCategory.TOYS,
            "icon": "toy",
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

    print(f"Created {len(rewards)} rewards")
    for reward in rewards:
        print(f"   {reward.title} - {reward.points_cost} points")

    return rewards


async def create_demo_transactions(
    session: AsyncSession,
    child: User,
    assignments: list[TaskAssignment],
    rewards: list[Reward],
):
    """Create sample point transactions from completed assignments"""
    print("\nCreating demo transactions...")

    transactions = []
    completed_assignments = [a for a in assignments if a.status == AssignmentStatus.COMPLETED and a.assigned_to == child.id]

    running_balance = 0
    for assignment in completed_assignments[:3]:  # First 3 completed
        # We need the template points; get from the assignment's template
        # Since templates are already in session we just reference the points from the template list
        points = 20  # Default; in real usage this comes from template
        transaction = PointTransaction(
            user_id=child.id,
            assignment_id=assignment.id,
            points=points,
            type=TransactionType.TASK_COMPLETED,
            balance_before=running_balance,
            balance_after=running_balance + points,
        )
        running_balance += points
        transactions.append(transaction)

    # A redeemed reward
    if rewards:
        transaction = PointTransaction(
            user_id=child.id,
            reward_id=rewards[0].id,
            points=-rewards[0].points_cost,
            type=TransactionType.REWARD_REDEEMED,
            balance_before=running_balance,
            balance_after=running_balance - rewards[0].points_cost,
        )
        transactions.append(transaction)

    session.add_all(transactions)
    await session.commit()

    print(f"Created {len(transactions)} sample transactions")

    return transactions


async def main():
    """Main seed script"""
    print("=" * 60)
    print("Family Task Manager - Seed Data Script")
    print("=" * 60)

    # Create engine
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session_maker() as session:
        # Clear existing data
        await clear_existing_data(session)

        # Create demo data
        family, parent1, parent2, child1, child2 = await create_demo_family(session)
        all_members = [parent1, parent2, child1, child2]

        # Create task templates
        templates = await create_demo_templates(session, family, parent1)

        # Run the shuffle to create weekly assignments
        assignments = await run_shuffle(session, family, templates, all_members)

        # Create rewards
        rewards = await create_demo_rewards(session, family, parent1)

        # Create sample transactions
        transactions = await create_demo_transactions(
            session, child1, assignments, rewards
        )

        print("\n" + "=" * 60)
        print("Seed data created successfully!")
        print("=" * 60)
        print("\nDemo Credentials:")
        print("   Parent: mom@demo.com / password123")
        print("   Parent: dad@demo.com / password123")
        print("   Child: emma@demo.com / password123")
        print("   Teen: lucas@demo.com / password123")
        print("\nStart the app with: docker-compose up -d")
        print("   Then login at: http://localhost:3000")
        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
