"""Backfill scanner-v2 feature keys into plus/pro plan limits.

The 2026-05-28 scanner-v2 wave introduced a2a_webhook / item_trends /
fx_cross_charge in FEATURE_MIN_PLAN but never patched the seeded plan rows,
so ``require_feature`` (which reads the limits dict, falling back to
DEFAULT_FREE_LIMITS) resolved them to False for every tier — including
paid ones. Now that the a2a-webhook config endpoint enforces
``require_feature("a2a_webhook")``, paid rows must carry the keys.

Per FEATURE_MIN_PLAN: a2a_webhook + item_trends unlock at plus;
fx_cross_charge at pro. Idempotent (jsonb_set overwrites in place).

Revision ID: plan_limit_feature_keys
Revises: gig_allow_multiple
"""
from alembic import op

revision = "plan_limit_feature_keys"
down_revision = "gig_allow_multiple"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE subscription_plans SET limits = "
        "jsonb_set(jsonb_set("
        "  COALESCE(limits, '{}'::jsonb),"
        "  '{a2a_webhook}', 'true'::jsonb, true),"
        "  '{item_trends}', 'true'::jsonb, true), "
        "updated_at = now() "
        "WHERE name IN ('plus', 'pro')"
    )
    op.execute(
        "UPDATE subscription_plans SET limits = "
        "jsonb_set(COALESCE(limits, '{}'::jsonb),"
        "  '{fx_cross_charge}', 'true'::jsonb, true), "
        "updated_at = now() "
        "WHERE name = 'pro'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE subscription_plans SET limits = "
        "(COALESCE(limits, '{}'::jsonb) - 'a2a_webhook' - 'item_trends'), "
        "updated_at = now() "
        "WHERE name IN ('plus', 'pro')"
    )
    op.execute(
        "UPDATE subscription_plans SET limits = "
        "(COALESCE(limits, '{}'::jsonb) - 'fx_cross_charge'), "
        "updated_at = now() "
        "WHERE name = 'pro'"
    )
