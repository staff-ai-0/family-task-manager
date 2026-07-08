"""Tests for the setup-paypal-plans script."""
from unittest.mock import MagicMock

from scripts.setup_paypal_plans import (
    PLAN_PRICES,
    build_plan_definitions,
    create_product_if_missing,
    create_plan_if_missing,
    main,
    plan_meta,
    _env_key,
    _sql_update,
)


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


def test_prices_cover_all_tiers_for_each_currency():
    for currency, prices in PLAN_PRICES.items():
        assert set(prices) == {
            ("plus", "monthly"),
            ("plus", "annual"),
            ("pro", "monthly"),
            ("pro", "annual"),
        }, currency


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


def test_create_plan_skips_if_exists():
    fake_api = MagicMock()
    fake_api.get.return_value = {
        "plans": [{"id": "P-EXISTING", "name": "Plus Monthly"}]
    }
    pid = create_plan_if_missing(fake_api, plan_def={"name": "Plus Monthly"})
    assert pid == "P-EXISTING"
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
        "plans": [{"id": "P-EXISTING-MXN", "name": "Plus Monthly MXN"}],
        "links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v1/billing/plans?page_size=20&page=2"}],
    }
    fake_api.get.side_effect = [page1, page2]

    pid = create_plan_if_missing(fake_api, plan_def={"name": "Plus Monthly MXN"})

    assert pid == "P-EXISTING-MXN"
    fake_api.post.assert_not_called()
    assert fake_api.get.call_count == 2
    # The followed href is passed base-relative (PayPalAPI.get prefixes base).
    followed = fake_api.get.call_args_list[1].args[0]
    assert followed == "/v1/billing/plans?page_size=20&page=2"


def test_create_plan_creates_only_after_scanning_all_pages():
    fake_api = MagicMock()
    page1 = {
        "plans": [{"id": "P-1", "name": "Other Plan"}],
        "links": [{"rel": "next", "href": "https://api-m.paypal.com/v1/billing/plans?page=2"}],
    }
    page2 = {"plans": [{"id": "P-2", "name": "Another Plan"}]}
    fake_api.get.side_effect = [page1, page2]
    fake_api.post.return_value = {"id": "P-NEW"}

    pid = create_plan_if_missing(fake_api, plan_def={"name": "Plus Monthly MXN"})

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
