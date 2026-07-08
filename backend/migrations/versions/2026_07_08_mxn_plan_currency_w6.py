"""P1-W6 MXN-denominated pricing

subscription_plans:
- currency (varchar(3), NOT NULL, default 'USD'): ISO 4217 code the
  price_monthly_cents / price_annual_cents columns are denominated in.
  Existing rows are backfilled as USD via the server_default.
- The single-column UNIQUE(name) is replaced by UNIQUE(name, currency) so a
  tier (plus/pro) can coexist in several currencies. Premium gating resolves
  entitlements by plan *name*, so duplicated tier names across currencies are
  currency-agnostic by construction. A plain (non-unique) index on name keeps
  lookups fast.

Seeds MXN rows for the paid tiers (Mexico-first pricing, per the 2026-07-07
competitor intel: nobody publishes MXN pricing):
- plus: MX$99.00/mo, MX$990.00/yr  (9900 / 99000 centavos)
- pro:  MX$199.00/mo, MX$1990.00/yr (19900 / 199000 centavos)

Limits are copied verbatim from the tier's existing USD row so both currency
rows always grant identical entitlements. PayPal plan ids are left NULL and
the rows are seeded **is_active = false**: an MXN row nobody can check out
(501 'PayPal plan not configured') must never be listed or resolved while
the operator has not yet provisioned MXN plans at PayPal. The operator runs
scripts/setup_paypal_plans.py and applies its printed SQL UPDATEs, which
wire the paypal_plan_id_* columns AND flip is_active = true in one step.
Until then the USD rows keep serving checkouts exactly as before this
migration. The free tier stays a single (currency-less in practice) row and
is always included in currency-filtered plan listings.

Revision ID: mxn_plan_currency_w6
Revises: task_mechanics_w4
Create Date: 2026-07-08

"""
from alembic import op
import sqlalchemy as sa


revision = 'mxn_plan_currency_w6'
down_revision = 'task_mechanics_w4'
branch_labels = None
depends_on = None


# Editable price constants (minor units — centavos).
MXN_PRICES = {
    "plus": {"monthly": 9900, "annual": 99000},   # MX$99 / MX$990
    "pro": {"monthly": 19900, "annual": 199000},  # MX$199 / MX$1990
}


# Seeded INACTIVE (is_active = false): the PayPal plan ids are NULL until the
# operator provisions MXN plans (scripts/setup_paypal_plans.py), whose printed
# wiring SQL sets the ids and activates the row. An active-but-unwired row
# would be listed on the pricing page and picked by checkout's MXN-first
# default, turning every plus/pro upgrade into a 501 for the whole
# deploy-to-provisioning window. ON CONFLICT deliberately does NOT touch
# is_active or the paypal ids, so re-running the migration never deactivates
# or unwires rows the operator already activated.
SEED_MXN_SQL = sa.text(
    """
    INSERT INTO subscription_plans
        (id, name, display_name, display_name_es, currency,
         price_monthly_cents, price_annual_cents,
         limits, is_active, sort_order)
    SELECT
        gen_random_uuid(), usd.name, usd.display_name, usd.display_name_es,
        'MXN', :monthly, :annual, usd.limits, false, usd.sort_order
    FROM subscription_plans usd
    WHERE usd.name = :name AND usd.currency = 'USD'
    ON CONFLICT (name, currency) DO UPDATE SET
        price_monthly_cents = EXCLUDED.price_monthly_cents,
        price_annual_cents  = EXCLUDED.price_annual_cents,
        limits              = EXCLUDED.limits,
        sort_order          = EXCLUDED.sort_order,
        updated_at          = now()
    """
)


def upgrade() -> None:
    # 1. currency column — server_default backfills every existing row as USD.
    op.add_column(
        "subscription_plans",
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
    )

    # 2. UNIQUE(name) → UNIQUE(name, currency) + plain index on name.
    op.drop_constraint("subscription_plans_name_key", "subscription_plans", type_="unique")
    op.create_unique_constraint(
        "uq_subscription_plans_name_currency",
        "subscription_plans",
        ["name", "currency"],
    )
    op.create_index(
        "ix_subscription_plans_name", "subscription_plans", ["name"], unique=False
    )

    # 3. Seed MXN rows for the paid tiers, cloning limits from the USD row.
    conn = op.get_bind()
    for name, prices in MXN_PRICES.items():
        conn.execute(
            SEED_MXN_SQL,
            {"name": name, "monthly": prices["monthly"], "annual": prices["annual"]},
        )


def downgrade() -> None:
    # Remove MXN rows so UNIQUE(name) can be restored. Blocked (RESTRICT FK)
    # if a family ever subscribed to an MXN plan — that is deliberate: those
    # subscriptions must be migrated by hand before downgrading.
    op.execute(
        "UPDATE family_subscriptions SET pending_plan_id = NULL "
        "WHERE pending_plan_id IN "
        "(SELECT id FROM subscription_plans WHERE currency <> 'USD')"
    )
    op.execute("DELETE FROM subscription_plans WHERE currency <> 'USD'")
    op.drop_index("ix_subscription_plans_name", table_name="subscription_plans")
    op.drop_constraint(
        "uq_subscription_plans_name_currency", "subscription_plans", type_="unique"
    )
    op.create_unique_constraint(
        "subscription_plans_name_key", "subscription_plans", ["name"]
    )
    op.drop_column("subscription_plans", "currency")
