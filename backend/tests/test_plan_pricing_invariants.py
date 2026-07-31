"""Invariants for subscription plan pricing.

Prod shipped with every paid plan priced at 0 for ~2 weeks (2026-07-16 →
2026-07-31) because the price lived in three hand-synced copies and nothing
compared them. These tests pin the single source of truth.

NOTE: conftest builds the schema with Base.metadata.create_all, so
subscription_plans starts EMPTY here. Nothing in this file may assume the
alembic seed ran — rows under test are created explicitly.
"""
import pytest

from app.core.plan_pricing import (
    CANONICAL_PRICES,
    price_decimal_str,
    price_minor,
)


def test_canonical_table_covers_every_paid_tier_and_currency():
    assert set(CANONICAL_PRICES) == {
        ("plus", "USD"),
        ("pro", "USD"),
        ("plus", "MXN"),
        ("pro", "MXN"),
    }


def test_canonical_prices_are_the_launch_values():
    assert CANONICAL_PRICES[("plus", "USD")] == (500, 5_000)
    assert CANONICAL_PRICES[("pro", "USD")] == (1_500, 15_000)
    assert CANONICAL_PRICES[("plus", "MXN")] == (9_900, 99_000)
    assert CANONICAL_PRICES[("pro", "MXN")] == (19_900, 199_000)


def test_annual_is_ten_months_of_monthly():
    """Annual is advertised as '2 months free'. If someone changes one side
    of a pair and not the other, the marketing claim silently becomes false."""
    for (tier, currency), (monthly, annual) in CANONICAL_PRICES.items():
        assert annual == monthly * 10, f"{tier} {currency} breaks 2-months-free"


def test_price_minor_selects_the_cycle():
    assert price_minor("pro", "monthly", "MXN") == 19_900
    assert price_minor("pro", "annual", "MXN") == 199_000


def test_price_minor_rejects_unknown_inputs():
    with pytest.raises(KeyError):
        price_minor("enterprise", "monthly", "USD")
    with pytest.raises(ValueError):
        price_minor("pro", "weekly", "USD")


def test_price_decimal_str_is_paypal_shaped():
    assert price_decimal_str("plus", "monthly", "USD") == "5.00"
    assert price_decimal_str("pro", "annual", "MXN") == "1990.00"


def test_provisioning_script_prices_match_the_canonical_table():
    """setup_paypal_plans is what PayPal actually charges. If it drifts from
    the DB's display price, customers see one number and pay another."""
    from scripts.setup_paypal_plans import build_plan_definitions, plan_meta

    defs = build_plan_definitions("PROD-TEST")
    assert len(defs) == 8  # plus/pro x monthly/annual x USD/MXN

    seen = set()
    for plan_def in defs:
        tier, cycle, currency = plan_meta(plan_def)
        seen.add((tier, cycle, currency))
        regular = [
            c for c in plan_def["billing_cycles"] if c["tenure_type"] == "REGULAR"
        ][0]
        charged = regular["pricing_scheme"]["fixed_price"]
        assert charged["currency_code"] == currency
        assert charged["value"] == price_decimal_str(tier, cycle, currency)

    assert seen == {
        (tier, cycle, currency)
        for (tier, currency) in CANONICAL_PRICES
        for cycle in ("monthly", "annual")
    }


def test_provisioning_script_has_no_private_price_copy():
    """The whole point of Task 1 — the script must not carry its own table."""
    import scripts.setup_paypal_plans as mod

    assert not hasattr(mod, "PLAN_PRICES")
