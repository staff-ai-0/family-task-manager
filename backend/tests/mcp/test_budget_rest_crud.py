"""
Smoke tests for Phase 5 budget-rest MCP tools:
category_group, category, payee, transaction, allocation, goal,
rule, recurring, tag, saved_filter, custom_report, receipt_draft.

Mirrors the pattern in test_budget_account_crud.py — one CRUD
cycle per representative entity, run against the test DB.
"""
import json
import pytest
from datetime import date

from app.mcp.server import build_server
from app.mcp.context import McpContext, use_context
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _call(s, tool, args=None):
    res = await s.call_tool(tool, args or {})
    return json.loads(res.content[0].text)


# ---------------------------------------------------------------------------
# category_group
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_budget_category_group_crud(db_session, family, parent_user):
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            assert "budget_category_group_create" in names

            r = await _call(s, "budget_category_group_create", {"name": "Housing"})
            assert r["ok"] is True
            gid = r["data"]["id"]

            listed = await _call(s, "budget_category_group_list")
            assert any(g["id"] == gid for g in listed["data"])

            upd = await _call(s, "budget_category_group_update", {"id": gid, "name": "Housing 2"})
            assert upd["data"]["name"] == "Housing 2"

            got = await _call(s, "budget_category_group_get", {"id": gid})
            assert got["data"]["id"] == gid

            d = await _call(s, "budget_category_group_delete", {"id": gid})
            assert d["ok"] is True


# ---------------------------------------------------------------------------
# payee (simpler than category, no FK deps)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_budget_payee_crud(db_session, family, parent_user):
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            assert "budget_payee_create" in [t.name for t in (await s.list_tools()).tools]

            r = await _call(s, "budget_payee_create", {"name": "Oxxo"})
            assert r["ok"] is True
            pid = r["data"]["id"]

            listed = await _call(s, "budget_payee_list")
            assert any(p["id"] == pid for p in listed["data"])

            upd = await _call(s, "budget_payee_update", {"id": pid, "name": "OXXO Store"})
            assert upd["data"]["name"] == "OXXO Store"

            d = await _call(s, "budget_payee_delete", {"id": pid})
            assert d["ok"] is True


# ---------------------------------------------------------------------------
# tag
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_budget_tag_crud(db_session, family, parent_user):
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            assert "budget_tag_create" in [t.name for t in (await s.list_tools()).tools]

            r = await _call(s, "budget_tag_create", {"name": "Grocery", "color": "#ff0000"})
            assert r["ok"] is True
            tid = r["data"]["id"]

            listed = await _call(s, "budget_tag_list")
            assert any(t["id"] == tid for t in listed["data"])

            upd = await _call(s, "budget_tag_update", {"id": tid, "name": "Food"})
            assert upd["data"]["name"] == "Food"

            d = await _call(s, "budget_tag_delete", {"id": tid})
            assert d["ok"] is True


# ---------------------------------------------------------------------------
# saved_filter
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_budget_saved_filter_crud(db_session, family, parent_user):
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            assert "budget_saved_filter_create" in [t.name for t in (await s.list_tools()).tools]

            r = await _call(s, "budget_saved_filter_create", {
                "name": "Big Expenses",
                "conditions": [{"field": "amount", "operator": "gt", "value": 10000}],
                "conditions_op": "and",
            })
            assert r["ok"] is True
            fid = r["data"]["id"]

            listed = await _call(s, "budget_saved_filter_list")
            assert any(f["id"] == fid for f in listed["data"])

            upd = await _call(s, "budget_saved_filter_update", {"id": fid, "name": "Large Expenses"})
            assert upd["data"]["name"] == "Large Expenses"

            d = await _call(s, "budget_saved_filter_delete", {"id": fid})
            assert d["ok"] is True


# ---------------------------------------------------------------------------
# custom_report
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_budget_custom_report_crud(db_session, family, parent_user):
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            assert "budget_custom_report_create" in [t.name for t in (await s.list_tools()).tools]

            r = await _call(s, "budget_custom_report_create", {
                "name": "Monthly Spending",
                "config": {"group_by": "category", "date_range": "last_30"},
            })
            assert r["ok"] is True
            rid = r["data"]["id"]

            listed = await _call(s, "budget_custom_report_list")
            assert any(rp["id"] == rid for rp in listed["data"])

            upd = await _call(s, "budget_custom_report_update", {"id": rid, "name": "Monthly Spending v2"})
            assert upd["data"]["name"] == "Monthly Spending v2"

            d = await _call(s, "budget_custom_report_delete", {"id": rid})
            assert d["ok"] is True


# ---------------------------------------------------------------------------
# receipt_draft (list + get + delete only; no create via MCP)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_budget_receipt_draft_list_delete(db_session, family, parent_user):
    from app.models.budget import BudgetAccount, BudgetReceiptDraft

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)

    # seed an account + draft directly
    acct = BudgetAccount(family_id=family.id, name="Cash", type="checking", currency="MXN")
    db_session.add(acct)
    await db_session.commit()
    await db_session.refresh(acct)

    draft = BudgetReceiptDraft(
        family_id=family.id,
        account_id=acct.id,
        scanned_data={"total": 100},
        confidence=0.2,
        status="pending",
    )
    db_session.add(draft)
    await db_session.commit()
    await db_session.refresh(draft)

    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            assert "budget_receipt_draft_list" in [t.name for t in (await s.list_tools()).tools]

            listed = await _call(s, "budget_receipt_draft_list")
            assert any(d["id"] == str(draft.id) for d in listed["data"])

            got = await _call(s, "budget_receipt_draft_get", {"id": str(draft.id)})
            assert got["data"]["id"] == str(draft.id)

            d = await _call(s, "budget_receipt_draft_delete", {"id": str(draft.id)})
            assert d["ok"] is True


# ---------------------------------------------------------------------------
# FIX 1: saved_filter + custom_report create must reject token-only sessions
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_saved_filter_create_token_session_returns_error(db_session, family):
    """SavedFilterAdapter.create with user_id=None must return ok:false,
    not attempt an FK-violating INSERT of family_id into users.id column."""
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=None, role="MCP_TOKEN", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            r = await _call(s, "budget_saved_filter_create", {
                "name": "Token Filter",
                "conditions": [{"field": "amount", "operator": "gt", "value": 5000}],
                "conditions_op": "and",
            })
    assert r["ok"] is False
    assert "user" in r["error"].lower() or "authenticated" in r["error"].lower()


@pytest.mark.anyio
async def test_saved_filter_create_with_user_sets_created_by(db_session, family, parent_user):
    """SavedFilterAdapter.create with a real user_id must succeed and use user_id as created_by."""
    from app.models.budget import BudgetSavedFilter
    from sqlalchemy import select
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            r = await _call(s, "budget_saved_filter_create", {
                "name": "User Filter",
                "conditions": [{"field": "amount", "operator": "gt", "value": 1000}],
                "conditions_op": "and",
            })
    assert r["ok"] is True
    # Verify the row in the DB uses the user's id, not the family id
    from uuid import UUID
    row = (await db_session.execute(
        select(BudgetSavedFilter).where(BudgetSavedFilter.id == UUID(r["data"]["id"]))
    )).scalar_one()
    assert row.created_by == parent_user.id


@pytest.mark.anyio
async def test_custom_report_create_token_session_returns_error(db_session, family):
    """CustomReportAdapter.create with user_id=None must return ok:false."""
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=None, role="MCP_TOKEN", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            r = await _call(s, "budget_custom_report_create", {
                "name": "Token Report",
                "config": {"group_by": "category"},
            })
    assert r["ok"] is False
    assert "user" in r["error"].lower() or "authenticated" in r["error"].lower()


@pytest.mark.anyio
async def test_custom_report_create_with_user_sets_created_by(db_session, family, parent_user):
    """CustomReportAdapter.create with a real user_id must succeed."""
    from app.models.budget import BudgetCustomReport
    from sqlalchemy import select
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            r = await _call(s, "budget_custom_report_create", {
                "name": "User Report",
                "config": {"group_by": "payee"},
            })
    assert r["ok"] is True
    from uuid import UUID
    row = (await db_session.execute(
        select(BudgetCustomReport).where(BudgetCustomReport.id == UUID(r["data"]["id"]))
    )).scalar_one()
    assert row.created_by == parent_user.id
