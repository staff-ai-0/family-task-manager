"""Kid budget-envelopes tests (P2 — CASH ledger / Family Bank jars).

The envelopes view is a THIN, read-only projection over each kid's existing
Family Bank jars (Spend/Save/Share == cash_cents) plus their named savings goal.
No new table. Covers:

- envelope balances reflect the kid's jar/cash balances (+ pct-of-total + goal
  overlay on the Save envelope);
- per-kid isolation: a kid cannot see a sibling's envelopes (403);
- parent sees ALL kids in the family;
- family isolation: another family's kid is invisible (list) / 404 (by id);
- two-currency guard: envelopes never reflect or touch POINTS.

Run: podman exec -e PYTHONPATH=/app family_app_backend \
     pytest tests/test_kid_envelopes.py -v --no-cov
"""
from uuid import uuid4

import pytest

from app.models.family import Family
from app.models.user import APPROVAL_APPROVED, User, UserRole
from app.services.bank_service import BankService
from app.services.envelope_service import EnvelopeService
from app.services.savings_goal_service import SavingsGoalService


# ── helpers ──────────────────────────────────────────────────────────────────


async def _mk_family(db, tz="UTC"):
    fam = Family(name="Fam", timezone=tz)
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


async def _mk_user(db, fam, role=UserRole.CHILD, cash=0, points=0, name="Kid"):
    u = User(
        email=f"u{uuid4().hex[:10]}@t.com", name=name, role=role,
        family_id=fam.id, email_verified=True, cash_cents=cash, points=points,
        approval_status=APPROVAL_APPROVED, is_active=True, preferred_lang="es",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _set_jars(db, kid, spend=0, save=0, share=0):
    """Materialize the kid's jars, keeping invariant #1 (jar sum == cash)."""
    acct = await BankService.ensure_account(db, kid)
    acct.spend_cents = spend
    acct.save_cents = save
    acct.share_cents = share
    kid.cash_cents = spend + save + share
    await db.commit()
    await db.refresh(acct)
    await db.refresh(kid)
    return acct


async def _login(client, email, pw="password123"):
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _by_key(view: dict) -> dict:
    return {e["key"]: e for e in view["envelopes"]}


# ── service: balances reflect the jars ───────────────────────────────────────


@pytest.mark.asyncio
async def test_envelopes_reflect_jar_balances(db):
    fam = await _mk_family(db)
    kid = await _mk_user(db, fam)
    await _set_jars(db, kid, spend=5000, save=3000, share=2000)

    view = await EnvelopeService.get_kid_envelopes(db, kid)
    assert view["user_id"] == kid.id
    assert view["total_cents"] == 10000
    envs = _by_key(view)
    assert set(envs) == {"spend", "save", "share"}
    assert envs["spend"]["balance_cents"] == 5000
    assert envs["save"]["balance_cents"] == 3000
    assert envs["share"]["balance_cents"] == 2000
    # pct_of_total = jar's share of total cash
    assert envs["spend"]["pct_of_total"] == 50
    assert envs["save"]["pct_of_total"] == 30
    assert envs["share"]["pct_of_total"] == 20
    # No goal set → no overlay on any envelope.
    assert all(e["goal"] is None for e in view["envelopes"])


@pytest.mark.asyncio
async def test_envelopes_zero_balance_no_div_by_zero(db):
    fam = await _mk_family(db)
    kid = await _mk_user(db, fam)  # no jars touched → all zero
    view = await EnvelopeService.get_kid_envelopes(db, kid)
    assert view["total_cents"] == 0
    assert all(e["balance_cents"] == 0 and e["pct_of_total"] == 0 for e in view["envelopes"])


@pytest.mark.asyncio
async def test_total_equals_cash_cents_invariant(db):
    fam = await _mk_family(db)
    kid = await _mk_user(db, fam)
    await _set_jars(db, kid, spend=1200, save=800, share=0)
    view = await EnvelopeService.get_kid_envelopes(db, kid)
    await db.refresh(kid)
    assert view["total_cents"] == kid.cash_cents == 2000


# ── service: savings goal overlays the Save envelope ─────────────────────────


@pytest.mark.asyncio
async def test_goal_overlays_save_envelope(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    await SavingsGoalService.create_goal(
        db, parent, kid=kid, name="bici", target_cents=6000, emoji="🚲"
    )
    await _set_jars(db, kid, spend=0, save=3000, share=0)

    view = await EnvelopeService.get_kid_envelopes(db, kid)
    envs = _by_key(view)
    # Goal only rides the Save envelope (it tracks the Save jar).
    assert envs["spend"]["goal"] is None
    assert envs["share"]["goal"] is None
    goal = envs["save"]["goal"]
    assert goal is not None
    assert goal["name"] == "bici"
    assert goal["emoji"] == "🚲"
    assert goal["target_cents"] == 6000
    assert goal["saved_cents"] == 3000
    assert goal["remaining_cents"] == 3000
    assert goal["progress_pct"] == 50
    assert goal["reached"] is False
    assert goal["pending_approval"] is False  # parent-created → active


@pytest.mark.asyncio
async def test_goal_reached_reflected(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    await SavingsGoalService.create_goal(db, parent, kid=kid, name="switch", target_cents=5000)
    await _set_jars(db, kid, save=5000)
    view = await EnvelopeService.get_kid_envelopes(db, kid)
    goal = _by_key(view)["save"]["goal"]
    assert goal["reached"] is True
    assert goal["progress_pct"] == 100
    assert goal["remaining_cents"] == 0
    # The projection is read-only: it must NOT fire the goal-reached
    # celebration (notify=False), even when save == target.
    from sqlalchemy import select as _select
    from app.models.kid_savings_goal import KidSavingsGoal
    goal_row = (await db.execute(
        _select(KidSavingsGoal).where(KidSavingsGoal.user_id == kid.id)
    )).scalar_one()
    assert goal_row.reached_at is None


# ── service: family view returns every kid, scoped ───────────────────────────


@pytest.mark.asyncio
async def test_family_envelopes_lists_all_kids(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    child = await _mk_user(db, fam, role=UserRole.CHILD, name="C")
    teen = await _mk_user(db, fam, role=UserRole.TEEN, name="T")
    await _set_jars(db, child, spend=100)
    await _set_jars(db, teen, save=200)

    rows = await EnvelopeService.get_family_envelopes(db, parent)
    ids = {r["user_id"] for r in rows}
    assert ids == {child.id, teen.id}  # parents themselves are not listed


@pytest.mark.asyncio
async def test_family_envelopes_excludes_other_family(db):
    fam_a = await _mk_family(db)
    fam_b = await _mk_family(db)
    parent_a = await _mk_user(db, fam_a, role=UserRole.PARENT)
    kid_a = await _mk_user(db, fam_a)
    kid_b = await _mk_user(db, fam_b)  # different family
    rows = await EnvelopeService.get_family_envelopes(db, parent_a)
    ids = {r["user_id"] for r in rows}
    assert ids == {kid_a.id}
    assert kid_b.id not in ids


# ── service: two-currency guard (no points coupling) ─────────────────────────


@pytest.mark.asyncio
async def test_envelopes_ignore_points(db):
    fam = await _mk_family(db)
    kid = await _mk_user(db, fam, points=999999)
    await _set_jars(db, kid, spend=1000, save=500, share=0)
    view = await EnvelopeService.get_kid_envelopes(db, kid)
    # Total tracks CASH only; points are invisible to envelopes.
    assert view["total_cents"] == 1500
    # No envelope field mentions points anywhere.
    blob = str(view).lower()
    assert "point" not in blob
    # Points were never mutated by the read.
    await db.refresh(kid)
    assert kid.points == 999999


# ── routes: per-kid isolation + parent access + family isolation ─────────────


@pytest.mark.asyncio
async def test_route_kid_sees_own_envelopes(client, test_child_user):
    h = await _login(client, "child@test.com")
    r = await client.get("/api/bank/envelopes/me", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == str(test_child_user.id)
    assert {e["key"] for e in body["envelopes"]} == {"spend", "save", "share"}


@pytest.mark.asyncio
async def test_route_parent_me_is_400(client, test_parent_user):
    h = await _login(client, "parent@test.com")
    r = await client.get("/api/bank/envelopes/me", headers=h)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_route_kid_cannot_see_sibling(client, test_child_user, test_teen_user):
    """Per-kid isolation: a kid cannot see a sibling's envelopes."""
    h = await _login(client, "child@test.com")
    r = await client.get(f"/api/bank/envelopes/{test_teen_user.id}", headers=h)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_route_kid_can_see_own_by_id(client, test_child_user):
    h = await _login(client, "child@test.com")
    r = await client.get(f"/api/bank/envelopes/{test_child_user.id}", headers=h)
    assert r.status_code == 200
    assert r.json()["user_id"] == str(test_child_user.id)


@pytest.mark.asyncio
async def test_route_parent_sees_all_kids(client, test_parent_user, test_child_user, test_teen_user):
    """Parent sees ALL kids' envelopes in the family."""
    h = await _login(client, "parent@test.com")
    r = await client.get("/api/bank/envelopes/family", headers=h)
    assert r.status_code == 200, r.text
    ids = {row["user_id"] for row in r.json()}
    assert ids == {str(test_child_user.id), str(test_teen_user.id)}


@pytest.mark.asyncio
async def test_route_parent_sees_specific_kid(client, test_parent_user, test_child_user):
    h = await _login(client, "parent@test.com")
    r = await client.get(f"/api/bank/envelopes/{test_child_user.id}", headers=h)
    assert r.status_code == 200
    assert r.json()["user_id"] == str(test_child_user.id)


@pytest.mark.asyncio
async def test_route_family_isolation_404(client, db, test_parent_user, test_child_user):
    """A parent cannot view a kid from another family (404, tenant isolation)."""
    other_fam = await _mk_family(db)
    other_kid = await _mk_user(db, other_fam)
    h = await _login(client, "parent@test.com")

    # By id → 404 (not in the parent's family).
    r = await client.get(f"/api/bank/envelopes/{other_kid.id}", headers=h)
    assert r.status_code == 404

    # Family list never leaks the other family's kid.
    r2 = await client.get("/api/bank/envelopes/family", headers=h)
    assert r2.status_code == 200
    ids = {row["user_id"] for row in r2.json()}
    assert str(other_kid.id) not in ids
    assert ids == {str(test_child_user.id)}


@pytest.mark.asyncio
async def test_route_parent_target_must_be_kid(client, test_parent_user):
    """Targeting a non-kid (e.g. another parent) by id → 400."""
    h = await _login(client, "parent@test.com")
    r = await client.get(f"/api/bank/envelopes/{test_parent_user.id}", headers=h)
    assert r.status_code == 400
