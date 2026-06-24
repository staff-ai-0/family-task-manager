"""
Smoke tests for tasks (assignment) + gigs (offering, claim) MCP tools
(Task 14, Phase 5).

Mirrors the structure of test_budget_account_crud.py and
test_points_rewards_crud.py.
"""

import json
import pytest
from app.mcp.server import build_server
from app.mcp.context import McpContext, use_context
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# tasks — assignment LGCUD
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_assignment_create_list_get_update_delete(db_session, family, parent_user):
    """
    Full CRUD cycle for a task assignment via MCP tools.

    The assignment is created via tasks_assignment_create which internally
    calls patch_assignment / or creates a TaskAssignment directly via the
    service.  We test list/get/update/delete around it.
    """
    from app.models.task_template import TaskTemplate
    from app.models.task_assignment import TaskAssignment, AssignmentStatus
    from datetime import date

    # Seed a template and assignment directly (assignment create via service
    # requires shuffle; we seed one here and use MCP for the other CRUD ops)
    tmpl = TaskTemplate(
        family_id=family.id,
        title="Test Chore",
        points=0,
        is_bonus=False,
        effort_level=1,
        interval_days=1,
        created_by=parent_user.id,
    )
    db_session.add(tmpl)
    await db_session.commit()
    await db_session.refresh(tmpl)

    today = date.today()
    from app.services.task_assignment_service import TaskAssignmentService
    week_mon = TaskAssignmentService._get_monday(today)
    asgn = TaskAssignment(
        family_id=family.id,
        template_id=tmpl.id,
        assigned_to=parent_user.id,
        assigned_date=today,
        week_of=week_mon,
        status=AssignmentStatus.PENDING,
    )
    db_session.add(asgn)
    await db_session.commit()
    await db_session.refresh(asgn)
    asgn_id = str(asgn.id)

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "tasks_assignment_list" in tool_names
            assert "tasks_assignment_get" in tool_names
            assert "tasks_assignment_update" in tool_names
            assert "tasks_assignment_delete" in tool_names

            # List — should include our seeded assignment
            listed = json.loads((await s.call_tool("tasks_assignment_list", {})).content[0].text)
            assert listed["ok"] is True
            ids = [r["id"] for r in listed["data"]]
            assert asgn_id in ids

            # Get
            got = json.loads((await s.call_tool(
                "tasks_assignment_get", {"id": asgn_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == asgn_id

            # Update — patch status to cancelled
            updated = json.loads((await s.call_tool(
                "tasks_assignment_update",
                {"id": asgn_id, "status": "cancelled"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["status"] == "cancelled"

            # Delete
            deleted = json.loads((await s.call_tool(
                "tasks_assignment_delete", {"id": asgn_id},
            )).content[0].text)
            assert deleted["ok"] is True


# ---------------------------------------------------------------------------
# gigs — offering LGCUD
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_gig_offering_create_list_get_update_delete(db_session, family, parent_user):
    """Full CRUD cycle for a gig offering via MCP tools."""
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "gigs_offering_list" in tool_names
            assert "gigs_offering_get" in tool_names
            assert "gigs_offering_create" in tool_names
            assert "gigs_offering_update" in tool_names
            assert "gigs_offering_delete" in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "gigs_offering_create",
                {
                    "title": "Clean the garage",
                    "points": 30,
                    "difficulty": 2,
                    "category": "chores",
                },
            )).content[0].text)
            assert created["ok"] is True, created
            offering_id = created["data"]["id"]
            assert created["data"]["title"] == "Clean the garage"

            # List
            listed = json.loads((await s.call_tool("gigs_offering_list", {})).content[0].text)
            assert listed["ok"] is True
            assert any(o["id"] == offering_id for o in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "gigs_offering_get", {"id": offering_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == offering_id

            # Update
            updated = json.loads((await s.call_tool(
                "gigs_offering_update",
                {"id": offering_id, "title": "Clean the garage v2"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["title"] == "Clean the garage v2"

            # Delete (deactivate)
            deleted = json.loads((await s.call_tool(
                "gigs_offering_delete", {"id": offering_id},
            )).content[0].text)
            assert deleted["ok"] is True


# ---------------------------------------------------------------------------
# gigs — claim LGUD (no create — claims come from GigClaimService.claim)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_gig_claim_list_get_update_delete(db_session, family, parent_user):
    """
    Seed a gig offering + claim; test list/get/update/delete of claim via MCP.
    """
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus

    offering = GigOffering(
        family_id=family.id,
        title="MCP Claim Gig",
        points=15,
        difficulty=1,
        created_by=parent_user.id,
    )
    db_session.add(offering)
    await db_session.commit()
    await db_session.refresh(offering)

    claim = GigClaim(
        gig_id=offering.id,
        family_id=family.id,
        claimed_by=parent_user.id,
        status=GigClaimStatus.CLAIMED,
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)
    claim_id = str(claim.id)

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "gigs_claim_list" in tool_names
            assert "gigs_claim_get" in tool_names
            assert "gigs_claim_update" in tool_names
            assert "gigs_claim_delete" in tool_names
            # No create for claims
            assert "gigs_claim_create" not in tool_names

            # List
            listed = json.loads((await s.call_tool("gigs_claim_list", {})).content[0].text)
            assert listed["ok"] is True
            ids = [r["id"] for r in listed["data"]]
            assert claim_id in ids

            # Get
            got = json.loads((await s.call_tool(
                "gigs_claim_get", {"id": claim_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == claim_id

            # Update — add proof text
            updated = json.loads((await s.call_tool(
                "gigs_claim_update",
                {"id": claim_id, "proof_text": "I did it!"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["proof_text"] == "I did it!"

            # Delete
            deleted = json.loads((await s.call_tool(
                "gigs_claim_delete", {"id": claim_id},
            )).content[0].text)
            assert deleted["ok"] is True
