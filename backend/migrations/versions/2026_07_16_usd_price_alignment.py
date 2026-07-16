"""Align USD display prices with the provisioning script and market intel.

The 2026-05-22 seed set USD Plus at $4.99/$49 and Pro at $9.99/$99, but the
canonical prices everywhere else — scripts/setup_paypal_plans.py (what PayPal
would charge), seed_data.py, and the 2026-07-07 market intel — are
Plus $5/$50 and Pro $15/$150 (annual = 2 months free). No PayPal plan has
been provisioned against the old USD prices (paypal_plan_id_* are NULL), so
no subscriber has ever been charged them; this is a display-only correction.

MXN rows (MX$99/990, MX$199/1990) are already aligned and untouched.
Idempotent.

Revision ID: usd_price_alignment
Revises: plan_limit_feature_keys
"""
from alembic import op

revision = "usd_price_alignment"
down_revision = "plan_limit_feature_keys"
branch_labels = None
depends_on = None

# (name, monthly_cents, annual_cents)
USD_PRICES = [("plus", 500, 5000), ("pro", 1500, 15000)]
OLD_USD_PRICES = [("plus", 499, 4900), ("pro", 999, 9900)]


def _apply(prices) -> None:
    for name, monthly, annual in prices:
        op.execute(
            "UPDATE subscription_plans "
            f"SET price_monthly_cents = {monthly}, "
            f"    price_annual_cents = {annual}, "
            "    updated_at = now() "
            f"WHERE name = '{name}' AND currency = 'USD'"
        )


def upgrade() -> None:
    _apply(USD_PRICES)


def downgrade() -> None:
    _apply(OLD_USD_PRICES)
