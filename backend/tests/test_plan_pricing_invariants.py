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
