#!/usr/bin/env python3
"""
Demo-data seeder for an EXISTING family — populates every domain.

Unlike seed_data.py (which TRUNCATEs the whole DB and builds a fresh demo
family), this script is ADDITIVE and SCOPED to a single existing family,
resolved by the email of one of its parents (TARGET_PARENT_EMAIL, default
info@agent-ia.mx). It NEVER truncates global tables — it only clears rows
belonging to that one family, so it is safe to run against a shared/prod DB
where other families' data must be preserved.

It is also idempotent: re-running first clears this family's demo data (and
any demo members previously added) and rebuilds it.

What it creates for the target family:
  - 3 demo members: +1 PARENT, +1 TEEN, +1 CHILD (the existing parent is kept)
  - Task templates (regular = 0 pts, bonus > 0 pts) + a week of assignments
  - Gig board: offerings + claims across the full lifecycle (open / claimed /
    pending review / approved-with-payout)
  - Rewards (all categories) + a kid reward-savings goal
  - Consequences (active + resolved)
  - Point transactions (task completion, gig payout, redemption, bonus,
    penalty) — User.points reconciled to the final running balance
  - Budget done the RIGHT way: accounts each with a synthetic "Starting
    Balance" transaction (so computed balances are correct), payees, category
    groups + categories, 3 months of allocations, realistic transactions
    (income / expenses / transfers / a split), goals, categorization rules,
    recurring templates
  - Subscription: family placed on the Pro plan (all features unlocked)
  - Meals (recipes + meal-plan entries) + shopping (list with checked items)
  - Calendar events (incl. a weekly recurring one)
  - Family chat messages + reactions
  - A DM thread between a parent and a kid
  - A virtual pet per kid + a PUP score snapshot

Run inside the backend container (DATABASE_URL comes from the environment):
  python /app/seed_demo_family.py
"""

import asyncio
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import get_password_hash
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
from app.models.calendar_event import CalendarEvent
from app.models.consequence import Consequence, ConsequenceSeverity, RestrictionType
from app.models.dm import DMMessage, DMThread
from app.models.family import Family
from app.models.family_chat import FamilyChatMessage
from app.models.family_chat_reaction import FamilyChatReaction
from app.models.gig import GigCategory, GigClaim, GigClaimStatus, GigOffering
from app.models.kid_pet import KidPet
from app.models.meal import MealPlanEntry, Recipe
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.pup_snapshot import PupScoreSnapshot
from app.models.reward import Reward, RewardCategory
from app.models.reward_goal import UserRewardGoal
from app.models.shopping import ShoppingItem, ShoppingList
from app.models.subscription import FamilySubscription, SubscriptionPlan, UsageTracking
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://familyapp:familyapp123@localhost:5437/familyapp",
)
TARGET_PARENT_EMAIL = os.getenv("TARGET_PARENT_EMAIL", "info@agent-ia.mx")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "FamiliaDemo2026!")

# Demo members added alongside the existing parent (kept). Emails are the
# stable handle used to clear/rebuild on re-run.
DEMO_MEMBERS = [
    ("Mariana Martinez", "mariana.demo@agent-ia.mx", UserRole.PARENT),
    ("Diego Martinez", "diego.demo@agent-ia.mx", UserRole.TEEN),
    ("Sofia Martinez", "sofia.demo@agent-ia.mx", UserRole.CHILD),
]

TODAY = date.today()
NOW = datetime.now(timezone.utc)
THIS_MONTH = TODAY.replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)
TWO_MONTHS_AGO = (LAST_MONTH - timedelta(days=1)).replace(day=1)

# Order matters: children before parents, users last. Every statement is
# scoped to a single :f (family_id) — nothing global is touched.
CLEAR_STATEMENTS = [
    "DELETE FROM point_transactions WHERE user_id IN (SELECT id FROM users WHERE family_id = :f)",
    "DELETE FROM family_chat_reactions WHERE message_id IN (SELECT id FROM family_chat_messages WHERE family_id = :f)",
    "DELETE FROM kid_pets WHERE user_id IN (SELECT id FROM users WHERE family_id = :f)",
    "DELETE FROM gig_claims WHERE family_id = :f",
    "DELETE FROM gig_offerings WHERE family_id = :f",
    "DELETE FROM user_reward_goals WHERE family_id = :f",
    "DELETE FROM dm_messages WHERE thread_id IN (SELECT id FROM dm_threads WHERE family_id = :f)",
    "DELETE FROM dm_threads WHERE family_id = :f",
    "DELETE FROM family_chat_messages WHERE family_id = :f",
    "DELETE FROM shopping_items WHERE list_id IN (SELECT id FROM shopping_lists WHERE family_id = :f)",
    "DELETE FROM shopping_lists WHERE family_id = :f",
    "DELETE FROM meal_plan_entries WHERE family_id = :f",
    "DELETE FROM recipes WHERE family_id = :f",
    "DELETE FROM calendar_events WHERE family_id = :f",
    "DELETE FROM pup_score_snapshots WHERE family_id = :f",
    "DELETE FROM consequences WHERE family_id = :f",
    "DELETE FROM task_assignments WHERE family_id = :f",
    "DELETE FROM task_templates WHERE family_id = :f",
    "DELETE FROM rewards WHERE family_id = :f",
    "DELETE FROM family_invitations WHERE family_id = :f",
    "DELETE FROM budget_recurring_transactions WHERE family_id = :f",
    "DELETE FROM budget_goals WHERE family_id = :f",
    "DELETE FROM budget_categorization_rules WHERE family_id = :f",
    "DELETE FROM budget_transactions WHERE family_id = :f AND parent_id IS NOT NULL",
    "DELETE FROM budget_transactions WHERE family_id = :f",
    "DELETE FROM budget_allocations WHERE family_id = :f",
    "DELETE FROM budget_categories WHERE family_id = :f",
    "DELETE FROM budget_category_groups WHERE family_id = :f",
    "DELETE FROM budget_payees WHERE family_id = :f",
    "DELETE FROM budget_accounts WHERE family_id = :f",
    "DELETE FROM usage_tracking WHERE family_id = :f",
    "DELETE FROM family_subscriptions WHERE family_id = :f",
    # Demo members only — the existing target parent is preserved.
    "DELETE FROM users WHERE family_id = :f AND lower(email) <> lower(:target)",
]


# ─── running point balances (reconciled into User.points at the end) ────────
_balances: dict[UUID, int] = {}


def _earn(session, user: User, txn_factory):
    """Append a PointTransaction built from the current balance and advance it."""
    bal = _balances.get(user.id, 0)
    txn = txn_factory(bal)
    _balances[user.id] = txn.balance_after
    session.add(txn)
    return txn


async def resolve_family(session: AsyncSession):
    row = (
        await session.execute(
            text("SELECT id, family_id FROM users WHERE lower(email) = lower(:e)"),
            {"e": TARGET_PARENT_EMAIL},
        )
    ).first()
    if not row:
        raise SystemExit(
            f"No user found with email {TARGET_PARENT_EMAIL!r}. "
            "Set TARGET_PARENT_EMAIL to an existing parent's email."
        )
    parent = await session.get(User, row[0])
    family = await session.get(Family, row[1])
    print(f"Target family: {family.name}  ({family.id})")
    print(f"Existing parent kept: {parent.name} <{parent.email}>")
    return family, parent


async def clear_family(session: AsyncSession, family: Family):
    print("\nClearing this family's existing demo data (scoped, additive)...")
    total = 0
    for stmt in CLEAR_STATEMENTS:
        params = {"f": str(family.id)}
        if ":target" in stmt:
            params["target"] = TARGET_PARENT_EMAIL
        res = await session.execute(text(stmt), params)
        total += res.rowcount or 0
    await session.commit()
    print(f"  Removed {total} rows.")


async def create_members(session: AsyncSession, family: Family):
    print("\nCreating demo members...")
    pw = get_password_hash(DEMO_PASSWORD)
    created = []
    for name, email, role in DEMO_MEMBERS:
        u = User(
            email=email,
            password_hash=pw,
            name=name,
            role=role,
            family_id=family.id,
            email_verified=True,
            is_active=True,
            points=0,
        )
        session.add(u)
        created.append(u)
    await session.commit()
    for u in created:
        print(f"  {u.role.value:6} {u.name} <{u.email}>")
    return created


async def create_tasks(session: AsyncSession, family, parent, members):
    """Templates (chores + bonus tasks award POINTS) + a week of assignments.

    Two-currency economy: all task templates award privilege POINTS on completion
    (mandatory chores and bonus tasks alike); only the /gigs board pays cash.
    Returns (templates, assignments, completed_bonus_by_user).
    """
    print("\nCreating task templates + assignments...")
    templates_data = [
        # title, title_es, desc, desc_es, points, interval_days, is_bonus
        ("Make Your Bed", "Hacer la Cama", "Make your bed neatly", "Haz tu cama ordenadamente", 10, 1, False),
        ("Brush Teeth", "Cepillar Dientes", "Brush morning and night", "Cepíllate mañana y noche", 10, 1, False),
        ("Complete Homework", "Terminar la Tarea", "Finish homework before dinner", "Termina la tarea antes de cenar", 15, 1, False),
        ("Clean Your Room", "Limpiar Cuarto", "Pick up and organize", "Recoge y organiza", 20, 7, False),
        ("Help With Dishes", "Ayudar con Platos", "Wash or dry after dinner", "Lava o seca después de cenar", 40, 1, True),
        ("Vacuum Living Room", "Aspirar la Sala", "Vacuum living room and hallway", "Aspira sala y pasillo", 75, 7, True),
        ("Help With Laundry", "Ayudar con Ropa", "Fold and put away clothes", "Dobla y guarda la ropa", 60, 7, True),
    ]
    templates = []
    for title, title_es, desc, desc_es, pts, interval, bonus in templates_data:
        templates.append(
            TaskTemplate(
                family_id=family.id, created_by=parent.id, is_active=True,
                title=title, title_es=title_es, description=desc,
                description_es=desc_es, points=pts, interval_days=interval,
                is_bonus=bonus,
            )
        )
    session.add_all(templates)
    await session.commit()

    kids = [m for m in members if m.role in (UserRole.TEEN, UserRole.CHILD)]
    week_monday = TODAY - timedelta(days=TODAY.weekday())
    regular = [t for t in templates if not t.is_bonus]
    bonus = [t for t in templates if t.is_bonus]

    assignments = []
    completed_bonus: dict[UUID, list] = {k.id: [] for k in kids}

    # Regular chores: assign each kid one per day this week; complete past days.
    for day_offset in range(7):
        d = week_monday + timedelta(days=day_offset)
        for i, kid in enumerate(kids):
            tmpl = regular[(day_offset + i) % len(regular)]
            a = TaskAssignment(
                template_id=tmpl.id, assigned_to=kid.id, family_id=family.id,
                status=AssignmentStatus.PENDING, assigned_date=d, week_of=week_monday,
            )
            if d < TODAY:
                a.status = AssignmentStatus.COMPLETED
                a.completed_at = datetime.combine(d, datetime.min.time()).replace(
                    hour=15, minute=30, tzinfo=timezone.utc
                )
            assignments.append(a)

    # Bonus chores: offer to kids; complete a couple of past ones (these pay points).
    for tmpl in bonus:
        for day_offset in range(0, 7, max(1, tmpl.interval_days)):
            d = week_monday + timedelta(days=day_offset)
            for kid in kids:
                a = TaskAssignment(
                    template_id=tmpl.id, assigned_to=kid.id, family_id=family.id,
                    status=AssignmentStatus.PENDING, assigned_date=d, week_of=week_monday,
                )
                if d < TODAY and random.random() < 0.5:
                    a.status = AssignmentStatus.COMPLETED
                    a.completed_at = datetime.combine(d, datetime.min.time()).replace(
                        hour=16, tzinfo=timezone.utc
                    )
                    completed_bonus[kid.id].append((a, tmpl.points))
                assignments.append(a)

    session.add_all(assignments)
    await session.commit()
    done = sum(1 for a in assignments if a.status == AssignmentStatus.COMPLETED)
    print(f"  {len(templates)} templates, {len(assignments)} assignments ({done} completed)")
    return templates, assignments, completed_bonus


async def create_gigs(session: AsyncSession, family, parent, members):
    """Offerings + claims across the full lifecycle. Approved claims pay CASH ($MXN)."""
    print("\nCreating gig board...")
    teen = next(m for m in members if m.role == UserRole.TEEN)
    child = next(m for m in members if m.role == UserRole.CHILD)

    offerings_data = [
        ("Wash the car", "Soap, rinse, dry — inside and out", 120, 2, GigCategory.CHORES),
        ("Walk the dog (evening)", "30 min walk around the block", 40, 1, GigCategory.OUTDOOR),
        ("Organize the garage shelves", "Sort tools and boxes", 200, 3, GigCategory.CHORES),
        ("Help cook dinner", "Prep veggies and set the table", 60, 1, GigCategory.LEARNING),
        ("Water the garden", "All plants, front and back", 30, 1, GigCategory.OUTDOOR),
        ("Draw a family poster", "Poster for the kitchen wall", 80, 2, GigCategory.CREATIVE),
    ]
    offerings = []
    for title, desc, pts, diff, cat in offerings_data:
        offerings.append(
            GigOffering(
                family_id=family.id, created_by=parent.id, title=title,
                description=desc, points=pts, difficulty=diff, category=cat,
                is_active=True,
            )
        )
    session.add_all(offerings)
    await session.commit()

    # Lifecycle: 2 stay open, 1 claimed, 1 pending review, 2 approved (payout).
    claims = []
    # claimed (teen) — "Help cook dinner"
    claims.append(GigClaim(
        gig_id=offerings[3].id, family_id=family.id, claimed_by=teen.id,
        status=GigClaimStatus.CLAIMED, created_at=NOW - timedelta(hours=3),
    ))
    # pending review (child) — "Water the garden"
    claims.append(GigClaim(
        gig_id=offerings[4].id, family_id=family.id, claimed_by=child.id,
        status=GigClaimStatus.COMPLETED, proof_text="¡Listo! Regué todas las plantas.",
        completed_at=NOW - timedelta(hours=1), created_at=NOW - timedelta(hours=5),
    ))
    session.add_all(claims)

    # approved (teen) — "Wash the car"; approved (child) — "Draw a family poster"
    approved_specs = [(offerings[0], teen), (offerings[5], child)]
    approved_claims = []
    for off, kid in approved_specs:
        c = GigClaim(
            gig_id=off.id, family_id=family.id, claimed_by=kid.id,
            status=GigClaimStatus.APPROVED,
            proof_text="Terminado 👍", proof_image_url=None,
            completed_at=NOW - timedelta(days=1, hours=2),
            approved_by=parent.id, approved_at=NOW - timedelta(days=1),
            approval_notes="¡Excelente trabajo!", points_awarded=off.points,
        )
        approved_claims.append((c, kid, off.points))
        session.add(c)
    await session.commit()

    # Pay out approved claims in CASH (the gig board pays $MXN, 1 pt = 100 cents),
    # advance trust streak.
    from app.models.cash_transaction import CashTransaction, CashTransactionType
    for c, kid, pts in approved_claims:
        cents = pts * 100
        before = kid.cash_cents or 0
        kid.cash_cents = before + cents
        session.add(CashTransaction(
            user_id=kid.id, family_id=family.id,
            type=CashTransactionType.GIG_EARNED, amount_cents=cents,
            balance_before=before, balance_after=before + cents,
            gig_claim_id=c.id, description="Gig (demo seed)",
        ))
        kid.gig_trust_streak = (kid.gig_trust_streak or 0) + 1
    await session.commit()
    print(f"  {len(offerings)} offerings, {len(claims) + len(approved_claims)} claims "
          f"(2 approved w/ payout, 1 pending, 1 claimed)")
    return offerings


async def create_rewards(session: AsyncSession, family, members):
    print("\nCreating rewards + a reward goal...")
    rewards_data = [
        ("15 Min Screen Time", "Extra 15 min of games/TV/tablet", 50, RewardCategory.SCREEN_TIME, "screen"),
        ("30 Min Screen Time", "Extra 30 min of games/TV/tablet", 100, RewardCategory.SCREEN_TIME, "screen"),
        ("Ice Cream Trip", "Trip for your favorite ice cream", 150, RewardCategory.TREATS, "treat"),
        ("Movie Night Pick", "Choose the family movie", 120, RewardCategory.PRIVILEGES, "movie"),
        ("Later Bedtime", "Stay up 30 min past bedtime", 200, RewardCategory.PRIVILEGES, "bedtime"),
        ("Small Toy / Book", "Pick a toy or book ($10 or less)", 500, RewardCategory.TOYS, "toy"),
        ("Park Visit", "Trip to the park of your choice", 80, RewardCategory.ACTIVITIES, "park"),
        ("$50 MXN Allowance Bonus", "Extra $50 MXN to your allowance", 300, RewardCategory.MONEY, "money"),
    ]
    rewards = []
    for title, desc, cost, cat, icon in rewards_data:
        rewards.append(Reward(
            family_id=family.id, title=title, description=desc,
            points_cost=cost, category=cat, icon=icon, is_active=True,
        ))
    session.add_all(rewards)
    await session.commit()

    # Child sets a savings goal toward the toy reward.
    child = next(m for m in members if m.role == UserRole.CHILD)
    toy = next(r for r in rewards if r.category == RewardCategory.TOYS)
    session.add(UserRewardGoal(
        user_id=child.id, family_id=family.id, reward_id=toy.id, set_at=NOW - timedelta(days=2),
    ))
    await session.commit()
    print(f"  {len(rewards)} rewards across {len(set(r.category for r in rewards))} categories, 1 reward goal")
    return rewards


async def create_points(session: AsyncSession, family, parent, members, completed_bonus, rewards):
    """Task-completion payouts + a redemption + a parent bonus/penalty.

    Gig payouts were already recorded in create_gigs(). Here we add the
    remaining transactions and reconcile User.points to the running balance.
    """
    print("\nCreating point transactions + reconciling balances...")
    teen = next(m for m in members if m.role == UserRole.TEEN)
    child = next(m for m in members if m.role == UserRole.CHILD)

    # Bonus task completions pay the template's points.
    for kid in (teen, child):
        for assignment, pts in completed_bonus.get(kid.id, []):
            _earn(session, kid, lambda bal, _a=assignment, _p=pts: PointTransaction.create_assignment_completion(
                user_id=_a.assigned_to, assignment_id=_a.id, points=_p, balance_before=bal,
            ))

    # Teen redeems the cheapest affordable reward.
    affordable = sorted(rewards, key=lambda r: r.points_cost)
    if affordable and _balances.get(teen.id, 0) >= affordable[0].points_cost:
        r = affordable[0]
        _earn(session, teen, lambda bal, _r=r: PointTransaction.create_reward_redemption(
            user_id=teen.id, reward_id=_r.id, points_cost=_r.points_cost, balance_before=bal,
        ))

    # Parent bonus for the child; a small penalty for the teen only when it
    # won't drive the balance negative (keeps points == sum(transactions)).
    _earn(session, child, lambda bal: PointTransaction(
        type=TransactionType.BONUS, user_id=child.id, points=50,
        balance_before=bal, balance_after=bal + 50, created_by=parent.id,
        description="Bonus for helping a neighbor",
    ))
    if _balances.get(teen.id, 0) >= 20:
        _earn(session, teen, lambda bal: PointTransaction(
            type=TransactionType.PENALTY, user_id=teen.id, points=-20,
            balance_before=bal, balance_after=bal - 20, created_by=parent.id,
            description="Left room messy after a warning",
        ))

    # Reconcile authoritative balance column to the running balance, which is
    # kept non-negative above so it always equals sum(point_transactions).
    for kid in (teen, child):
        kid.points = _balances.get(kid.id, 0)
    await session.commit()

    # Self-check: User.points must match the sum of the kid's transactions.
    for kid in (teen, child):
        total = (await session.execute(
            text("SELECT COALESCE(SUM(points), 0) FROM point_transactions WHERE user_id = :u"),
            {"u": str(kid.id)},
        )).scalar()
        if total != kid.points:
            raise SystemExit(
                f"Points mismatch for {kid.name}: User.points={kid.points} "
                f"but sum(point_transactions)={total}"
            )
    print(f"  {teen.name}: {teen.points} pts · {child.name}: {child.points} pts (reconciled)")


async def create_consequences(session: AsyncSession, family, members, assignments):
    print("\nCreating consequences...")
    teen = next(m for m in members if m.role == UserRole.TEEN)
    child = next(m for m in members if m.role == UserRole.CHILD)
    child_assigns = [a for a in assignments if a.assigned_to == child.id]

    rows = [
        Consequence(
            title="No Screen Time", description="Missed homework two days running",
            severity=ConsequenceSeverity.MEDIUM, restriction_type=RestrictionType.SCREEN_TIME,
            duration_days=3, active=True, resolved=False, applied_to_user=child.id,
            family_id=family.id,
            triggered_by_assignment_id=child_assigns[0].id if child_assigns else None,
            start_date=NOW - timedelta(days=1), end_date=NOW + timedelta(days=2),
            created_at=NOW - timedelta(days=1), updated_at=NOW - timedelta(days=1),
        ),
        Consequence(
            title="Extra Chores", description="Forgot to take out the trash all week",
            severity=ConsequenceSeverity.LOW, restriction_type=RestrictionType.EXTRA_TASKS,
            duration_days=2, active=False, resolved=True, applied_to_user=teen.id,
            family_id=family.id, start_date=NOW - timedelta(days=5),
            end_date=NOW - timedelta(days=3), resolved_at=NOW - timedelta(days=3),
            created_at=NOW - timedelta(days=5), updated_at=NOW - timedelta(days=3),
        ),
    ]
    session.add_all(rows)
    await session.commit()
    print(f"  {len(rows)} consequences (1 active, 1 resolved)")


# ─── BUDGET (the right way) ─────────────────────────────────────────────────

async def create_budget(session: AsyncSession, family, parent):
    print("\nCreating budget...")

    # Accounts — each non-zero starting balance gets a synthetic "Starting
    # Balance" transaction so the computed balance is correct (mirrors
    # AccountService.create).
    accounts_data = [
        ("Checking - BBVA", "checking", False, False, 2500000, 0),     # $25,000.00
        ("Savings - BBVA", "savings", False, False, 8000000, 1),        # $80,000.00
        ("Credit Card - Amex", "credit", False, False, -350000, 2),     # -$3,500.00
        ("Emergency Fund", "savings", True, False, 15000000, 3),        # $150,000 off-budget
    ]
    accounts = []
    for name, atype, offbudget, closed, bal, sort in accounts_data:
        a = BudgetAccount(
            family_id=family.id, name=name, type=atype, offbudget=offbudget,
            closed=closed, starting_balance=bal, sort_order=sort, currency="MXN",
        )
        accounts.append(a)
    session.add_all(accounts)
    await session.flush()
    for a in accounts:
        if a.starting_balance:
            session.add(BudgetTransaction(
                family_id=family.id, account_id=a.id,
                date=TWO_MONTHS_AGO, amount=a.starting_balance,
                notes="Starting Balance", cleared=True, reconciled=False,
                is_parent=False, created_by_id=parent.id,
            ))
    await session.commit()

    # Payees
    payee_names = [
        "Walmart", "Costco", "CFE (Electric)", "Telmex (Internet)", "Netflix",
        "Spotify", "Gasolinera", "Farmacia Guadalajara", "School Tuition",
        "Pediatrician", "Restaurant El Fogón", "Amazon", "Uber / DiDi",
    ]
    payees = [BudgetPayee(family_id=family.id, name=n) for n in payee_names]
    session.add_all(payees)
    await session.commit()

    # Category groups + categories (goal_amount in cents)
    groups_data = [
        ("Income", True, [("Salary", 0), ("Freelance", 0), ("Other Income", 0)]),
        ("Housing", False, [("Rent / Mortgage", 1200000), ("Utilities", 300000), ("Home Maintenance", 200000)]),
        ("Groceries & Food", False, [("Groceries", 800000), ("Dining Out", 300000), ("Coffee & Snacks", 100000)]),
        ("Transportation", False, [("Gas", 400000), ("Ride Share", 150000), ("Car Maintenance", 200000)]),
        ("Kids & Education", False, [("School Tuition", 500000), ("School Supplies", 100000), ("Kids Allowance", 100000)]),
        ("Health", False, [("Doctor Visits", 200000), ("Pharmacy", 150000), ("Insurance", 400000)]),
        ("Entertainment", False, [("Subscriptions", 50000), ("Movies & Outings", 150000), ("Hobbies", 100000)]),
        ("Savings Goals", False, [("Emergency Fund", 500000), ("Vacation Fund", 300000)]),
    ]
    categories = []
    for sort_order, (gname, is_income, cats) in enumerate(groups_data):
        g = BudgetCategoryGroup(family_id=family.id, name=gname, sort_order=sort_order, is_income=is_income)
        session.add(g)
        await session.flush()
        for cat_sort, (cname, goal) in enumerate(cats):
            categories.append(BudgetCategory(
                family_id=family.id, group_id=g.id, name=cname,
                sort_order=cat_sort, goal_amount=goal,
            ))
    session.add_all(categories)
    await session.commit()
    cat = {c.name: c for c in categories}
    pay = {p.name: p for p in payees}

    # Monthly allocations for the last 3 months
    allocations = []
    for month in (TWO_MONTHS_AGO, LAST_MONTH, THIS_MONTH):
        for c in categories:
            if c.goal_amount <= 0:
                continue
            amount = int(c.goal_amount * random.uniform(0.9, 1.1))
            a = BudgetAllocation(
                family_id=family.id, category_id=c.id, month=month, budgeted_amount=amount,
            )
            if month < THIS_MONTH:
                a.closed_at = datetime(month.year, month.month, 28, tzinfo=timezone.utc)
            allocations.append(a)
    session.add_all(allocations)
    await session.commit()

    checking, savings, credit = accounts[0], accounts[1], accounts[2]
    txns = []
    # Income
    for m in (TWO_MONTHS_AGO, LAST_MONTH, THIS_MONTH):
        if m <= TODAY:
            txns.append(BudgetTransaction(
                family_id=family.id, account_id=checking.id, date=m.replace(day=15),
                amount=4500000, category_id=cat["Salary"].id, notes="Salary deposit", cleared=True,
            ))
    # Recurring expenses
    expenses = [
        ("Walmart", "Groceries", [-85000, -120000], "checking"),
        ("Costco", "Groceries", [-250000], "credit"),
        ("CFE (Electric)", "Utilities", [-95000], "checking"),
        ("Telmex (Internet)", "Utilities", [-89900], "checking"),
        ("Netflix", "Subscriptions", [-22900], "credit"),
        ("Spotify", "Subscriptions", [-11500], "credit"),
        ("Gasolinera", "Gas", [-80000, -75000], "credit"),
        ("Farmacia Guadalajara", "Pharmacy", [-35000], "checking"),
        ("School Tuition", "School Tuition", [-500000], "checking"),
        ("Restaurant El Fogón", "Dining Out", [-45000, -62000], "credit"),
        ("Uber / DiDi", "Ride Share", [-18000, -22000], "credit"),
    ]
    acct = {"checking": checking, "credit": credit}
    for m in (TWO_MONTHS_AGO, LAST_MONTH):
        for pname, cname, amounts, akey in expenses:
            for amt in amounts:
                d = m.replace(day=min(random.randint(1, 28), 28))
                if d <= TODAY:
                    txns.append(BudgetTransaction(
                        family_id=family.id, account_id=acct[akey].id, date=d, amount=amt,
                        payee_id=pay[pname].id, category_id=cat[cname].id,
                        cleared=True, reconciled=(m == TWO_MONTHS_AGO),
                    ))
    # Current month partial
    for pname, cname, amounts, akey in expenses[:6]:
        d = THIS_MONTH.replace(day=min(max(TODAY.day - 2, 1), 28))
        txns.append(BudgetTransaction(
            family_id=family.id, account_id=acct[akey].id, date=d, amount=amounts[0],
            payee_id=pay[pname].id, category_id=cat[cname].id, cleared=random.random() > 0.3,
        ))
    # Transfer checking -> savings (mirrored pair)
    for m in (TWO_MONTHS_AGO, LAST_MONTH):
        txns.append(BudgetTransaction(
            family_id=family.id, account_id=checking.id, date=m.replace(day=16),
            amount=-500000, transfer_account_id=savings.id, notes="Monthly savings transfer", cleared=True,
        ))
        txns.append(BudgetTransaction(
            family_id=family.id, account_id=savings.id, date=m.replace(day=16),
            amount=500000, transfer_account_id=checking.id, notes="Monthly savings transfer", cleared=True,
        ))
    # Credit-card payment (mirrored pair)
    txns.append(BudgetTransaction(
        family_id=family.id, account_id=checking.id, date=LAST_MONTH.replace(day=25),
        amount=-350000, transfer_account_id=credit.id, notes="Credit card payment", cleared=True,
    ))
    txns.append(BudgetTransaction(
        family_id=family.id, account_id=credit.id, date=LAST_MONTH.replace(day=25),
        amount=350000, transfer_account_id=checking.id, notes="Credit card payment", cleared=True,
    ))
    # Split transaction (parent + children)
    parent_txn = BudgetTransaction(
        family_id=family.id, account_id=checking.id, date=LAST_MONTH.replace(day=10),
        amount=-150000, payee_id=pay["Walmart"].id, is_parent=True,
        notes="Walmart trip (split)", cleared=True,
    )
    txns.append(parent_txn)
    session.add_all(txns)
    await session.flush()
    session.add_all([
        BudgetTransaction(
            family_id=family.id, account_id=checking.id, date=LAST_MONTH.replace(day=10),
            amount=-100000, parent_id=parent_txn.id, category_id=cat["Groceries"].id,
            notes="Groceries portion", cleared=True,
        ),
        BudgetTransaction(
            family_id=family.id, account_id=checking.id, date=LAST_MONTH.replace(day=10),
            amount=-50000, parent_id=parent_txn.id, category_id=cat["School Supplies"].id,
            notes="School supplies portion", cleared=True,
        ),
    ])
    await session.commit()

    # Goals
    goals = [
        ("Grocery spending limit", cat["Groceries"], "spending_limit", 900000, "monthly"),
        ("Dining out limit", cat["Dining Out"], "spending_limit", 350000, "monthly"),
        ("Emergency fund target", cat["Emergency Fund"], "savings_target", 6000000, "annual"),
        ("Vacation savings", cat["Vacation Fund"], "savings_target", 3600000, "annual"),
    ]
    session.add_all([
        BudgetGoal(
            family_id=family.id, category_id=c.id, goal_type=gt, target_amount=amt,
            period=per, start_date=TWO_MONTHS_AGO, is_active=True, name=name,
        )
        for name, c, gt, amt, per in goals
    ])
    # Categorization rules
    rules = [
        (cat["Groceries"], "contains", "payee", "walmart", 10),
        (cat["Groceries"], "contains", "payee", "costco", 10),
        (cat["Utilities"], "contains", "payee", "cfe", 20),
        (cat["Subscriptions"], "contains", "payee", "netflix", 30),
        (cat["Gas"], "startswith", "payee", "gasolinera", 15),
        (cat["Ride Share"], "contains", "payee", "uber", 5),
    ]
    session.add_all([
        BudgetCategorizationRule(
            family_id=family.id, category_id=c.id, rule_type=rt, match_field=mf,
            pattern=pat, enabled=True, priority=pri,
        )
        for c, rt, mf, pat, pri in rules
    ])
    # Recurring templates
    recs = [
        ("Monthly Rent", checking, cat["Rent / Mortgage"], None, -1200000, {"day": 1}),
        ("Electric Bill", checking, cat["Utilities"], pay["CFE (Electric)"], -95000, {"day": 15}),
        ("Internet", checking, cat["Utilities"], pay["Telmex (Internet)"], -89900, {"day": 10}),
        ("Netflix", credit, cat["Subscriptions"], pay["Netflix"], -22900, {"day": 5}),
        ("School Tuition", checking, cat["School Tuition"], pay["School Tuition"], -500000, {"day": 1}),
    ]
    session.add_all([
        BudgetRecurringTransaction(
            family_id=family.id, account_id=acc.id,
            category_id=c.id if c else None, payee_id=p.id if p else None,
            name=name, amount=amt, recurrence_type="monthly_dayofmonth",
            recurrence_interval=1, recurrence_pattern=pat,
            start_date=LAST_MONTH.replace(day=pat["day"]), is_active=True,
            last_generated_date=LAST_MONTH.replace(day=pat["day"]),
            next_due_date=THIS_MONTH.replace(day=pat["day"]),
        )
        for name, acc, c, p, amt, pat in recs
    ])
    await session.commit()
    print(f"  {len(accounts)} accounts, {len(payees)} payees, {len(categories)} categories, "
          f"{len(allocations)} allocations, {len(txns) + 2} transactions, {len(goals)} goals, "
          f"{len(rules)} rules, {len(recs)} recurring")


async def ensure_pro_subscription(session: AsyncSession, family):
    """Make sure the 3 plans exist (global) and put this family on Pro."""
    print("\nEnsuring subscription plans + placing family on Pro...")
    existing = {
        r[0] for r in (await session.execute(text("SELECT name FROM subscription_plans"))).all()
    }
    plans_data = [
        {"name": "free", "display_name": "Free", "display_name_es": "Gratis",
         "price_monthly_cents": 0, "price_annual_cents": 0, "sort_order": 0,
         "limits": {"max_family_members": 4, "max_budget_accounts": 2,
                    "max_budget_transactions_per_month": 30, "max_recurring_transactions": 0,
                    "budget_reports": False, "budget_goals": False, "csv_import": False,
                    "max_receipt_scans_per_month": 0, "ai_features": False}},
        {"name": "plus", "display_name": "Plus", "display_name_es": "Plus",
         "price_monthly_cents": 500, "price_annual_cents": 5000, "sort_order": 1,
         "limits": {"max_family_members": 8, "max_budget_accounts": 5,
                    "max_budget_transactions_per_month": 200, "max_recurring_transactions": 5,
                    "budget_reports": True, "budget_goals": True, "csv_import": True,
                    "max_receipt_scans_per_month": 15, "ai_features": True}},
        {"name": "pro", "display_name": "Pro", "display_name_es": "Pro",
         "price_monthly_cents": 1500, "price_annual_cents": 15000, "sort_order": 2,
         "limits": {"max_family_members": -1, "max_budget_accounts": -1,
                    "max_budget_transactions_per_month": -1, "max_recurring_transactions": -1,
                    "budget_reports": True, "budget_goals": True, "csv_import": True,
                    "max_receipt_scans_per_month": -1, "ai_features": True}},
    ]
    for d in plans_data:
        if d["name"] not in existing:
            session.add(SubscriptionPlan(**d))
    await session.commit()

    pro = (await session.execute(
        text("SELECT id FROM subscription_plans WHERE name = 'pro'")
    )).first()
    session.add(FamilySubscription(
        family_id=family.id, plan_id=pro[0], billing_cycle="monthly", status="active",
        current_period_start=NOW, current_period_end=NOW + timedelta(days=30),
    ))
    session.add(UsageTracking(
        family_id=family.id, feature="budget_transaction",
        period_start=THIS_MONTH, count=24,
    ))
    await session.commit()
    print("  Family on Pro plan (all features unlocked)")


async def create_meals_and_shopping(session: AsyncSession, family, parent, members):
    print("\nCreating meals + shopping...")
    recipes_data = [
        ("Pasta Carbonara", "Creamy classic with pancetta", "200g spaghetti\n100g pancetta\n2 eggs\n50g parmesan\nblack pepper", 25),
        ("Tacos de Pollo", "Weeknight chicken tacos", "500g chicken breast\n8 corn tortillas\n1 onion\ncilantro\nlime\nsalsa verde", 30),
        ("Veggie Stir Fry", "Quick colorful stir fry", "2 cups broccoli\n1 bell pepper\n2 carrots\nsoy sauce\nginger\nrice", 20),
    ]
    recipes = [
        Recipe(family_id=family.id, created_by=parent.id, name=n, description=desc,
               ingredients_text=ing, prep_minutes=mins)
        for n, desc, ing, mins in recipes_data
    ]
    session.add_all(recipes)
    await session.commit()

    week_monday = TODAY - timedelta(days=TODAY.weekday())
    entries = [
        MealPlanEntry(family_id=family.id, plan_date=week_monday, meal_type="dinner",
                      title="Pasta Carbonara", recipe_id=recipes[0].id, notes="Double for leftovers"),
        MealPlanEntry(family_id=family.id, plan_date=week_monday + timedelta(days=1),
                      meal_type="dinner", title="Tacos de Pollo", recipe_id=recipes[1].id),
        MealPlanEntry(family_id=family.id, plan_date=week_monday + timedelta(days=2),
                      meal_type="dinner", title="Veggie Stir Fry", recipe_id=recipes[2].id),
        MealPlanEntry(family_id=family.id, plan_date=week_monday, meal_type="breakfast",
                      title="Oatmeal & fruit", recipe_id=None),
    ]
    session.add_all(entries)
    await session.commit()

    teen = next(m for m in members if m.role == UserRole.TEEN)
    slist = ShoppingList(name="Weekly Groceries", family_id=family.id, created_by=parent.id)
    session.add(slist)
    await session.flush()
    items_data = [
        ("Spaghetti", "200g", False), ("Pancetta", "100g", False), ("Eggs", "12", True),
        ("Chicken breast", "500g", False), ("Corn tortillas", "1 pack", True),
        ("Broccoli", "2 cups", False), ("Bell pepper", "1", False), ("Milk", "2L", True),
    ]
    items = []
    for name, qty, checked in items_data:
        it = ShoppingItem(list_id=slist.id, name=name, qty=qty, added_by=teen.id, is_checked=checked)
        if checked:
            it.checked_by = teen.id
            it.checked_at = NOW - timedelta(hours=2)
        items.append(it)
    session.add_all(items)
    await session.commit()
    print(f"  {len(recipes)} recipes, {len(entries)} meal entries, 1 list / {len(items)} items")


async def create_calendar(session: AsyncSession, family, parent, members):
    print("\nCreating calendar events...")
    kids = [m for m in members if m.role in (UserRole.TEEN, UserRole.CHILD)]
    base = datetime.combine(TODAY, datetime.min.time(), tzinfo=timezone.utc)
    events = [
        CalendarEvent(
            family_id=family.id, created_by=parent.id, title="Soccer Practice",
            description="Bring cleats and water", location="Parque Central",
            start_ts=base + timedelta(days=1, hours=17), end_ts=base + timedelta(days=1, hours=18, minutes=30),
            all_day=False, source="manual", color="green",
            recurrence_rule="FREQ=WEEKLY;BYDAY=WE", attendees=[str(kids[0].id)],
        ),
        CalendarEvent(
            family_id=family.id, created_by=parent.id, title="Dentist Appointment",
            location="Clínica Dental Roma", start_ts=base + timedelta(days=3, hours=10),
            end_ts=base + timedelta(days=3, hours=11), all_day=False, source="manual", color="blue",
            attendees=[str(kids[-1].id)],
        ),
        CalendarEvent(
            family_id=family.id, created_by=parent.id, title="Family Movie Night",
            start_ts=base + timedelta(days=5, hours=20), all_day=False, source="manual", color="purple",
        ),
        CalendarEvent(
            family_id=family.id, created_by=parent.id, title="School Holiday",
            start_ts=base + timedelta(days=7), all_day=True, source="school_import", color="orange",
        ),
    ]
    session.add_all(events)
    await session.commit()
    print(f"  {len(events)} events (1 weekly recurring)")


async def create_chat_and_dm(session: AsyncSession, family, parent, members):
    print("\nCreating family chat + DM...")
    teen = next(m for m in members if m.role == UserRole.TEEN)
    child = next(m for m in members if m.role == UserRole.CHILD)

    msgs = [
        FamilyChatMessage(family_id=family.id, sender_id=parent.id,
                          body="¡Buenos días equipo! No olviden sus tareas de hoy 💪",
                          created_at=NOW - timedelta(hours=6)),
        FamilyChatMessage(family_id=family.id, sender_id=teen.id,
                          body="Ya terminé de lavar el carro 🚗✨",
                          created_at=NOW - timedelta(hours=5)),
        FamilyChatMessage(family_id=family.id, sender_id=child.id,
                          body="¡Yo regué las plantas! 🌱",
                          created_at=NOW - timedelta(hours=1)),
    ]
    session.add_all(msgs)
    await session.flush()
    session.add_all([
        FamilyChatReaction(message_id=msgs[1].id, user_id=parent.id, emoji="👍"),
        FamilyChatReaction(message_id=msgs[1].id, user_id=child.id, emoji="🎉"),
        FamilyChatReaction(message_id=msgs[2].id, user_id=parent.id, emoji="❤️"),
    ])

    thread = DMThread(
        family_id=family.id,
        participant_ids=sorted([str(parent.id), str(teen.id)]),
        updated_at=NOW - timedelta(minutes=30),
    )
    session.add(thread)
    await session.flush()
    session.add_all([
        DMMessage(thread_id=thread.id, sender_id=parent.id,
                  body="¿Terminaste la tarea de matemáticas?",
                  created_at=NOW - timedelta(minutes=40)),
        DMMessage(thread_id=thread.id, sender_id=teen.id,
                  body="Sí, ya la subí. ¿Puedo reclamar la gig del garage?",
                  created_at=NOW - timedelta(minutes=30)),
    ])
    await session.commit()
    print(f"  {len(msgs)} chat messages (3 reactions), 1 DM thread / 2 messages")


async def create_pets(session: AsyncSession, family, members):
    print("\nCreating virtual pets + PUP snapshot...")
    teen = next(m for m in members if m.role == UserRole.TEEN)
    child = next(m for m in members if m.role == UserRole.CHILD)
    session.add_all([
        KidPet(user_id=teen.id, name="Rocky", species="dog", mood=82, hunger=35, xp=240),
        KidPet(user_id=child.id, name="Luna", species="cat", mood=90, hunger=20, xp=110),
    ])
    session.add(PupScoreSnapshot(
        family_id=family.id, score=78, label="Great", snapshot_date=TODAY,
    ))
    await session.commit()
    print("  2 pets (Rocky 🐶, Luna 🐱), 1 PUP snapshot")


async def main():
    print("=" * 64)
    print("Family Task Manager — Demo seeder for an EXISTING family")
    print("=" * 64)

    engine = create_async_engine(DATABASE_URL, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        family, parent = await resolve_family(session)
        await clear_family(session, family)
        members = await create_members(session, family)

        templates, assignments, completed_bonus = await create_tasks(session, family, parent, members)
        await create_gigs(session, family, parent, members)
        rewards = await create_rewards(session, family, members)
        await create_points(session, family, parent, members, completed_bonus, rewards)
        await create_consequences(session, family, members, assignments)
        await create_budget(session, family, parent)
        await ensure_pro_subscription(session, family)
        await create_meals_and_shopping(session, family, parent, members)
        await create_calendar(session, family, parent, members)
        await create_chat_and_dm(session, family, parent, members)
        await create_pets(session, family, members)

    await engine.dispose()

    print("\n" + "=" * 64)
    print("Demo seed complete!")
    print("=" * 64)
    print(f"\nFamily: {family.name}  ({family.id})")
    print(f"Existing parent (kept): {parent.email}")
    print("Demo members (password = DEMO_PASSWORD env):")
    for name, email, role in DEMO_MEMBERS:
        print(f"  {role.value:6} {name} <{email}>")
    print(f"\nPassword for demo members: {DEMO_PASSWORD}")
    print("Frontend: https://gcp-family.agent-ia.mx\n")


if __name__ == "__main__":
    asyncio.run(main())
