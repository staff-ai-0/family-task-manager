"""GET /api/bank/payout-summary — parent aggregate of money owed to kids.

Covers: cash totals, chore-paycheck contribution per parent-released mode,
released-week zeroing, multi-tenant isolation, and the parent-only gate.
"""
from datetime import timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import APPROVAL_APPROVED, User, UserRole
from app.services.bank_service import BankService


@pytest_asyncio.fixture
async def parent_headers(client: AsyncClient, test_parent_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": test_parent_user.email, "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def teen_headers(client: AsyncClient, test_teen_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": test_teen_user.email, "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _current_week_monday(db, family_id):
    today = await BankService._family_local_today(db, family_id)
    return BankService._week_monday(today)


async def _bank_config(db, kid, **kw):
    acct = await BankService.ensure_account(db, kid)
    for k, v in kw.items():
        setattr(acct, k, v)
    await db.commit()
    return acct


async def _chore(
    db, fam_id, creator_id, kid_id, points, week, *,
    title="C", is_bonus=False, assigned_date=None,
    status=AssignmentStatus.COMPLETED, approval=ApprovalStatus.APPROVED,
    grade=None, pct=None, notes=None,
):
    t = TaskTemplate(
        title=title, points=points, effort_level=1, interval_days=1, is_bonus=is_bonus,
        assignment_type=AssignmentType.AUTO, family_id=fam_id, created_by=creator_id,
    )
    db.add(t)
    await db.flush()
    a = TaskAssignment(
        template_id=t.id, assigned_to=kid_id, family_id=fam_id,
        status=status, approval_status=approval,
        completion_grade=grade, partial_credit_pct=pct, approval_notes=notes,
        assigned_date=assigned_date or week, week_of=week,
    )
    db.add(a)
    await db.commit()
    return a


async def _approved_chore(db, fam_id, creator_id, kid_id, points, week):
    return await _chore(db, fam_id, creator_id, kid_id, points, week)


def _kid_row(body, user_id):
    return next(k for k in body["kids"] if k["user_id"] == str(user_id))


@pytest.mark.asyncio
async def test_payout_summary_parent_only(client, test_teen_user, teen_headers):
    r = await client.get("/api/bank/payout-summary", headers=teen_headers)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_payout_summary_cash_totals_flat_mode(
    client, db_session, test_family, test_parent_user,
    test_child_user, test_teen_user, parent_headers,
):
    test_child_user.cash_cents = 12000
    test_teen_user.cash_cents = 5000
    await db_session.commit()

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    assert r.status_code == 200
    body = r.json()

    assert body["cash_total_cents"] == 17000
    assert body["paycheck_total_cents"] == 0
    assert body["grand_total_cents"] == 17000
    assert len(body["kids"]) == 2

    child = _kid_row(body, test_child_user.id)
    assert child["cash_pending_cents"] == 12000
    assert child["paycheck_cents"] == 0
    assert child["paycheck_released"] is False
    assert child["allowance_mode"] == "flat"
    assert child["name"] == test_child_user.name


@pytest.mark.asyncio
async def test_payout_summary_includes_proportional_paycheck(
    client, db_session, test_family, test_parent_user, test_teen_user, parent_headers,
):
    test_teen_user.cash_cents = 3000
    await _bank_config(
        db_session, test_teen_user,
        allowance_mode="chore_proportional", allowance_cents=20000,
    )
    week = await _current_week_monday(db_session, test_family.id)
    await _approved_chore(
        db_session, test_family.id, test_parent_user.id, test_teen_user.id, 10, week
    )

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    assert r.status_code == 200
    body = r.json()

    teen = _kid_row(body, test_teen_user.id)
    assert teen["paycheck_cents"] == 20000  # 100% done → full cap
    assert teen["paycheck_released"] is False
    assert teen["allowance_mode"] == "chore_proportional"
    # Week-progress fields feed the payouts dashboard rows.
    assert teen["done_points"] == 10
    assert teen["assigned_points"] == 10
    assert teen["pct"] == 100
    assert body["paycheck_total_cents"] == 20000
    assert body["cash_total_cents"] == 3000
    assert body["grand_total_cents"] == 23000


@pytest.mark.asyncio
async def test_payout_summary_outstanding_weeks_includes_backlog(
    client, db_session, test_family, test_parent_user, test_teen_user, parent_headers,
):
    """The new additive fields surface a backlog the old flat fields can't:
    a fully-elapsed unreleased past week plus the current week."""
    await _bank_config(
        db_session, test_teen_user,
        allowance_mode="chore_proportional", allowance_cents=20000,
    )
    current_week = await _current_week_monday(db_session, test_family.id)
    past_week = current_week - timedelta(days=7)
    await _approved_chore(
        db_session, test_family.id, test_parent_user.id, test_teen_user.id, 10, past_week
    )
    await _approved_chore(
        db_session, test_family.id, test_parent_user.id, test_teen_user.id, 5, current_week
    )

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    body = r.json()
    teen = _kid_row(body, test_teen_user.id)

    weeks_seen = {w["week_of"] for w in teen["outstanding_weeks"]}
    assert past_week.isoformat() in weeks_seen
    assert current_week.isoformat() in weeks_seen
    # Old current-week-only fields are completely unaffected by the backlog.
    assert teen["paycheck_cents"] == 20000  # 100% of current_week's 5 pts
    assert body["paycheck_total_cents"] == 20000
    # New totals include the past week's 20000 too.
    assert body["outstanding_paycheck_total_cents"] == 40000
    assert body["outstanding_grand_total_cents"] == 40000


@pytest.mark.asyncio
async def test_payout_summary_points_rate_paycheck(
    client, db_session, test_family, test_parent_user, test_teen_user, parent_headers,
):
    test_family.point_value_cents = 200
    await _bank_config(db_session, test_teen_user, allowance_mode="points_rate")
    week = await _current_week_monday(db_session, test_family.id)
    await _approved_chore(
        db_session, test_family.id, test_parent_user.id, test_teen_user.id, 10, week
    )

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    body = r.json()
    teen = _kid_row(body, test_teen_user.id)
    assert teen["paycheck_cents"] == 2000  # 10 pts × $2.00
    assert body["grand_total_cents"] == 2000


@pytest.mark.asyncio
async def test_payout_summary_released_week_is_zero(
    client, db_session, test_family, test_parent_user, test_teen_user, parent_headers,
):
    week = await _current_week_monday(db_session, test_family.id)
    await _bank_config(
        db_session, test_teen_user,
        allowance_mode="chore_proportional", allowance_cents=20000,
        last_chore_paycheck_week=week,
    )
    await _approved_chore(
        db_session, test_family.id, test_parent_user.id, test_teen_user.id, 10, week
    )

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    body = r.json()
    teen = _kid_row(body, test_teen_user.id)
    assert teen["paycheck_cents"] == 0
    assert teen["paycheck_released"] is True
    assert body["paycheck_total_cents"] == 0


@pytest.mark.asyncio
async def test_payout_summary_multitenant_isolation(
    client, db_session: AsyncSession, test_family, test_parent_user,
    test_child_user, parent_headers,
):
    other_fam = Family(name="Other Fam")
    db_session.add(other_fam)
    await db_session.flush()
    outsider = User(
        email=f"o{uuid4().hex[:8]}@t.com", name="Outsider", role=UserRole.CHILD,
        family_id=other_fam.id, email_verified=True, cash_cents=99999, points=0,
        approval_status=APPROVAL_APPROVED, is_active=True,
    )
    db_session.add(outsider)
    await db_session.commit()

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    body = r.json()
    ids = {k["user_id"] for k in body["kids"]}
    assert str(outsider.id) not in ids
    assert body["cash_total_cents"] == 0


# ── Per-task detail list (payouts dashboard tooltips) ────────────────────────


@pytest.mark.asyncio
async def test_payout_summary_task_details_status_buckets(
    client, db_session, test_family, test_parent_user, test_teen_user, parent_headers,
):
    await _bank_config(
        db_session, test_teen_user,
        allowance_mode="chore_proportional", allowance_cents=10000,
    )
    week = await _current_week_monday(db_session, test_family.id)
    fam, par, kid = test_family.id, test_parent_user.id, test_teen_user.id

    await _chore(db_session, fam, par, kid, 10, week, title="Full", grade="full")
    await _chore(
        db_session, fam, par, kid, 10, week, title="Partial",
        assigned_date=week + timedelta(days=1),
        grade="partial", pct=50, notes="Faltó la almohada",
    )
    await _chore(
        db_session, fam, par, kid, 5, week, title="Review",
        assigned_date=week + timedelta(days=2), approval=ApprovalStatus.PENDING,
    )
    await _chore(
        db_session, fam, par, kid, 5, week, title="Missed",
        assigned_date=week + timedelta(days=3),
        approval=ApprovalStatus.REJECTED, grade="missed",
    )
    await _chore(
        db_session, fam, par, kid, 5, week, title="Todo",
        assigned_date=week + timedelta(days=4),
        status=AssignmentStatus.PENDING, approval=ApprovalStatus.NONE,
    )

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    assert r.status_code == 200
    teen = _kid_row(r.json(), test_teen_user.id)

    tasks = teen["tasks"]
    assert [t["title"] for t in tasks] == ["Full", "Partial", "Review", "Missed", "Todo"]
    by_title = {t["title"]: t for t in tasks}

    full = by_title["Full"]
    assert full["status"] == "credited"
    assert full["points"] == 10
    assert full["earned_points"] == 10
    assert full["assigned_date"] == week.isoformat()

    partial = by_title["Partial"]
    assert partial["status"] == "credited"
    assert partial["earned_points"] == 5  # 10 pts × 50%
    assert partial["grade"] == "partial"
    assert partial["partial_credit_pct"] == 50
    assert partial["approval_notes"] == "Faltó la almohada"

    assert by_title["Review"]["status"] == "pending_review"
    assert by_title["Review"]["earned_points"] == 0
    assert by_title["Missed"]["status"] == "missed"
    assert by_title["Missed"]["earned_points"] == 0
    assert by_title["Todo"]["status"] == "not_done"
    assert by_title["Todo"]["earned_points"] == 0

    # List agrees with the aggregate the row already shows.
    assert teen["done_points"] == 15
    assert teen["assigned_points"] == 35


@pytest.mark.asyncio
async def test_payout_summary_task_details_exclusions(
    client, db_session, test_family, test_parent_user, test_teen_user, parent_headers,
):
    await _bank_config(
        db_session, test_teen_user,
        allowance_mode="chore_proportional", allowance_cents=10000,
    )
    week = await _current_week_monday(db_session, test_family.id)
    fam, par, kid = test_family.id, test_parent_user.id, test_teen_user.id

    await _chore(db_session, fam, par, kid, 10, week, title="Keep")
    await _chore(db_session, fam, par, kid, 10, week, title="Gig", is_bonus=True)
    await _chore(
        db_session, fam, par, kid, 10, week, title="Cancelled",
        status=AssignmentStatus.CANCELLED,
    )
    await _chore(
        db_session, fam, par, kid, 10, week - timedelta(days=7), title="LastWeek",
    )

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    teen = _kid_row(r.json(), test_teen_user.id)
    assert [t["title"] for t in teen["tasks"]] == ["Keep"]


@pytest.mark.asyncio
async def test_payout_summary_flat_mode_has_no_task_list(
    client, db_session, test_family, test_parent_user, test_child_user, parent_headers,
):
    week = await _current_week_monday(db_session, test_family.id)
    await _chore(
        db_session, test_family.id, test_parent_user.id, test_child_user.id, 10, week,
    )

    r = await client.get("/api/bank/payout-summary", headers=parent_headers)
    child = _kid_row(r.json(), test_child_user.id)
    assert child["allowance_mode"] == "flat"
    assert child["tasks"] == []


# ── Chore-paycheck history route ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_route_parent_only(client, test_teen_user, teen_headers):
    r = await client.get(
        f"/api/bank/chore-paycheck/{test_teen_user.id}/history", headers=teen_headers
    )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_history_route_returns_past_releases(
    client, db_session, test_family, test_parent_user, test_teen_user, parent_headers,
):
    await _bank_config(
        db_session, test_teen_user,
        allowance_mode="chore_proportional", allowance_cents=10000,
    )
    week = await _current_week_monday(db_session, test_family.id)
    await _chore(db_session, test_family.id, test_parent_user.id, test_teen_user.id, 10, week)
    await BankService.release_chore_paycheck(
        db_session, test_teen_user, test_family.id, week, entitled=True,
    )

    r = await client.get(
        f"/api/bank/chore-paycheck/{test_teen_user.id}/history", headers=parent_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["has_more"] is False
    assert len(body["weeks"]) == 1
    assert body["weeks"][0]["week_of"] == week.isoformat()
    assert body["weeks"][0]["amount_cents"] == 10000
    assert body["weeks"][0]["tasks"][0]["title"] == "C"


@pytest.mark.asyncio
async def test_history_route_cross_tenant_404(
    client, db_session, test_family, parent_headers,
):
    other_fam = Family(name="Other Fam 2")
    db_session.add(other_fam)
    await db_session.flush()
    outsider = User(
        email=f"o{uuid4().hex[:8]}@t.com", name="Outsider", role=UserRole.TEEN,
        family_id=other_fam.id, email_verified=True, cash_cents=0, points=0,
        approval_status=APPROVAL_APPROVED, is_active=True,
    )
    db_session.add(outsider)
    await db_session.commit()

    r = await client.get(
        f"/api/bank/chore-paycheck/{outsider.id}/history", headers=parent_headers
    )
    assert r.status_code == 404
