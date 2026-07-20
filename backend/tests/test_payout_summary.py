"""GET /api/bank/payout-summary — parent aggregate of money owed to kids.

Covers: cash totals, chore-paycheck contribution per parent-released mode,
released-week zeroing, multi-tenant isolation, and the parent-only gate.
"""
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


async def _approved_chore(db, fam_id, creator_id, kid_id, points, week):
    t = TaskTemplate(
        title="C", points=points, effort_level=1, interval_days=1, is_bonus=False,
        assignment_type=AssignmentType.AUTO, family_id=fam_id, created_by=creator_id,
    )
    db.add(t)
    await db.flush()
    a = TaskAssignment(
        template_id=t.id, assigned_to=kid_id, family_id=fam_id,
        status=AssignmentStatus.COMPLETED, approval_status=ApprovalStatus.APPROVED,
        assigned_date=week, week_of=week,
    )
    db.add(a)
    await db.commit()
    return a


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
    assert body["paycheck_total_cents"] == 20000
    assert body["cash_total_cents"] == 3000
    assert body["grand_total_cents"] == 23000


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
