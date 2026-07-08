"""
P1-W6: MXN-denominated pricing.

Covers:
- USD + MXN plan rows coexisting per tier under UNIQUE(name, currency)
- /plans currency filtering (free tier always included)
- /checkout with an explicit MXN/USD currency and the MXN-first default
- premium gating staying currency-agnostic (tier resolved by name)
"""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.core.premium import (
    DEFAULT_FREE_LIMITS,
    PLAN_ORDER,
    get_family_plan,
    require_feature,
)
from app.models.subscription import FamilySubscription, SubscriptionPlan


@pytest.fixture(autouse=True)
def _mute_email_transport():
    """Billing state transitions dispatch emails; never hit SMTP in tests."""
    with patch(
        "app.services.email_service.EmailService._send",
        new=AsyncMock(return_value=True),
    ):
        yield


PLUS_LIMITS = {
    "max_family_members": 6,
    "max_budget_accounts": 10,
    "max_budget_transactions_per_month": -1,
    "max_recurring_transactions": -1,
    "budget_reports": True,
    "budget_goals": True,
    "csv_import": True,
    "max_receipt_scans_per_month": 50,
    "ai_features": True,
}


def _plan(name, currency, monthly, annual, *, limits=None, sort_order=10, **kw):
    return SubscriptionPlan(
        name=name,
        display_name=name.capitalize(),
        display_name_es=name.capitalize(),
        currency=currency,
        price_monthly_cents=monthly,
        price_annual_cents=annual,
        limits=limits or dict(PLUS_LIMITS),
        sort_order=sort_order,
        **kw,
    )


@pytest_asyncio.fixture
async def currency_plans(db_session):
    """free (USD) + plus/pro in both USD and MXN, PayPal ids wired."""
    plans = {
        "free": _plan(
            "free", "USD", 0, 0, limits=dict(DEFAULT_FREE_LIMITS), sort_order=0
        ),
        "plus_usd": _plan(
            "plus", "USD", 500, 5000,
            paypal_plan_id_monthly="P-PLUS-M-USD",
            paypal_plan_id_annual="P-PLUS-A-USD",
        ),
        "plus_mxn": _plan(
            "plus", "MXN", 9900, 99000,
            paypal_plan_id_monthly="P-PLUS-M-MXN",
            paypal_plan_id_annual="P-PLUS-A-MXN",
        ),
        "pro_usd": _plan(
            "pro", "USD", 1500, 15000, sort_order=20,
            paypal_plan_id_monthly="P-PRO-M-USD",
        ),
        "pro_mxn": _plan(
            "pro", "MXN", 19900, 199000, sort_order=20,
            paypal_plan_id_monthly="P-PRO-M-MXN",
        ),
    }
    db_session.add_all(plans.values())
    await db_session.commit()
    for p in plans.values():
        await db_session.refresh(p)
    return plans


# ---------------------------------------------------------------------------
# Schema: UNIQUE(name, currency)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_tier_coexists_across_currencies(db_session, currency_plans):
    """(plus, USD) and (plus, MXN) both live in the table."""
    assert currency_plans["plus_usd"].id != currency_plans["plus_mxn"].id
    assert currency_plans["plus_usd"].currency == "USD"
    assert currency_plans["plus_mxn"].currency == "MXN"


@pytest.mark.asyncio
async def test_duplicate_name_currency_rejected(db_session, currency_plans):
    db_session.add(_plan("plus", "MXN", 1234, 12340))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# /plans listing — currency filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_plans_unfiltered_returns_all_currency_rows(
    client, auth_headers, currency_plans
):
    resp = await client.get("/api/subscriptions/plans", headers=auth_headers)
    assert resp.status_code == 200
    plans = resp.json()
    assert len(plans) == 5
    assert all("currency" in p for p in plans)


@pytest.mark.asyncio
async def test_list_plans_mxn_filter_includes_free(
    client, auth_headers, currency_plans
):
    resp = await client.get(
        "/api/subscriptions/plans?currency=MXN", headers=auth_headers
    )
    assert resp.status_code == 200
    plans = resp.json()
    by_name = {(p["name"], p["currency"]) for p in plans}
    # Free tier is currency-less (price 0) — always listed.
    assert by_name == {("free", "USD"), ("plus", "MXN"), ("pro", "MXN")}
    mxn_plus = next(p for p in plans if p["name"] == "plus")
    assert mxn_plus["price_monthly_cents"] == 9900
    assert mxn_plus["price_annual_cents"] == 99000


@pytest.mark.asyncio
async def test_list_plans_usd_filter(client, auth_headers, currency_plans):
    resp = await client.get(
        "/api/subscriptions/plans?currency=usd", headers=auth_headers
    )
    assert resp.status_code == 200
    plans = resp.json()
    assert {(p["name"], p["currency"]) for p in plans} == {
        ("free", "USD"),
        ("plus", "USD"),
        ("pro", "USD"),
    }


# ---------------------------------------------------------------------------
# /checkout — currency-aware plan resolution
# ---------------------------------------------------------------------------

_PAYPAL_OK = {
    "subscription_id": "I-NEW-SUB",
    "approval_url": "https://paypal.example/approve",
    "status": "APPROVAL_PENDING",
}


async def _checkout(client, auth_headers, body):
    with patch(
        "app.services.paypal_service.PayPalService.create_subscription",
        return_value=dict(_PAYPAL_OK),
    ) as mock_create:
        resp = await client.post(
            "/api/subscriptions/checkout", headers=auth_headers, json=body
        )
    return resp, mock_create


@pytest.mark.asyncio
async def test_checkout_explicit_mxn_uses_mxn_paypal_plan(
    client, auth_headers, db_session, test_family, currency_plans
):
    resp, mock_create = await _checkout(
        client,
        auth_headers,
        {"plan_name": "plus", "billing_cycle": "monthly", "currency": "MXN"},
    )
    assert resp.status_code == 200, resp.text
    assert mock_create.call_args.kwargs["plan_id"] == "P-PLUS-M-MXN"

    row = (
        await db_session.execute(
            FamilySubscription.__table__.select().where(
                FamilySubscription.family_id == test_family.id
            )
        )
    ).one()
    assert row.plan_id == currency_plans["plus_mxn"].id
    assert row.status == "pending"


@pytest.mark.asyncio
async def test_checkout_defaults_to_mxn_when_both_currencies_exist(
    client, auth_headers, currency_plans
):
    """Mexico-first: no currency in the request → the MXN row wins."""
    resp, mock_create = await _checkout(
        client, auth_headers, {"plan_name": "pro", "billing_cycle": "monthly"}
    )
    assert resp.status_code == 200, resp.text
    assert mock_create.call_args.kwargs["plan_id"] == "P-PRO-M-MXN"


@pytest.mark.asyncio
async def test_checkout_explicit_usd(client, auth_headers, currency_plans):
    resp, mock_create = await _checkout(
        client,
        auth_headers,
        {"plan_name": "plus", "billing_cycle": "annual", "currency": "usd"},
    )
    assert resp.status_code == 200, resp.text
    assert mock_create.call_args.kwargs["plan_id"] == "P-PLUS-A-USD"


@pytest.mark.asyncio
async def test_checkout_unknown_currency_404(
    client, auth_headers, currency_plans
):
    resp, _ = await _checkout(
        client,
        auth_headers,
        {"plan_name": "plus", "billing_cycle": "monthly", "currency": "EUR"},
    )
    assert resp.status_code == 404
    assert "EUR" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_checkout_single_currency_tier_still_works_without_currency(
    client, auth_headers, db_session
):
    """Backward compatibility: a tier with one row (USD only) resolves fine."""
    plan = _plan(
        "plus", "USD", 500, 5000, paypal_plan_id_monthly="P-ONLY-USD"
    )
    db_session.add(plan)
    await db_session.commit()

    resp, mock_create = await _checkout(
        client, auth_headers, {"plan_name": "plus", "billing_cycle": "monthly"}
    )
    assert resp.status_code == 200, resp.text
    assert mock_create.call_args.kwargs["plan_id"] == "P-ONLY-USD"


@pytest.mark.asyncio
async def test_checkout_default_skips_unwired_mxn_row(
    client, auth_headers, db_session
):
    """Deploy-to-provisioning window: an MXN row exists but its PayPal ids
    are NULL (operator has not wired PayPal yet). A currency-omitted checkout
    must fall back to the wired USD row instead of 501ing every upgrade."""
    db_session.add_all(
        [
            _plan(
                "plus", "USD", 500, 5000,
                paypal_plan_id_monthly="P-PLUS-M-USD",
                paypal_plan_id_annual="P-PLUS-A-USD",
            ),
            _plan("plus", "MXN", 9900, 99000),  # unwired
        ]
    )
    await db_session.commit()

    resp, mock_create = await _checkout(
        client, auth_headers, {"plan_name": "plus", "billing_cycle": "monthly"}
    )
    assert resp.status_code == 200, resp.text
    assert mock_create.call_args.kwargs["plan_id"] == "P-PLUS-M-USD"


@pytest.mark.asyncio
async def test_checkout_default_wiredness_is_per_billing_cycle(
    client, auth_headers, db_session
):
    """MXN wired for monthly only: monthly defaults to MXN (Mexico-first),
    annual falls back to the USD row that can actually bill."""
    db_session.add_all(
        [
            _plan(
                "plus", "USD", 500, 5000,
                paypal_plan_id_monthly="P-PLUS-M-USD",
                paypal_plan_id_annual="P-PLUS-A-USD",
            ),
            _plan(
                "plus", "MXN", 9900, 99000,
                paypal_plan_id_monthly="P-PLUS-M-MXN",  # annual unwired
            ),
        ]
    )
    await db_session.commit()

    resp, mock_create = await _checkout(
        client, auth_headers, {"plan_name": "plus", "billing_cycle": "monthly"}
    )
    assert resp.status_code == 200, resp.text
    assert mock_create.call_args.kwargs["plan_id"] == "P-PLUS-M-MXN"

    resp, mock_create = await _checkout(
        client, auth_headers, {"plan_name": "plus", "billing_cycle": "annual"}
    )
    assert resp.status_code == 200, resp.text
    assert mock_create.call_args.kwargs["plan_id"] == "P-PLUS-A-USD"


@pytest.mark.asyncio
async def test_checkout_explicit_unwired_currency_still_501(
    client, auth_headers, db_session
):
    """Explicitly asking for an unwired currency keeps surfacing the 501 —
    the fallback only applies to the currency-omitted default."""
    db_session.add_all(
        [
            _plan(
                "plus", "USD", 500, 5000, paypal_plan_id_monthly="P-PLUS-M-USD"
            ),
            _plan("plus", "MXN", 9900, 99000),  # unwired
        ]
    )
    await db_session.commit()

    resp, _ = await _checkout(
        client,
        auth_headers,
        {"plan_name": "plus", "billing_cycle": "monthly", "currency": "MXN"},
    )
    assert resp.status_code == 501


@pytest.mark.asyncio
async def test_checkout_invalid_billing_cycle_400(client, auth_headers):
    resp, _ = await _checkout(
        client, auth_headers, {"plan_name": "plus", "billing_cycle": "weekly"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_migration_seeded_inactive_mxn_rows_invisible_and_skipped(
    client, auth_headers, db_session
):
    """Mirrors the exact post-migration prod state: MXN rows seeded with
    is_active = false until the operator's wiring SQL activates them. They
    must not be listed and the default checkout stays on the USD row."""
    db_session.add_all(
        [
            _plan(
                "free", "USD", 0, 0,
                limits=dict(DEFAULT_FREE_LIMITS), sort_order=0,
            ),
            _plan(
                "plus", "USD", 500, 5000, paypal_plan_id_monthly="P-PLUS-M-USD"
            ),
            _plan("plus", "MXN", 9900, 99000, is_active=False),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/subscriptions/plans", headers=auth_headers)
    assert resp.status_code == 200
    assert {(p["name"], p["currency"]) for p in resp.json()} == {
        ("free", "USD"),
        ("plus", "USD"),
    }

    resp, mock_create = await _checkout(
        client, auth_headers, {"plan_name": "plus", "billing_cycle": "monthly"}
    )
    assert resp.status_code == 200, resp.text
    assert mock_create.call_args.kwargs["plan_id"] == "P-PLUS-M-USD"


@pytest.mark.asyncio
async def test_zero_price_non_free_tier_not_leaked_into_currency_listing(
    client, auth_headers, db_session, currency_plans
):
    """The always-include branch keys on name == 'free' (tier identity), not
    a zero-price heuristic: a $0 promo tier in USD must not appear in the
    MXN-filtered listing."""
    db_session.add(_plan("promo", "USD", 0, 0, sort_order=5))
    await db_session.commit()

    resp = await client.get(
        "/api/subscriptions/plans?currency=MXN", headers=auth_headers
    )
    assert resp.status_code == 200
    by_name = {(p["name"], p["currency"]) for p in resp.json()}
    assert ("promo", "USD") not in by_name
    assert ("free", "USD") in by_name


@pytest.mark.asyncio
async def test_plans_expose_checkout_readiness_not_paypal_ids(
    client, auth_headers, currency_plans
):
    """The pricing UI needs to know which rows can actually check out, but
    the raw PayPal plan ids stay server-side."""
    resp = await client.get("/api/subscriptions/plans", headers=auth_headers)
    assert resp.status_code == 200
    plans = {(p["name"], p["currency"]): p for p in resp.json()}

    pro_usd = plans[("pro", "USD")]  # fixture wires monthly only
    assert pro_usd["checkout_ready_monthly"] is True
    assert pro_usd["checkout_ready_annual"] is False
    plus_mxn = plans[("plus", "MXN")]  # fully wired
    assert plus_mxn["checkout_ready_monthly"] is True
    assert plus_mxn["checkout_ready_annual"] is True
    free = plans[("free", "USD")]
    assert free["checkout_ready_monthly"] is False

    for p in plans.values():
        assert "paypal_plan_id_monthly" not in p
        assert "paypal_plan_id_annual" not in p


# ---------------------------------------------------------------------------
# Premium gating stays currency-agnostic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mxn_subscription_grants_tier_by_name(
    db_session, test_family, test_parent_user, currency_plans
):
    """A family on the MXN plus row resolves to tier 'plus' — same limits,
    same PLAN_ORDER rank — exactly like the USD row."""
    db_session.add(
        FamilySubscription(
            family_id=test_family.id,
            plan_id=currency_plans["plus_mxn"].id,
            billing_cycle="monthly",
            status="active",
        )
    )
    await db_session.commit()

    plan = await get_family_plan(db_session, test_parent_user)
    assert plan.name == "plus"
    assert plan.name in PLAN_ORDER
    assert plan.limits["budget_reports"] is True

    gated = await require_feature("budget_reports", db_session, test_parent_user)
    assert gated.name == "plus"


@pytest.mark.asyncio
async def test_free_fallback_survives_multiple_free_currency_rows(
    db_session, test_parent_user, currency_plans
):
    """If 'free' ever gains a second currency row, plan resolution must not
    blow up (regression guard for the old scalar_one_or_none lookup)."""
    db_session.add(
        _plan("free", "MXN", 0, 0, limits=dict(DEFAULT_FREE_LIMITS), sort_order=0)
    )
    await db_session.commit()

    plan = await get_family_plan(db_session, test_parent_user)
    assert plan.name == "free"
    assert plan.limits["max_family_members"] == DEFAULT_FREE_LIMITS[
        "max_family_members"
    ]
