#!/usr/bin/env python3
"""
Budget Seed Data Script for Family Task Manager

Creates budget structure for the Martinez/Johnson demo family:
- Default category groups (Mandado, Servicios, etc.)
- Categories within groups
- Budget accounts (checking, savings)
- Sample allocations for current month
- Sample transactions
"""

import asyncio
import sys
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.family import Family
from app.models.user import User, UserRole
from app.models.budget import (
    BudgetCategoryGroup,
    BudgetCategory,
    BudgetAccount,
    BudgetPayee,
    BudgetTransaction,
    BudgetAllocation,
)

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://familyapp:familyapp123@db:5432/familyapp",
)


async def clear_budget_data(session: AsyncSession):
    """Clear existing budget data"""
    print("Clearing existing budget data...")
    
    tables = [
        "budget_transactions",
        "budget_allocations",
        "budget_payees",
        "budget_accounts",
        "budget_categories",
        "budget_category_groups",
    ]
    
    for table in tables:
        await session.execute(text(f"DELETE FROM {table}"))
    
    await session.commit()
    print("Budget data cleared.")


async def create_budget_structure(session: AsyncSession):
    """Create default budget structure for Martinez family"""
    
    # Get the Demo family
    result = await session.execute(
        select(Family).where(Family.name == "Demo Family")
    )
    family = result.scalar_one_or_none()
    
    if not family:
        print("ERROR: Demo Family not found. Run seed_data.py first!")
        return
    
    print(f"Creating budget for family: {family.name} (ID: {family.id})")
    
    # ========================================================================
    # CATEGORY GROUPS
    # ========================================================================
    print("\nCreating category groups...")
    
    groups = []
    
    # Income group
    income_group = BudgetCategoryGroup(
        family_id=family.id,
        name="Ingresos",
        sort_order=0,
        is_income=True,
        hidden=False,
    )
    groups.append(income_group)
    
    # Expense groups
    mandado_group = BudgetCategoryGroup(
        family_id=family.id,
        name="Mandado",
        sort_order=1,
        is_income=False,
        hidden=False,
    )
    groups.append(mandado_group)
    
    servicios_group = BudgetCategoryGroup(
        family_id=family.id,
        name="Servicios",
        sort_order=2,
        is_income=False,
        hidden=False,
    )
    groups.append(servicios_group)
    
    transporte_group = BudgetCategoryGroup(
        family_id=family.id,
        name="Transporte",
        sort_order=3,
        is_income=False,
        hidden=False,
    )
    groups.append(transporte_group)
    
    entretenimiento_group = BudgetCategoryGroup(
        family_id=family.id,
        name="Entretenimiento",
        sort_order=4,
        is_income=False,
        hidden=False,
    )
    groups.append(entretenimiento_group)
    
    otros_group = BudgetCategoryGroup(
        family_id=family.id,
        name="Otros Gastos",
        sort_order=5,
        is_income=False,
        hidden=False,
    )
    groups.append(otros_group)
    
    session.add_all(groups)
    await session.flush()
    
    print(f"Created {len(groups)} category groups")
    
    # ========================================================================
    # CATEGORIES
    # ========================================================================
    print("\nCreating categories...")
    
    categories = []
    
    # Income categories
    categories.extend([
        BudgetCategory(
            family_id=family.id,
            group_id=income_group.id,
            name="Salario",
            sort_order=0,
            rollover_enabled=False,
            goal_amount=0,
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=income_group.id,
            name="Ingresos Extra",
            sort_order=1,
            rollover_enabled=False,
            goal_amount=0,
        ),
    ])
    
    # Mandado categories
    categories.extend([
        BudgetCategory(
            family_id=family.id,
            group_id=mandado_group.id,
            name="Fruta y Verdura",
            sort_order=0,
            rollover_enabled=True,
            goal_amount=200000,  # $2,000 MXN
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=mandado_group.id,
            name="Carne y Pescado",
            sort_order=1,
            rollover_enabled=True,
            goal_amount=150000,  # $1,500 MXN
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=mandado_group.id,
            name="Despensa",
            sort_order=2,
            rollover_enabled=True,
            goal_amount=300000,  # $3,000 MXN
        ),
    ])
    
    # Servicios categories
    categories.extend([
        BudgetCategory(
            family_id=family.id,
            group_id=servicios_group.id,
            name="Luz",
            sort_order=0,
            rollover_enabled=False,
            goal_amount=100000,  # $1,000 MXN
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=servicios_group.id,
            name="Agua",
            sort_order=1,
            rollover_enabled=False,
            goal_amount=50000,  # $500 MXN
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=servicios_group.id,
            name="Internet",
            sort_order=2,
            rollover_enabled=False,
            goal_amount=60000,  # $600 MXN
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=servicios_group.id,
            name="Gas",
            sort_order=3,
            rollover_enabled=False,
            goal_amount=80000,  # $800 MXN
        ),
    ])
    
    # Transporte categories
    categories.extend([
        BudgetCategory(
            family_id=family.id,
            group_id=transporte_group.id,
            name="Gasolina",
            sort_order=0,
            rollover_enabled=True,
            goal_amount=200000,  # $2,000 MXN
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=transporte_group.id,
            name="Uber/Taxi",
            sort_order=1,
            rollover_enabled=True,
            goal_amount=50000,  # $500 MXN
        ),
    ])
    
    # Entretenimiento categories
    categories.extend([
        BudgetCategory(
            family_id=family.id,
            group_id=entretenimiento_group.id,
            name="Restaurantes",
            sort_order=0,
            rollover_enabled=True,
            goal_amount=150000,  # $1,500 MXN
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=entretenimiento_group.id,
            name="Streaming",
            sort_order=1,
            rollover_enabled=False,
            goal_amount=30000,  # $300 MXN
        ),
        BudgetCategory(
            family_id=family.id,
            group_id=entretenimiento_group.id,
            name="Salidas Familia",
            sort_order=2,
            rollover_enabled=True,
            goal_amount=100000,  # $1,000 MXN
        ),
    ])
    
    # Otros categories
    categories.extend([
        BudgetCategory(
            family_id=family.id,
            group_id=otros_group.id,
            name="Varios",
            sort_order=0,
            rollover_enabled=True,
            goal_amount=50000,  # $500 MXN
        ),
    ])
    
    session.add_all(categories)
    await session.flush()
    
    print(f"Created {len(categories)} categories")
    
    # ========================================================================
    # ACCOUNTS
    # ========================================================================
    print("\nCreating accounts...")
    
    accounts = []
    
    # Main checking account
    checking = BudgetAccount(
        family_id=family.id,
        name="BBVA Cuenta de Cheques",
        type="checking",
        offbudget=False,
        closed=False,
        sort_order=0,
        notes="Cuenta principal familia",
    )
    accounts.append(checking)
    
    # Savings account
    savings = BudgetAccount(
        family_id=family.id,
        name="BBVA Ahorro",
        type="savings",
        offbudget=False,
        closed=False,
        sort_order=1,
        notes="Ahorros familiar",
    )
    accounts.append(savings)
    
    # Credit card
    credit = BudgetAccount(
        family_id=family.id,
        name="Tarjeta Crédito BBVA",
        type="credit",
        offbudget=False,
        closed=False,
        sort_order=2,
        notes="Tarjeta de crédito familiar",
    )
    accounts.append(credit)
    
    session.add_all(accounts)
    await session.flush()
    
    print(f"Created {len(accounts)} accounts")
    
    # ========================================================================
    # PAYEES
    # ========================================================================
    print("\nCreating payees...")
    
    payees = []
    
    common_payees = [
        "Walmart",
        "Soriana",
        "Bodega Aurrera",
        "CFE (Luz)",
        "Telmex",
        "Pemex",
        "Uber",
        "Netflix",
        "Spotify",
        "Mercado Libre",
    ]
    
    for idx, payee_name in enumerate(common_payees):
        payee = BudgetPayee(
            family_id=family.id,
            name=payee_name,
            notes=None,
        )
        payees.append(payee)
    
    session.add_all(payees)
    await session.flush()
    
    print(f"Created {len(payees)} payees")
    
    # ========================================================================
    # ALLOCATIONS (Current Month)
    # ========================================================================
    print("\nCreating budget allocations for current month...")
    
    current_month = date.today().replace(day=1)
    allocations = []
    
    # Set budget for each expense category based on goal_amount
    for category in categories:
        if not category.group_id == income_group.id:  # Skip income categories
            allocation = BudgetAllocation(
                family_id=family.id,
                category_id=category.id,
                month=current_month,
                budgeted_amount=category.goal_amount,
                notes=None,
            )
            allocations.append(allocation)
    
    session.add_all(allocations)
    await session.flush()
    
    print(f"Created {len(allocations)} budget allocations for {current_month.strftime('%B %Y')}")
    
    # ========================================================================
    # SAMPLE TRANSACTIONS
    # ========================================================================
    print("\nCreating sample transactions...")
    
    transactions = []
    
    # Get some categories for transactions
    despensa_cat = next(c for c in categories if c.name == "Despensa")
    frutas_cat = next(c for c in categories if c.name == "Fruta y Verdura")
    gasolina_cat = next(c for c in categories if c.name == "Gasolina")
    restaurantes_cat = next(c for c in categories if c.name == "Restaurantes")
    luz_cat = next(c for c in categories if c.name == "Luz")
    salario_cat = next(c for c in categories if c.name == "Salario")
    
    # Get some payees
    walmart_payee = next(p for p in payees if p.name == "Walmart")
    soriana_payee = next(p for p in payees if p.name == "Soriana")
    pemex_payee = next(p for p in payees if p.name == "Pemex")
    cfe_payee = next(p for p in payees if p.name == "CFE (Luz)")
    
    # Income transaction (salary)
    transactions.append(BudgetTransaction(
        family_id=family.id,
        account_id=checking.id,
        date=current_month,
        amount=2500000,  # $25,000 MXN income (positive)
        payee_id=None,
        category_id=salario_cat.id,
        notes="Salario mensual",
        cleared=True,
        reconciled=False,
    ))
    
    # Expense transactions
    transactions.append(BudgetTransaction(
        family_id=family.id,
        account_id=checking.id,
        date=current_month + timedelta(days=3),
        amount=-85000,  # -$850 MXN
        payee_id=walmart_payee.id,
        category_id=despensa_cat.id,
        notes="Mandado semanal",
        cleared=True,
        reconciled=False,
    ))
    
    transactions.append(BudgetTransaction(
        family_id=family.id,
        account_id=checking.id,
        date=current_month + timedelta(days=5),
        amount=-42000,  # -$420 MXN
        payee_id=soriana_payee.id,
        category_id=frutas_cat.id,
        notes="Frutas y verduras",
        cleared=True,
        reconciled=False,
    ))
    
    transactions.append(BudgetTransaction(
        family_id=family.id,
        account_id=credit.id,
        date=current_month + timedelta(days=7),
        amount=-60000,  # -$600 MXN
        payee_id=pemex_payee.id,
        category_id=gasolina_cat.id,
        notes="Gasolina",
        cleared=True,
        reconciled=False,
    ))
    
    transactions.append(BudgetTransaction(
        family_id=family.id,
        account_id=credit.id,
        date=current_month + timedelta(days=10),
        amount=-35000,  # -$350 MXN
        payee_id=None,
        category_id=restaurantes_cat.id,
        notes="Comida familiar",
        cleared=True,
        reconciled=False,
    ))
    
    transactions.append(BudgetTransaction(
        family_id=family.id,
        account_id=checking.id,
        date=current_month + timedelta(days=15),
        amount=-95000,  # -$950 MXN
        payee_id=cfe_payee.id,
        category_id=luz_cat.id,
        notes="Recibo de luz",
        cleared=True,
        reconciled=False,
    ))
    
    session.add_all(transactions)
    await session.commit()
    
    print(f"Created {len(transactions)} sample transactions")
    
    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("\n" + "="*60)
    print("BUDGET SEED DATA CREATION COMPLETE!")
    print("="*60)
    print(f"Family: {family.name}")
    print(f"  Category Groups: {len(groups)}")
    print(f"  Categories: {len(categories)}")
    print(f"  Accounts: {len(accounts)}")
    print(f"  Payees: {len(payees)}")
    print(f"  Allocations: {len(allocations)} (for {current_month.strftime('%B %Y')})")
    print(f"  Transactions: {len(transactions)}")
    print("\nYou can now access the budget via the API!")
    print("="*60)


async def main():
    """Main execution"""
    print("Family Task Manager - Budget Seed Data Script")
    print("="*60)
    
    # Create async engine
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        # Clear existing budget data
        await clear_budget_data(session)
        
        # Create budget structure
        await create_budget_structure(session)
    
    await engine.dispose()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
