"""L7: get_or_create_for_category_month was a check-then-insert. Two concurrent
calls for the same category+month both saw "no row", both inserted, and the
second commit hit uq_allocation_category_month -> raw IntegrityError 500.
It must converge on the existing row instead."""
import asyncio
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.budget import BudgetAllocation, BudgetCategory, BudgetCategoryGroup
from app.services.budget.allocation_service import AllocationService


@pytest.mark.asyncio
async def test_concurrent_get_or_create_converges(test_engine, db_session, test_family):
    grp = BudgetCategoryGroup(family_id=test_family.id, name="G", sort_order=0)
    db_session.add(grp)
    await db_session.commit()
    await db_session.refresh(grp)

    cat = BudgetCategory(family_id=test_family.id, group_id=grp.id, name="C")
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)

    month = date(2026, 6, 1)
    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _goc():
        async with maker() as s:
            return await AllocationService.get_or_create_for_category_month(
                s, test_family.id, cat.id, month
            )

    results = await asyncio.gather(_goc(), _goc(), return_exceptions=True)

    errs = [r for r in results if isinstance(r, Exception)]
    assert not errs, f"concurrent get_or_create raised: {errs}"

    rows = (
        await db_session.execute(
            select(BudgetAllocation).where(
                BudgetAllocation.category_id == cat.id,
                BudgetAllocation.month == month,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
