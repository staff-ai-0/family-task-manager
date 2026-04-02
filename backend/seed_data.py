#!/usr/bin/env python3
"""
Comprehensive Seed Data Script for Family Task Manager

Creates demo data for ALL features:
- 1 demo family with 2 parents, 1 child, 1 teen
- Task templates (regular + bonus) with weekly shuffle
- Rewards (all categories)
- Consequences (active + resolved)
- Point transactions (all types)
- Budget: accounts, payees, category groups, categories, allocations,
  transactions (income/expenses/transfers/splits), goals, recurring,
  categorization rules
- Family invitation (pending)
"""

import asyncio
import random
import secrets
import sys
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.user import User, UserRole
from app.models.family import Family
from app.models.task_template import TaskTemplate
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.reward import Reward, RewardCategory
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.consequence import Consequence, ConsequenceSeverity, RestrictionType
from app.models.invitation import FamilyInvitation, InvitationStatus
from app.models.budget import (
    BudgetAccount,
    BudgetAllocation,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetCategorizationRule,
    BudgetGoal,
    BudgetPayee,
    BudgetRecurringTransaction,
    BudgetTransaction,
)
from app.core.security import get_password_hash

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://familyapp:familyapp123@localhost:5433/familyapp",
)

TODAY = date.today()
THIS_MONTH = TODAY.replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)
TWO_MONTHS_AGO = (LAST_MONTH - timedelta(days=1)).replace(day=1)


async def clear_all(session: AsyncSession):
    """Clear all data in FK-safe order"""
    print("Clearing existing data...")
    tables = [
        "budget_recurring_transactions",
        "budget_goals",
        "budget_categorization_rules",
        "budget_transactions",
        "budget_allocations",
        "budget_categories",
        "budget_category_groups",
        "budget_payees",
        "budget_accounts",
        "budget_sync_state",
        "point_transactions",
        "consequences",
        "task_assignments",
        "task_templates",
        "tasks",
        "rewards",
        "family_invitations",
        "email_verification_tokens",
        "password_reset_tokens",
        "users",
        "families",
    ]
    for table in tables:
        try:
            await session.execute(text(f"DELETE FROM {table}"))
        except Exception as e:
            print(f"  Warning: {table}: {e}")
    await session.commit()
    print("  Done.\n")


async def create_family_and_users(session: AsyncSession):
    """Create demo family with 4 members"""
    print("Creating family & users...")
    family = Family(name="Demo Family")
    session.add(family)
    await session.flush()

    pw = get_password_hash("password123")
    users_data = [
        ("Sarah Johnson", "mom@demo.com", UserRole.PARENT, 500),
        ("Mike Johnson", "dad@demo.com", UserRole.PARENT, 300),
        ("Emma Johnson", "emma@demo.com", UserRole.CHILD, 150),
        ("Lucas Johnson", "lucas@demo.com", UserRole.TEEN, 280),
    ]
    users = []
    for name, email, role, points in users_data:
        u = User(
            email=email, password_hash=pw, name=name, role=role,
            family_id=family.id, email_verified=True, points=points,
        )
        users.append(u)
    session.add_all(users)
    await session.commit()

    mom, dad, emma, lucas = users
    print(f"  Family: {family.name}")
    print(f"  Parents: {mom.name}, {dad.name}")
    print(f"  Children: {emma.name} (child), {lucas.name} (teen)")
    return family, mom, dad, emma, lucas


async def create_task_templates(session: AsyncSession, family, parent):
    """Create task templates — regular + bonus"""
    print("\nCreating task templates...")
    templates_data = [
        ("Make Your Bed", "Hacer la Cama", "Make your bed neatly", "Haz tu cama ordenadamente", 20, 1, False),
        ("Complete Homework", "Terminar la Tarea", "Finish homework before dinner", "Termina la tarea antes de cenar", 50, 1, False),
        ("Brush Teeth", "Cepillar Dientes", "Brush morning and night", "Cepíllate mañana y noche", 10, 1, False),
        ("Feed the Pet", "Alimentar Mascota", "Give food and water to the pet", "Dale comida y agua a la mascota", 15, 1, False),
        ("Take Out Trash", "Sacar la Basura", "Empty trash cans", "Vacía los botes de basura", 25, 3, False),
        ("Clean Your Room", "Limpiar Cuarto", "Pick up toys and organize", "Recoge juguetes y organiza", 30, 7, False),
        ("Help With Dishes", "Ayudar con Platos", "Wash or dry dishes after dinner", "Lava o seca los platos", 40, 1, True),
        ("Vacuum Living Room", "Aspirar la Sala", "Vacuum living room and hallway", "Aspira sala y pasillo", 75, 7, True),
        ("Help With Laundry", "Ayudar con Ropa", "Fold and put away clothes", "Dobla y guarda la ropa", 60, 7, True),
    ]
    templates = []
    for title, title_es, desc, desc_es, pts, interval, bonus in templates_data:
        t = TaskTemplate(
            family_id=family.id, created_by=parent.id, is_active=True,
            title=title, title_es=title_es, description=desc,
            description_es=desc_es, points=pts, interval_days=interval,
            is_bonus=bonus,
        )
        templates.append(t)
    session.add_all(templates)
    await session.commit()
    print(f"  Created {len(templates)} templates ({sum(1 for t in templates if not t.is_bonus)} regular, {sum(1 for t in templates if t.is_bonus)} bonus)")
    return templates


async def create_assignments(session: AsyncSession, family, templates, members):
    """Shuffle tasks into weekly assignments"""
    print("\nCreating weekly task assignments...")
    week_monday = TODAY - timedelta(days=TODAY.weekday())
    regular = [t for t in templates if not t.is_bonus]
    bonus = [t for t in templates if t.is_bonus]
    assignments = []

    # Regular: expand into (template, date) then round-robin
    instances = []
    for t in regular:
        current = week_monday
        while current <= week_monday + timedelta(days=6):
            instances.append((t, current))
            current += timedelta(days=t.interval_days)
    random.shuffle(instances)
    for i, (t, d) in enumerate(instances):
        member = members[i % len(members)]
        a = TaskAssignment(
            template_id=t.id, assigned_to=member.id, family_id=family.id,
            status=AssignmentStatus.PENDING, assigned_date=d, week_of=week_monday,
        )
        assignments.append(a)

    # Bonus: assign to all members
    for t in bonus:
        current = week_monday
        while current <= week_monday + timedelta(days=6):
            for member in members:
                a = TaskAssignment(
                    template_id=t.id, assigned_to=member.id, family_id=family.id,
                    status=AssignmentStatus.PENDING, assigned_date=current, week_of=week_monday,
                )
                assignments.append(a)
            current += timedelta(days=t.interval_days)

    # Mark ~70% of past dates as completed
    for a in assignments:
        if a.assigned_date < TODAY and random.random() < 0.7:
            a.status = AssignmentStatus.COMPLETED
            a.completed_at = datetime.combine(a.assigned_date, datetime.min.time()).replace(hour=15, minute=30)

    session.add_all(assignments)
    await session.commit()
    completed = sum(1 for a in assignments if a.status == AssignmentStatus.COMPLETED)
    print(f"  {len(assignments)} assignments for week of {week_monday}")
    print(f"  {completed} pre-completed (past dates)")
    return assignments


async def create_rewards(session: AsyncSession, family, parent):
    """Create rewards across all categories"""
    print("\nCreating rewards...")
    rewards_data = [
        ("30 Min Screen Time", "Extra 30 min for games/TV/tablet", 100, RewardCategory.SCREEN_TIME, "screen"),
        ("Ice Cream Trip", "Trip to get your favorite ice cream", 150, RewardCategory.TREATS, "treat"),
        ("Movie Night Pick", "Choose the movie for movie night", 120, RewardCategory.PRIVILEGES, "movie"),
        ("Later Bedtime", "Stay up 30 min past bedtime", 200, RewardCategory.PRIVILEGES, "bedtime"),
        ("Small Toy/Book", "Pick a toy or book ($10 or less)", 500, RewardCategory.TOYS, "toy"),
        ("Park Visit", "Trip to the park of your choice", 80, RewardCategory.ACTIVITIES, "park"),
        ("$5 Allowance Bonus", "Extra $5 added to allowance", 300, RewardCategory.MONEY, "money"),
    ]
    rewards = []
    for title, desc, cost, cat, icon in rewards_data:
        r = Reward(
            family_id=family.id, title=title, description=desc,
            points_cost=cost, category=cat, icon=icon, is_active=True,
        )
        rewards.append(r)
    session.add_all(rewards)
    await session.commit()
    print(f"  {len(rewards)} rewards across {len(set(r.category for r in rewards))} categories")
    return rewards


async def create_consequences(session: AsyncSession, family, emma, lucas, assignments):
    """Create consequences — active and resolved"""
    print("\nCreating consequences...")
    now = datetime.now(timezone.utc)

    # Find a completed assignment to link
    emma_assignments = [a for a in assignments if a.assigned_to == emma.id]
    lucas_assignments = [a for a in assignments if a.assigned_to == lucas.id]

    consequences = [
        # Active consequence for Emma — missed homework
        Consequence(
            title="No Screen Time",
            description="Missed homework 2 days in a row",
            severity=ConsequenceSeverity.MEDIUM,
            restriction_type=RestrictionType.SCREEN_TIME,
            duration_days=3,
            active=True, resolved=False,
            applied_to_user=emma.id, family_id=family.id,
            triggered_by_assignment_id=emma_assignments[0].id if emma_assignments else None,
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=2),
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
        ),
        # Resolved consequence for Lucas
        Consequence(
            title="No Bonus Tasks",
            description="Didn't take out the trash for a week",
            severity=ConsequenceSeverity.LOW,
            restriction_type=RestrictionType.EXTRA_TASKS,
            duration_days=2,
            active=False, resolved=True,
            applied_to_user=lucas.id, family_id=family.id,
            triggered_by_assignment_id=lucas_assignments[0].id if lucas_assignments else None,
            start_date=now - timedelta(days=5),
            end_date=now - timedelta(days=3),
            resolved_at=now - timedelta(days=3),
            created_at=now - timedelta(days=5),
            updated_at=now - timedelta(days=3),
        ),
        # Active consequence for Lucas — high severity
        Consequence(
            title="Reduced Allowance",
            description="Repeatedly left room messy after warnings",
            severity=ConsequenceSeverity.HIGH,
            restriction_type=RestrictionType.ALLOWANCE,
            duration_days=7,
            active=True, resolved=False,
            applied_to_user=lucas.id, family_id=family.id,
            start_date=now - timedelta(days=2),
            end_date=now + timedelta(days=5),
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(days=2),
        ),
    ]
    session.add_all(consequences)
    await session.commit()
    active = sum(1 for c in consequences if c.active)
    print(f"  {len(consequences)} consequences ({active} active, {len(consequences) - active} resolved)")
    return consequences


async def create_point_transactions(session: AsyncSession, family, mom, emma, lucas, assignments, rewards):
    """Create diverse point transactions"""
    print("\nCreating point transactions...")
    transactions = []

    # Task completion transactions for Emma
    emma_completed = [a for a in assignments if a.assigned_to == emma.id and a.status == AssignmentStatus.COMPLETED]
    balance = 0
    for a in emma_completed[:5]:
        pts = 20
        t = PointTransaction(
            user_id=emma.id, assignment_id=a.id, points=pts,
            type=TransactionType.TASK_COMPLETED, balance_before=balance,
            balance_after=balance + pts, description=f"Completed task and earned {pts} points",
        )
        balance += pts
        transactions.append(t)

    # Reward redemption for Emma
    if rewards:
        cost = rewards[0].points_cost
        t = PointTransaction(
            user_id=emma.id, reward_id=rewards[0].id, points=-cost,
            type=TransactionType.REWARD_REDEEMED, balance_before=balance,
            balance_after=balance - cost, description=f"Redeemed reward for {cost} points",
        )
        balance -= cost
        transactions.append(t)

    # Parent adjustment — bonus for good behavior
    t = PointTransaction(
        user_id=emma.id, points=50,
        type=TransactionType.PARENT_ADJUSTMENT, balance_before=balance,
        balance_after=balance + 50, description="Bonus for helping grandma",
        created_by=mom.id,
    )
    balance += 50
    transactions.append(t)

    # Penalty for Lucas
    lucas_balance = 280
    t = PointTransaction(
        user_id=lucas.id, points=-30,
        type=TransactionType.PENALTY, balance_before=lucas_balance,
        balance_after=lucas_balance - 30, description="Left room messy after warning",
        created_by=mom.id,
    )
    lucas_balance -= 30
    transactions.append(t)

    # Bonus for Lucas
    t = PointTransaction(
        user_id=lucas.id, points=100,
        type=TransactionType.BONUS, balance_before=lucas_balance,
        balance_after=lucas_balance + 100, description="Perfect week — all tasks completed!",
        created_by=mom.id,
    )
    lucas_balance += 100
    transactions.append(t)

    # Task completions for Lucas
    lucas_completed = [a for a in assignments if a.assigned_to == lucas.id and a.status == AssignmentStatus.COMPLETED]
    for a in lucas_completed[:4]:
        pts = 25
        t = PointTransaction(
            user_id=lucas.id, assignment_id=a.id, points=pts,
            type=TransactionType.TASK_COMPLETED, balance_before=lucas_balance,
            balance_after=lucas_balance + pts, description=f"Completed task and earned {pts} points",
        )
        lucas_balance += pts
        transactions.append(t)

    session.add_all(transactions)
    await session.commit()
    print(f"  {len(transactions)} transactions ({len(set(t.type for t in transactions))} types)")
    return transactions


async def create_invitation(session: AsyncSession, family, mom):
    """Create a pending family invitation"""
    print("\nCreating family invitation...")
    inv = FamilyInvitation(
        family_id=family.id,
        invited_email="aunt@example.com",
        invited_by_user_id=mom.id,
        invitation_code=secrets.token_urlsafe(24),
        status=InvitationStatus.PENDING,
        role=UserRole.PARENT,
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    session.add(inv)
    await session.commit()
    print(f"  Pending invitation for aunt@example.com (code: {inv.invitation_code[:12]}...)")
    return inv


# ─── BUDGET SECTION ──────────────────────────────────────────────────────────

async def create_budget_accounts(session: AsyncSession, family):
    """Create budget accounts"""
    print("\nCreating budget accounts...")
    accounts_data = [
        ("Checking - BBVA", "checking", False, False, 2500000, 0),       # $25,000.00
        ("Savings - BBVA", "savings", False, False, 8000000, 1),          # $80,000.00
        ("Credit Card - Amex", "credit", False, False, -350000, 2),       # -$3,500.00 owed
        ("Emergency Fund", "savings", True, False, 15000000, 3),          # $150,000 off-budget
        ("Old Account", "checking", False, True, 0, 4),                    # closed account
    ]
    accounts = []
    for name, atype, offbudget, closed, balance, sort in accounts_data:
        a = BudgetAccount(
            family_id=family.id, name=name, type=atype, offbudget=offbudget,
            closed=closed, starting_balance=balance, sort_order=sort,
        )
        accounts.append(a)
    session.add_all(accounts)
    await session.commit()
    on_budget = sum(1 for a in accounts if not a.offbudget and not a.closed)
    print(f"  {len(accounts)} accounts ({on_budget} on-budget, {sum(1 for a in accounts if a.offbudget)} tracking, {sum(1 for a in accounts if a.closed)} closed)")
    return accounts


async def create_budget_payees(session: AsyncSession, family):
    """Create budget payees"""
    print("\nCreating budget payees...")
    payee_names = [
        "Walmart", "Costco", "CFE (Electric)", "Telmex (Internet)",
        "Netflix", "Spotify", "Gasolinera", "Farmacia Guadalajara",
        "School Tuition", "Pediatrician", "Restaurant El Fogón",
        "Amazon", "Mercado Libre", "Uber / DiDi", "Water Bill",
    ]
    payees = []
    for name in payee_names:
        p = BudgetPayee(family_id=family.id, name=name)
        payees.append(p)
    session.add_all(payees)
    await session.commit()
    print(f"  {len(payees)} payees")
    return payees


async def create_budget_categories(session: AsyncSession, family):
    """Create category groups and categories"""
    print("\nCreating budget category groups & categories...")

    groups_data = [
        ("Income", True, [
            ("Salary", 0),
            ("Freelance", 0),
            ("Other Income", 0),
        ]),
        ("Housing", False, [
            ("Rent / Mortgage", 1200000),
            ("Utilities", 300000),
            ("Home Maintenance", 200000),
        ]),
        ("Groceries & Food", False, [
            ("Groceries", 800000),
            ("Dining Out", 300000),
            ("Coffee & Snacks", 100000),
        ]),
        ("Transportation", False, [
            ("Gas", 400000),
            ("Ride Share", 150000),
            ("Car Maintenance", 200000),
        ]),
        ("Kids & Education", False, [
            ("School Tuition", 500000),
            ("School Supplies", 100000),
            ("Extracurriculars", 200000),
            ("Kids Allowance", 100000),
        ]),
        ("Health", False, [
            ("Doctor Visits", 200000),
            ("Pharmacy", 150000),
            ("Insurance", 400000),
        ]),
        ("Entertainment", False, [
            ("Subscriptions", 50000),
            ("Movies & Outings", 150000),
            ("Hobbies", 100000),
        ]),
        ("Savings Goals", False, [
            ("Emergency Fund", 500000),
            ("Vacation Fund", 300000),
            ("Kids College", 200000),
        ]),
    ]

    all_groups = []
    all_categories = []
    for sort_order, (group_name, is_income, cats) in enumerate(groups_data):
        g = BudgetCategoryGroup(
            family_id=family.id, name=group_name,
            sort_order=sort_order, is_income=is_income,
        )
        session.add(g)
        await session.flush()
        all_groups.append(g)

        for cat_sort, (cat_name, goal) in enumerate(cats):
            c = BudgetCategory(
                family_id=family.id, group_id=g.id, name=cat_name,
                sort_order=cat_sort, goal_amount=goal,
            )
            all_categories.append(c)

    session.add_all(all_categories)
    await session.commit()
    print(f"  {len(all_groups)} groups, {len(all_categories)} categories")
    return all_groups, all_categories


async def create_budget_allocations(session: AsyncSession, family, categories):
    """Create monthly budget allocations for last 3 months"""
    print("\nCreating budget allocations...")
    months = [TWO_MONTHS_AGO, LAST_MONTH, THIS_MONTH]
    allocations = []
    non_income = [c for c in categories if c.goal_amount > 0]

    for month in months:
        for cat in non_income:
            # Vary the allocation slightly each month
            variation = random.uniform(0.9, 1.1)
            amount = int(cat.goal_amount * variation)
            a = BudgetAllocation(
                family_id=family.id, category_id=cat.id,
                month=month, budgeted_amount=amount,
            )
            # Close past months
            if month < THIS_MONTH:
                a.closed_at = datetime(month.year, month.month, 28, tzinfo=timezone.utc)
            allocations.append(a)

    session.add_all(allocations)
    await session.commit()
    print(f"  {len(allocations)} allocations across {len(months)} months")
    return allocations


async def create_budget_transactions(session: AsyncSession, family, accounts, payees, categories):
    """Create realistic budget transactions"""
    print("\nCreating budget transactions...")

    checking = accounts[0]
    savings = accounts[1]
    credit = accounts[2]

    # Build lookup helpers
    payee_map = {p.name: p for p in payees}
    cat_map = {c.name: c for c in categories}

    txns = []

    # --- Income transactions (2 months of salary) ---
    for month_start in [TWO_MONTHS_AGO, LAST_MONTH, THIS_MONTH]:
        if month_start <= TODAY:
            txns.append(BudgetTransaction(
                family_id=family.id, account_id=checking.id,
                date=month_start.replace(day=15),
                amount=4500000, payee_id=None, category_id=cat_map["Salary"].id,
                notes="Salary deposit", cleared=True,
            ))
            # Freelance income (not every month)
            if random.random() > 0.4:
                txns.append(BudgetTransaction(
                    family_id=family.id, account_id=checking.id,
                    date=month_start.replace(day=random.randint(5, 25)),
                    amount=random.choice([800000, 1200000, 1500000]),
                    category_id=cat_map["Freelance"].id,
                    notes="Freelance project payment", cleared=True,
                ))

    # --- Recurring expenses pattern ---
    expense_patterns = [
        ("Walmart", "Groceries", [-85000, -120000, -95000, -110000], "checking"),
        ("Costco", "Groceries", [-250000, -180000], "credit"),
        ("CFE (Electric)", "Utilities", [-95000], "checking"),
        ("Telmex (Internet)", "Utilities", [-89900], "checking"),
        ("Netflix", "Subscriptions", [-22900], "credit"),
        ("Spotify", "Subscriptions", [-11500], "credit"),
        ("Gasolinera", "Gas", [-80000, -75000, -90000], "credit"),
        ("Farmacia Guadalajara", "Pharmacy", [-35000, -28000], "checking"),
        ("School Tuition", "School Tuition", [-500000], "checking"),
        ("Pediatrician", "Doctor Visits", [-150000], "checking"),
        ("Restaurant El Fogón", "Dining Out", [-45000, -62000], "credit"),
        ("Amazon", "Hobbies", [-35000, -89000], "credit"),
        ("Uber / DiDi", "Ride Share", [-18000, -22000, -15000], "credit"),
    ]

    acct_lookup = {"checking": checking, "credit": credit}

    for month_start in [TWO_MONTHS_AGO, LAST_MONTH]:
        for payee_name, cat_name, amounts, acct_key in expense_patterns:
            for amount in amounts:
                d = month_start.replace(day=min(random.randint(1, 28), 28))
                if d <= TODAY:
                    txns.append(BudgetTransaction(
                        family_id=family.id, account_id=acct_lookup[acct_key].id,
                        date=d, amount=amount,
                        payee_id=payee_map.get(payee_name, payees[0]).id,
                        category_id=cat_map.get(cat_name, categories[0]).id,
                        cleared=True, reconciled=(month_start == TWO_MONTHS_AGO),
                    ))

    # Current month — partial (only up to today)
    for payee_name, cat_name, amounts, acct_key in expense_patterns[:8]:
        for amount in amounts[:1]:  # fewer this month
            day = random.randint(1, min(TODAY.day, 28))
            d = THIS_MONTH.replace(day=day)
            txns.append(BudgetTransaction(
                family_id=family.id, account_id=acct_lookup[acct_key].id,
                date=d, amount=amount,
                payee_id=payee_map.get(payee_name, payees[0]).id,
                category_id=cat_map.get(cat_name, categories[0]).id,
                cleared=random.random() > 0.3,
            ))

    # --- Transfer: checking → savings ---
    for month_start in [TWO_MONTHS_AGO, LAST_MONTH]:
        txns.append(BudgetTransaction(
            family_id=family.id, account_id=checking.id,
            date=month_start.replace(day=16), amount=-500000,
            transfer_account_id=savings.id,
            notes="Monthly savings transfer", cleared=True,
        ))
        txns.append(BudgetTransaction(
            family_id=family.id, account_id=savings.id,
            date=month_start.replace(day=16), amount=500000,
            transfer_account_id=checking.id,
            notes="Monthly savings transfer", cleared=True,
        ))

    # --- Credit card payment ---
    txns.append(BudgetTransaction(
        family_id=family.id, account_id=checking.id,
        date=LAST_MONTH.replace(day=25), amount=-350000,
        transfer_account_id=credit.id,
        notes="Credit card payment", cleared=True,
    ))
    txns.append(BudgetTransaction(
        family_id=family.id, account_id=credit.id,
        date=LAST_MONTH.replace(day=25), amount=350000,
        transfer_account_id=checking.id,
        notes="Credit card payment", cleared=True,
    ))

    # --- Split transaction example ---
    parent_txn = BudgetTransaction(
        family_id=family.id, account_id=checking.id,
        date=LAST_MONTH.replace(day=10), amount=-150000,
        payee_id=payee_map["Walmart"].id,
        is_parent=True, notes="Walmart trip (split)", cleared=True,
    )
    txns.append(parent_txn)
    session.add_all(txns)
    await session.flush()

    # Split children
    splits = [
        BudgetTransaction(
            family_id=family.id, account_id=checking.id,
            date=LAST_MONTH.replace(day=10), amount=-100000,
            parent_id=parent_txn.id,
            category_id=cat_map["Groceries"].id,
            notes="Groceries portion", cleared=True,
        ),
        BudgetTransaction(
            family_id=family.id, account_id=checking.id,
            date=LAST_MONTH.replace(day=10), amount=-50000,
            parent_id=parent_txn.id,
            category_id=cat_map["School Supplies"].id,
            notes="School supplies portion", cleared=True,
        ),
    ]
    session.add_all(splits)
    await session.commit()

    total = len(txns) + len(splits)
    print(f"  {total} transactions (income, expenses, transfers, 1 split)")
    return txns


async def create_budget_goals(session: AsyncSession, family, categories):
    """Create budget goals"""
    print("\nCreating budget goals...")
    cat_map = {c.name: c for c in categories}

    goals_data = [
        ("Grocery spending limit", cat_map["Groceries"], "spending_limit", 900000, "monthly"),
        ("Dining out limit", cat_map["Dining Out"], "spending_limit", 350000, "monthly"),
        ("Emergency fund target", cat_map["Emergency Fund"], "savings_target", 6000000, "annual"),
        ("Vacation savings", cat_map["Vacation Fund"], "savings_target", 3600000, "annual"),
        ("College savings", cat_map["Kids College"], "savings_target", 2400000, "annual"),
    ]
    goals = []
    for name, cat, gtype, amount, period in goals_data:
        g = BudgetGoal(
            family_id=family.id, category_id=cat.id,
            goal_type=gtype, target_amount=amount, period=period,
            start_date=TWO_MONTHS_AGO, is_active=True, name=name,
        )
        goals.append(g)
    session.add_all(goals)
    await session.commit()
    print(f"  {len(goals)} goals ({sum(1 for g in goals if g.goal_type == 'spending_limit')} spending limits, {sum(1 for g in goals if g.goal_type == 'savings_target')} savings targets)")
    return goals


async def create_categorization_rules(session: AsyncSession, family, categories):
    """Create auto-categorization rules"""
    print("\nCreating categorization rules...")
    cat_map = {c.name: c for c in categories}

    rules_data = [
        (cat_map["Groceries"], "contains", "payee", "walmart", 10),
        (cat_map["Groceries"], "contains", "payee", "costco", 10),
        (cat_map["Utilities"], "contains", "payee", "cfe", 20),
        (cat_map["Utilities"], "exact", "payee", "Telmex (Internet)", 20),
        (cat_map["Subscriptions"], "contains", "payee", "netflix", 30),
        (cat_map["Subscriptions"], "contains", "payee", "spotify", 30),
        (cat_map["Gas"], "startswith", "payee", "gasolinera", 15),
        (cat_map["Pharmacy"], "contains", "payee", "farmacia", 15),
        (cat_map["School Tuition"], "contains", "payee", "school tuition", 25),
        (cat_map["Ride Share"], "contains", "payee", "uber", 5),
    ]
    rules = []
    for cat, rtype, field, pattern, priority in rules_data:
        r = BudgetCategorizationRule(
            family_id=family.id, category_id=cat.id,
            rule_type=rtype, match_field=field, pattern=pattern,
            enabled=True, priority=priority,
        )
        rules.append(r)
    session.add_all(rules)
    await session.commit()
    print(f"  {len(rules)} auto-categorization rules")
    return rules


async def create_recurring_transactions(session: AsyncSession, family, accounts, payees, categories):
    """Create recurring transaction templates"""
    print("\nCreating recurring transactions...")
    checking = accounts[0]
    credit = accounts[2]
    cat_map = {c.name: c for c in categories}
    payee_map = {p.name: p for p in payees}

    recurring_data = [
        ("Monthly Rent", checking, cat_map["Rent / Mortgage"], None, -1200000, "monthly_dayofmonth", {"day": 1}, LAST_MONTH.replace(day=1)),
        ("Electric Bill", checking, cat_map["Utilities"], payee_map["CFE (Electric)"], -95000, "monthly_dayofmonth", {"day": 15}, LAST_MONTH.replace(day=15)),
        ("Internet", checking, cat_map["Utilities"], payee_map["Telmex (Internet)"], -89900, "monthly_dayofmonth", {"day": 10}, LAST_MONTH.replace(day=10)),
        ("Netflix", credit, cat_map["Subscriptions"], payee_map["Netflix"], -22900, "monthly_dayofmonth", {"day": 5}, LAST_MONTH.replace(day=5)),
        ("Spotify", credit, cat_map["Subscriptions"], payee_map["Spotify"], -11500, "monthly_dayofmonth", {"day": 12}, LAST_MONTH.replace(day=12)),
        ("School Tuition", checking, cat_map["School Tuition"], payee_map["School Tuition"], -500000, "monthly_dayofmonth", {"day": 1}, LAST_MONTH.replace(day=1)),
        ("Savings Transfer", checking, cat_map["Emergency Fund"], None, -500000, "monthly_dayofmonth", {"day": 16}, LAST_MONTH.replace(day=16)),
    ]
    recs = []
    for name, account, cat, payee, amount, rtype, pattern, start in recurring_data:
        r = BudgetRecurringTransaction(
            family_id=family.id, account_id=account.id,
            category_id=cat.id if cat else None,
            payee_id=payee.id if payee else None,
            name=name, amount=amount,
            recurrence_type=rtype, recurrence_interval=1,
            recurrence_pattern=pattern, start_date=start,
            is_active=True, last_generated_date=LAST_MONTH.replace(day=start.day),
            next_due_date=THIS_MONTH.replace(day=start.day),
        )
        recs.append(r)
    session.add_all(recs)
    await session.commit()
    print(f"  {len(recs)} recurring templates")
    return recs


async def main():
    print("=" * 60)
    print("Family Task Manager — Full Seed Data")
    print("=" * 60)

    engine = create_async_engine(DATABASE_URL, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        await clear_all(session)

        # Core
        family, mom, dad, emma, lucas = await create_family_and_users(session)
        all_members = [mom, dad, emma, lucas]

        # Tasks
        templates = await create_task_templates(session, family, mom)
        assignments = await create_assignments(session, family, templates, all_members)

        # Rewards & consequences
        rewards = await create_rewards(session, family, mom)
        await create_consequences(session, family, emma, lucas, assignments)

        # Points
        await create_point_transactions(session, family, mom, emma, lucas, assignments, rewards)

        # Invitation
        await create_invitation(session, family, mom)

        # Budget
        accounts = await create_budget_accounts(session, family)
        payees = await create_budget_payees(session, family)
        groups, categories = await create_budget_categories(session, family)
        await create_budget_allocations(session, family, categories)
        await create_budget_transactions(session, family, accounts, payees, categories)
        await create_budget_goals(session, family, categories)
        await create_categorization_rules(session, family, categories)
        await create_recurring_transactions(session, family, accounts, payees, categories)

    await engine.dispose()

    print("\n" + "=" * 60)
    print("Seed complete!")
    print("=" * 60)
    print("\nCredentials:")
    print("  mom@demo.com   / password123  (PARENT)")
    print("  dad@demo.com   / password123  (PARENT)")
    print("  emma@demo.com  / password123  (CHILD)")
    print("  lucas@demo.com / password123  (TEEN)")
    print(f"\nFrontend: http://localhost:3003")
    print(f"API Docs: http://localhost:8002/docs\n")


if __name__ == "__main__":
    asyncio.run(main())
