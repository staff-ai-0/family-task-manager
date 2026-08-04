"""Restore subscription plan prices after an out-of-band zeroing.

On 2026-07-31 production held price_monthly_cents = price_annual_cents = 0
for all four paid rows (plus/pro x USD/MXN). This was NOT a missing
migration: prod's head was downstream of both usd_price_alignment and
mxn_plan_currency_w6, all four rows shared updated_at
2026-07-16 17:30:11.67115+00 (one transaction, consistent with that upgrade
run), and no migration in the chain ever writes a 0. The rows were
overwritten out of band afterwards.

Since resolved (2026-08-03): that write was a DELIBERATE, operator-requested
"test mode" on 2026-07-16, disabling checkout by zeroing the prices. It was
never recorded in-repo, which is why this migration was written as a
forensic reconstruction of an unexplained event. It is not corruption — but
the remedy stands, and so does the rule it produced: never zero prices to
switch selling off. Every guard now fires on a zero (CI invariants, the
startup audit, GET /api/admin/billing-config, and the deploy gate, which
exits non-zero). The sanctioned off switch is is_active=false on the rows.

The UPDATE is ABSOLUTE and idempotent — re-running always converges on the
canonical values, whatever the row currently holds.

FROZEN_PRICES is a deliberate literal copy of app.core.plan_pricing's
CANONICAL_PRICES. Migrations must not import app code (it evolves under
already-applied revisions), so the copy is frozen here and
tests/test_plan_pricing_invariants.py asserts it has not drifted.

Deliberately does NOT touch is_active or paypal_plan_id_* — those are
provisioning state owned by scripts/setup_paypal_plans.py, and a migration
fighting the operator over them is how the MXN rows ended up active and
unwired.

Revision ID: restore_plan_prices
Revises: user_completed_tours
Create Date: 2026-07-31
"""
from alembic import op

revision = "restore_plan_prices"
down_revision = "user_completed_tours"
branch_labels = None
depends_on = None


# FROZEN copy of app.core.plan_pricing.CANONICAL_PRICES.
# (tier, currency) -> (monthly_minor_units, annual_minor_units)
FROZEN_PRICES = {
    ("plus", "USD"): (500, 5_000),
    ("pro", "USD"): (1_500, 15_000),
    ("plus", "MXN"): (9_900, 99_000),
    ("pro", "MXN"): (19_900, 199_000),
}


def upgrade() -> None:
    conn = op.get_bind()
    from sqlalchemy import text

    stmt = text(
        "UPDATE subscription_plans "
        "SET price_monthly_cents = :monthly, "
        "    price_annual_cents = :annual, "
        "    updated_at = now() "
        "WHERE name = :name AND currency = :currency"
    )
    for (name, currency), (monthly, annual) in FROZEN_PRICES.items():
        conn.execute(
            stmt,
            {
                "name": name,
                "currency": currency,
                "monthly": monthly,
                "annual": annual,
            },
        )


def downgrade() -> None:
    """No-op, deliberately.

    Prices are display data with exactly one correct value; there is no
    earlier state worth restoring, and reverting to 0 would recreate the
    outage this revision fixes. CI runs upgrade -> downgrade -1 -> upgrade,
    which is safe: the following upgrade re-asserts the same values.
    """
