"""Canonical subscription plan prices — the single source of truth.

Prices are stored and compared in the currency's MINOR unit (US cents,
MXN centavos), matching subscription_plans.price_*_cents.

History: these values used to live in three hand-synced copies (the
provisioning script, two alembic migrations, and a frontend fallback
constant). On 2026-07-16 prod's rows were overwritten with 0 out of band and
nothing noticed for two weeks — the pricing page advertised "$0/mes" and
checkout 501'd. Every consumer now derives from this table:

- backend/scripts/setup_paypal_plans.py  (what PayPal is told to charge)
- backend/migrations/versions/2026_07_31_restore_plan_prices.py
  (a FROZEN copy — migrations must not import app code, which moves under
  them; test_plan_pricing_invariants asserts the copy has not drifted)
- app/main.py startup audit, the operator console panel, and the deploy
  smoke check — all via audit_plan_rows() below.

The frontend deliberately has NO copy: a missing plan row renders "—" and
disables checkout rather than printing a price the backend never confirmed.
"""

# (tier, currency) -> (monthly_minor_units, annual_minor_units).
# Annual is exactly 10x monthly — "2 months free" is a marketing promise the
# invariant test enforces.
CANONICAL_PRICES: dict[tuple[str, str], tuple[int, int]] = {
    ("plus", "USD"): (500, 5_000),
    ("pro", "USD"): (1_500, 15_000),
    ("plus", "MXN"): (9_900, 99_000),
    ("pro", "MXN"): (19_900, 199_000),
}

_CYCLE_INDEX = {"monthly": 0, "annual": 1}


def price_minor(tier: str, cycle: str, currency: str) -> int:
    """Canonical price in minor units. Raises on an unknown tier/currency
    (KeyError) or an unknown billing cycle (ValueError)."""
    if cycle not in _CYCLE_INDEX:
        raise ValueError(f"Unknown billing cycle: {cycle!r}")
    return CANONICAL_PRICES[(tier, currency)][_CYCLE_INDEX[cycle]]


def price_decimal_str(tier: str, cycle: str, currency: str) -> str:
    """Canonical price as the decimal string PayPal's Billing API expects."""
    return f"{price_minor(tier, cycle, currency) / 100:.2f}"
