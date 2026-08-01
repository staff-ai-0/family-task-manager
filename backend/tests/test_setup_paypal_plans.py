"""Tests for the setup-paypal-plans script."""
from unittest.mock import MagicMock

import pytest

from scripts.setup_paypal_plans import (
    PlanPriceMismatch,
    PlanPriceUnavailable,
    build_plan_definitions,
    create_product_if_missing,
    create_plan_if_missing,
    main,
    plan_meta,
    _env_key,
    _sql_update,
)


def _regular_cycle(value: str, currency: str = "USD") -> list[dict]:
    """A minimal billing_cycles list containing only the REGULAR cycle —
    all create_plan_if_missing's price check looks at."""
    return [
        {
            "tenure_type": "REGULAR",
            "pricing_scheme": {
                "fixed_price": {"value": value, "currency_code": currency}
            },
        }
    ]


def test_build_plan_definitions_returns_eight_across_currencies():
    defs = build_plan_definitions(product_id="PROD-FAM")
    names = [d["name"] for d in defs]
    # Legacy USD names preserved (idempotency key at PayPal's side)
    assert "Plus Monthly" in names
    assert "Plus Annual" in names
    assert "Pro Monthly" in names
    assert "Pro Annual" in names
    # MXN counterparts
    assert "Plus Monthly MXN" in names
    assert "Plus Annual MXN" in names
    assert "Pro Monthly MXN" in names
    assert "Pro Annual MXN" in names
    assert len(defs) == 8


def test_build_plan_definitions_usd_only_matches_legacy_four():
    defs = build_plan_definitions(product_id="PROD-FAM", currencies=("USD",))
    assert len(defs) == 4
    assert all(len(d["name"].split(" ")) == 2 for d in defs)


def test_build_plan_definitions_has_trial_cycle():
    defs = build_plan_definitions(product_id="PROD-FAM")
    for d in defs:
        cycles = d["billing_cycles"]
        assert cycles[0]["tenure_type"] == "TRIAL"
        assert cycles[0]["frequency"]["interval_unit"] == "DAY"
        assert cycles[0]["frequency"]["interval_count"] == 7


def test_mxn_plan_prices_and_currency_consistency():
    defs = build_plan_definitions(product_id="PROD-FAM", currencies=("MXN",))
    by_name = {d["name"]: d for d in defs}
    assert len(defs) == 4

    expected = {
        "Plus Monthly MXN": "99.00",
        "Plus Annual MXN": "990.00",
        "Pro Monthly MXN": "199.00",
        "Pro Annual MXN": "1990.00",
    }
    for name, value in expected.items():
        d = by_name[name]
        trial, regular = d["billing_cycles"]
        assert regular["pricing_scheme"]["fixed_price"] == {
            "value": value,
            "currency_code": "MXN",
        }
        # Trial price and setup fee must be denominated in the plan currency
        assert trial["pricing_scheme"]["fixed_price"]["currency_code"] == "MXN"
        assert (
            d["payment_preferences"]["setup_fee"]["currency_code"] == "MXN"
        )


def test_plan_meta_roundtrip():
    defs = build_plan_definitions(product_id="PROD-FAM")
    metas = {plan_meta(d) for d in defs}
    assert ("plus", "monthly", "USD") in metas
    assert ("pro", "annual", "MXN") in metas
    assert len(metas) == 8


def test_env_key_and_sql_update_formats():
    assert _env_key("plus", "monthly", "USD") == "PAYPAL_PLAN_ID_PLUS_MONTHLY"
    assert _env_key("pro", "annual", "MXN") == "PAYPAL_PLAN_ID_PRO_ANNUAL_MXN"
    sql = _sql_update("plus", "monthly", "MXN", "P-123")
    assert "paypal_plan_id_monthly" in sql
    assert "name = 'plus' AND currency = 'MXN'" in sql
    assert "'P-123'" in sql


def test_sql_update_activates_the_row():
    """Wiring SQL must flip is_active = true: the migration seeds MXN rows
    inactive so they cannot be listed/checked out before provisioning."""
    sql = _sql_update("pro", "annual", "MXN", "P-456")
    assert "is_active = true" in sql


def test_dry_run_makes_no_api_calls_and_needs_no_credentials(capsys, monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    rc = main(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Plus Monthly MXN" in out
    assert "199.00" in out


def test_create_product_skips_if_exists():
    fake_api = MagicMock()
    fake_api.get.return_value = {
        "products": [{"id": "EXISTING", "name": "Family Task Manager"}]
    }
    pid = create_product_if_missing(fake_api, name="Family Task Manager")
    assert pid == "EXISTING"
    fake_api.post.assert_not_called()


def test_create_plan_skips_if_exists_and_price_matches():
    """The List Plans item name-matches; the price comparison must be made
    against the Show Plan Details fetch (the second api.get call), not the
    list item itself."""
    fake_api = MagicMock()
    list_page = {
        "plans": [
            {
                "id": "P-EXISTING",
                "name": "Plus Monthly",
                "billing_cycles": _regular_cycle("5.00", "USD"),
            }
        ]
    }
    detail = {
        "id": "P-EXISTING",
        "name": "Plus Monthly",
        "billing_cycles": _regular_cycle("5.00", "USD"),
    }
    fake_api.get.side_effect = [list_page, detail]
    plan_def = {"name": "Plus Monthly", "billing_cycles": _regular_cycle("5.00", "USD")}
    pid = create_plan_if_missing(fake_api, plan_def=plan_def)
    assert pid == "P-EXISTING"
    fake_api.post.assert_not_called()
    assert fake_api.get.call_count == 2
    assert fake_api.get.call_args_list[1].args[0] == "/v1/billing/plans/P-EXISTING"


def test_create_plan_reused_when_list_response_lacks_billing_cycles():
    """Regression test for the defect this fix corrects.

    Per PayPal's published OpenAPI spec, GET /v1/billing/plans defaults to
    `Prefer: return=minimal` — a minimal response carries only `id`,
    `status`, and HATEOAS `links`, NEVER `billing_cycles`. This is the
    REALISTIC shape of a List Plans item against the real API (unlike the
    other tests in this file, which stub `billing_cycles` directly onto the
    list item for convenience). The old code treated an absent
    `billing_cycles` as a price mismatch and raised `PlanPriceMismatch:
    ... charges None`, aborting the entire provisioning run on the very
    first name match. The fix must instead fetch the plan's full
    representation via Show Plan Details and compare THAT — so a plan
    charging the canonical price is reused with no exception, even though
    the list item itself carried no price data at all.
    """
    fake_api = MagicMock()
    list_page = {
        "plans": [
            {
                "id": "P-EXISTING",
                "status": "ACTIVE",
                "links": [{"rel": "self", "href": "https://api-m.paypal.com/v1/billing/plans/P-EXISTING"}],
                # No "name" key omitted deliberately — minimal responses DO
                # include name (needed for the match itself); what's absent
                # is billing_cycles.
                "name": "Plus Monthly",
            }
        ]
    }
    detail = {
        "id": "P-EXISTING",
        "name": "Plus Monthly",
        "billing_cycles": _regular_cycle("5.00", "USD"),
    }
    fake_api.get.side_effect = [list_page, detail]

    plan_def = {"name": "Plus Monthly", "billing_cycles": _regular_cycle("5.00", "USD")}
    pid = create_plan_if_missing(fake_api, plan_def=plan_def)

    assert pid == "P-EXISTING"
    fake_api.post.assert_not_called()
    assert fake_api.get.call_count == 2
    assert fake_api.get.call_args_list[1].args[0] == "/v1/billing/plans/P-EXISTING"


def test_create_plan_reused_when_price_differs_only_in_formatting():
    """Regression test for the 2026-07-31 LIVE provisioning abort.

    The real API returned {'currency_code': 'USD', 'value': '5.0'} for the
    July-provisioned "Plus Monthly" plan — numerically identical to the
    canonical '5.00', but raw dict equality treated the formatting
    difference as a stale price and aborted the whole run with zero output.
    PayPal does not guarantee decimal formatting on the wire; comparison
    must be numeric (Decimal) on value + exact on currency_code.
    """
    fake_api = MagicMock()
    list_page = {"plans": [{"id": "P-FMT", "name": "Plus Monthly"}]}
    detail = {
        "id": "P-FMT",
        "name": "Plus Monthly",
        # the exact wire shape observed live on 2026-07-31
        "billing_cycles": _regular_cycle("5.0", "USD"),
    }
    fake_api.get.side_effect = [list_page, detail]
    plan_def = {"name": "Plus Monthly", "billing_cycles": _regular_cycle("5.00", "USD")}

    pid = create_plan_if_missing(fake_api, plan_def=plan_def)

    assert pid == "P-FMT"
    fake_api.post.assert_not_called()


def test_create_plan_raises_price_unavailable_on_malformed_value():
    """A value Decimal cannot parse is missing/malformed price data, not
    evidence of a stale price — PlanPriceUnavailable, never a crash and
    never PlanPriceMismatch."""
    fake_api = MagicMock()
    list_page = {"plans": [{"id": "P-GARBAGE", "name": "Plus Monthly"}]}
    detail = {
        "id": "P-GARBAGE",
        "name": "Plus Monthly",
        "billing_cycles": _regular_cycle("not-a-number", "USD"),
    }
    fake_api.get.side_effect = [list_page, detail]
    plan_def = {"name": "Plus Monthly", "billing_cycles": _regular_cycle("5.00", "USD")}

    with pytest.raises(PlanPriceUnavailable):
        create_plan_if_missing(fake_api, plan_def=plan_def)


def test_create_plan_raises_on_price_mismatch():
    """Whole-branch review Fix 4: a name match with a STALE price must NOT
    be silently reused — that is precisely how a customer could be charged
    something the DB never showed them (DB force-set to canonical while
    PayPal keeps billing the old amount). The stale price is discovered via
    the Show Plan Details fetch, not the list item."""
    fake_api = MagicMock()
    list_page = {
        "plans": [
            {
                "id": "P-STALE",
                "name": "Plus Monthly",
            }
        ]
    }
    detail = {
        "id": "P-STALE",
        "name": "Plus Monthly",
        # pre-usd_price_alignment price — canonical is now 5.00
        "billing_cycles": _regular_cycle("4.99", "USD"),
    }
    fake_api.get.side_effect = [list_page, detail]
    plan_def = {"name": "Plus Monthly", "billing_cycles": _regular_cycle("5.00", "USD")}

    with pytest.raises(PlanPriceMismatch) as exc_info:
        create_plan_if_missing(fake_api, plan_def=plan_def)

    message = str(exc_info.value)
    assert "P-STALE" in message
    assert "4.99" in message
    assert "5.00" in message
    fake_api.post.assert_not_called()


def test_create_plan_raises_on_currency_mismatch():
    """Value can match while currency_code differs — must still abort."""
    fake_api = MagicMock()
    list_page = {
        "plans": [
            {
                "id": "P-WRONG-CCY",
                "name": "Plus Monthly MXN",
            }
        ]
    }
    detail = {
        "id": "P-WRONG-CCY",
        "name": "Plus Monthly MXN",
        "billing_cycles": _regular_cycle("99.00", "USD"),
    }
    fake_api.get.side_effect = [list_page, detail]
    plan_def = {
        "name": "Plus Monthly MXN",
        "billing_cycles": _regular_cycle("99.00", "MXN"),
    }

    with pytest.raises(PlanPriceMismatch):
        create_plan_if_missing(fake_api, plan_def=plan_def)


def test_create_plan_raises_price_unavailable_when_detail_fetch_still_has_no_price():
    """Distinct from a stale-price mismatch: the Show Plan Details response
    itself has no REGULAR billing cycle at all (missing/malformed data).
    Must raise PlanPriceUnavailable, NOT PlanPriceMismatch — this is a
    different problem with its own message, not evidence of a stale
    price."""
    fake_api = MagicMock()
    list_page = {
        "plans": [
            {
                "id": "P-BROKEN",
                "name": "Plus Monthly",
            }
        ]
    }
    detail = {
        "id": "P-BROKEN",
        "name": "Plus Monthly",
        "billing_cycles": [{"tenure_type": "TRIAL"}],  # no REGULAR cycle at all
    }
    fake_api.get.side_effect = [list_page, detail]
    plan_def = {"name": "Plus Monthly", "billing_cycles": _regular_cycle("5.00", "USD")}

    with pytest.raises(PlanPriceUnavailable) as exc_info:
        create_plan_if_missing(fake_api, plan_def=plan_def)

    message = str(exc_info.value)
    assert "P-BROKEN" in message
    fake_api.post.assert_not_called()


def test_create_plan_finds_match_beyond_first_page():
    """Idempotency must survive accounts with >20 pre-existing plans: the
    lookup follows the links rel=next chain instead of reading page 1 only
    (which would create a duplicate ACTIVE plan on re-run)."""
    fake_api = MagicMock()
    page1 = {
        "plans": [{"id": f"P-{i}", "name": f"Legacy Plan {i}"} for i in range(20)],
        "links": [
            {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v1/billing/plans?page_size=20&page=1"},
            {"rel": "next", "href": "https://api-m.sandbox.paypal.com/v1/billing/plans?page_size=20&page=2"},
        ],
    }
    page2 = {
        "plans": [{
            "id": "P-EXISTING-MXN",
            "name": "Plus Monthly MXN",
        }],
        "links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v1/billing/plans?page_size=20&page=2"}],
    }
    detail = {
        "id": "P-EXISTING-MXN",
        "name": "Plus Monthly MXN",
        "billing_cycles": _regular_cycle("99.00", "MXN"),
    }
    fake_api.get.side_effect = [page1, page2, detail]

    plan_def = {"name": "Plus Monthly MXN", "billing_cycles": _regular_cycle("99.00", "MXN")}
    pid = create_plan_if_missing(fake_api, plan_def=plan_def)

    assert pid == "P-EXISTING-MXN"
    fake_api.post.assert_not_called()
    assert fake_api.get.call_count == 3
    # The followed href is passed base-relative (PayPalAPI.get prefixes base).
    followed = fake_api.get.call_args_list[1].args[0]
    assert followed == "/v1/billing/plans?page_size=20&page=2"
    # The final call is the Show Plan Details detail fetch on the match.
    assert fake_api.get.call_args_list[2].args[0] == "/v1/billing/plans/P-EXISTING-MXN"


def test_create_plan_creates_only_after_scanning_all_pages():
    fake_api = MagicMock()
    page1 = {
        "plans": [{"id": "P-1", "name": "Other Plan"}],
        "links": [{"rel": "next", "href": "https://api-m.paypal.com/v1/billing/plans?page=2"}],
    }
    page2 = {"plans": [{"id": "P-2", "name": "Another Plan"}]}
    fake_api.get.side_effect = [page1, page2]
    fake_api.post.return_value = {"id": "P-NEW"}

    plan_def = {"name": "Plus Monthly MXN", "billing_cycles": _regular_cycle("99.00", "MXN")}
    pid = create_plan_if_missing(fake_api, plan_def=plan_def)

    assert pid == "P-NEW"
    assert fake_api.get.call_count == 2
    fake_api.post.assert_called_once()


def test_create_product_finds_match_beyond_first_page():
    fake_api = MagicMock()
    page1 = {
        "products": [{"id": "PROD-OTHER", "name": "Some Other Product"}],
        "links": [{"rel": "next", "href": "https://api-m.paypal.com/v1/catalogs/products?page_size=20&page=2"}],
    }
    page2 = {"products": [{"id": "EXISTING", "name": "Family Task Manager"}]}
    fake_api.get.side_effect = [page1, page2]

    pid = create_product_if_missing(fake_api, name="Family Task Manager")

    assert pid == "EXISTING"
    fake_api.post.assert_not_called()
    assert fake_api.get.call_count == 2
