"""Jarvis must be able to answer "how much did we spend on food this month?".

Prod 2026-09-26: Jarvis replied "No tengo información sobre cuánto gastaron
en comida este mes" — the only budget tools were generic CRUD lists, so the
model would have had to list categories, list every transaction and sum them
itself; it gave up without calling anything. ``budget_spending_report`` hands
it the aggregate directly.
"""
import json
from datetime import date

import pytest

from app.mcp.context import McpContext, use_context
from app.mcp.inproc import connected_mcp_session
from app.mcp.server import build_server
from app.models.budget import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetTransaction,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _call(s, tool, args=None):
    res = await s.call_tool(tool, args or {})
    return json.loads(res.content[0].text)


async def _seed(db, family_id):
    acct = BudgetAccount(family_id=family_id, name="Checking", type="checking", offbudget=False)
    food = BudgetCategoryGroup(family_id=family_id, name="Comida Fuera")
    home = BudgetCategoryGroup(family_id=family_id, name="Mandado")
    db.add_all([acct, food, home])
    await db.flush()
    rest = BudgetCategory(family_id=family_id, group_id=food.id, name="Restaurantes")
    desp = BudgetCategory(family_id=family_id, group_id=home.id, name="Despensa")
    db.add_all([rest, desp])
    await db.flush()

    def tx(cat, d, amount):
        return BudgetTransaction(
            family_id=family_id, account_id=acct.id, category_id=cat.id, date=d, amount=amount
        )

    db.add_all([
        tx(rest, date(2026, 9, 3), -40000),
        tx(rest, date(2026, 9, 20), -21200),
        tx(desp, date(2026, 9, 10), -150050),
        tx(desp, date(2026, 8, 30), -99999),  # previous month: excluded
    ])
    await db.commit()


@pytest.mark.anyio
async def test_spending_report_aggregates_by_category_for_range(db_session, family, parent_user):
    await _seed(db_session, family.id)
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with connected_mcp_session(build_server()) as s:
            await s.initialize()
            tools = {t.name: t for t in (await s.list_tools()).tools}
            assert "budget_spending_report" in tools
            assert "spen" in tools["budget_spending_report"].description.lower()

            r = await _call(s, "budget_spending_report",
                            {"start_date": "2026-09-01", "end_date": "2026-09-30"})

    assert r["ok"] is True, r
    data = r["data"]
    by_name = {row["category"]: row for row in data["categories"]}
    assert by_name["Restaurantes"]["spent"] == 612.00
    assert by_name["Restaurantes"]["group"] == "Comida Fuera"
    assert by_name["Restaurantes"]["transactions"] == 2
    assert by_name["Despensa"]["spent"] == 1500.50
    assert data["total_spent"] == 2112.50
    # Largest spend first, so the model reads the headline without sorting.
    assert [row["category"] for row in data["categories"]] == ["Despensa", "Restaurantes"]


@pytest.mark.anyio
async def test_spending_report_group_by_group(db_session, family, parent_user):
    await _seed(db_session, family.id)
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with connected_mcp_session(build_server()) as s:
            await s.initialize()
            r = await _call(s, "budget_spending_report", {
                "start_date": "2026-09-01", "end_date": "2026-09-30", "group_by": "group",
            })
    assert r["ok"] is True, r
    by_name = {row["group"]: row["spent"] for row in r["data"]["groups"]}
    assert by_name == {"Mandado": 1500.50, "Comida Fuera": 612.00}


@pytest.mark.anyio
async def test_spending_report_is_family_scoped(db_session, family, other_family, parent_user):
    await _seed(db_session, other_family.id)
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with connected_mcp_session(build_server()) as s:
            await s.initialize()
            r = await _call(s, "budget_spending_report",
                            {"start_date": "2026-09-01", "end_date": "2026-09-30"})
    assert r["ok"] is True, r
    assert r["data"]["categories"] == []
    assert r["data"]["total_spent"] == 0


def test_jarvis_system_prompt_covers_budget_and_today():
    """The base persona must advertise budget questions, and the prompt must
    carry today's date — without it the 09-20 scheduled meal plan was written
    for "December 4th to December 10th"."""
    from app.services.jarvis_service import SYSTEM_BASE, _build_system

    assert "budget" in SYSTEM_BASE.lower()
    prompt = _build_system("CTX", "es", today=date(2026, 9, 26))
    assert "2026-09-26" in prompt
