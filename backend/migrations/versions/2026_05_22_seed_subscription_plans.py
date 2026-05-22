"""seed subscription plans (free / plus / pro)

Idempotent — uses ON CONFLICT(name) DO UPDATE so re-running keeps prices
and limits in sync with this migration. PayPal plan IDs are left NULL;
fill them in via UPDATE once the PayPal billing dashboard returns the
provisioned IDs (or via the subscription admin route).

Revision ID: seed_sub_plans_v1
Revises: paypal_v1_flags
Create Date: 2026-05-22
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "seed_sub_plans_v1"
down_revision = "paypal_v1_flags"
branch_labels = None
depends_on = None


# Mirrors app.core.premium.DEFAULT_FREE_LIMITS. Keep in sync if either changes.
FREE_LIMITS = {
    "max_family_members": 4,
    "max_budget_accounts": 2,
    "max_budget_transactions_per_month": 30,
    "max_recurring_transactions": 0,
    "budget_reports": False,
    "budget_goals": False,
    "csv_import": False,
    "max_receipt_scans_per_month": 0,
    "ai_features": False,
}

# Plus tier: unlocks every premium feature, generous metered caps.
# -1 = unlimited (interpreted by premium.require_feature).
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

# Pro tier: truly unlimited everything.
PRO_LIMITS = {
    "max_family_members": -1,
    "max_budget_accounts": -1,
    "max_budget_transactions_per_month": -1,
    "max_recurring_transactions": -1,
    "budget_reports": True,
    "budget_goals": True,
    "csv_import": True,
    "max_receipt_scans_per_month": -1,
    "ai_features": True,
}


PLANS = [
    {
        "name": "free",
        "display_name": "Free",
        "display_name_es": "Gratis",
        "price_monthly_cents": 0,
        "price_annual_cents": 0,
        "limits": FREE_LIMITS,
        "sort_order": 0,
    },
    {
        "name": "plus",
        "display_name": "Plus",
        "display_name_es": "Plus",
        "price_monthly_cents": 499,
        "price_annual_cents": 4900,
        "limits": PLUS_LIMITS,
        "sort_order": 10,
    },
    {
        "name": "pro",
        "display_name": "Pro",
        "display_name_es": "Pro",
        "price_monthly_cents": 999,
        "price_annual_cents": 9900,
        "limits": PRO_LIMITS,
        "sort_order": 20,
    },
]


UPSERT_SQL = sa.text(
    """
    INSERT INTO subscription_plans
        (id, name, display_name, display_name_es,
         price_monthly_cents, price_annual_cents,
         limits, is_active, sort_order)
    VALUES
        (gen_random_uuid(), :name, :display_name, :display_name_es,
         :price_monthly_cents, :price_annual_cents,
         CAST(:limits AS jsonb), true, :sort_order)
    ON CONFLICT (name) DO UPDATE SET
        display_name         = EXCLUDED.display_name,
        display_name_es      = EXCLUDED.display_name_es,
        price_monthly_cents  = EXCLUDED.price_monthly_cents,
        price_annual_cents   = EXCLUDED.price_annual_cents,
        limits               = EXCLUDED.limits,
        sort_order           = EXCLUDED.sort_order,
        is_active            = true,
        updated_at           = now()
    """
)


def upgrade() -> None:
    conn = op.get_bind()
    for plan in PLANS:
        conn.execute(
            UPSERT_SQL,
            {
                "name": plan["name"],
                "display_name": plan["display_name"],
                "display_name_es": plan["display_name_es"],
                "price_monthly_cents": plan["price_monthly_cents"],
                "price_annual_cents": plan["price_annual_cents"],
                "limits": json.dumps(plan["limits"]),
                "sort_order": plan["sort_order"],
            },
        )


def downgrade() -> None:
    # Leave families that have already subscribed to these plans untouched;
    # only deactivate so they stop appearing on the pricing page.
    op.execute(
        "UPDATE subscription_plans "
        "SET is_active = false, updated_at = now() "
        "WHERE name IN ('free', 'plus', 'pro')"
    )
