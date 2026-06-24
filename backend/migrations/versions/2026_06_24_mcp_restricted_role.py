"""Create restricted jarvis_mcp DB role for external /mcp sessions

Revision ID: mcp_restricted_role
Revises: jarvis_mcp_token
Create Date: 2026-06-24

## Overview

Creates the ``jarvis_mcp`` PostgreSQL role used by the external HTTP transport
(``/mcp``).  The role:

- Has ``NOLOGIN`` (never used as a direct connection credential).
- Is assumed via ``SET ROLE jarvis_mcp`` inside a session opened by the app
  role (``familyapp``), which requires a ``GRANT jarvis_mcp TO familyapp``.
- Holds **SELECT, INSERT, UPDATE, DELETE** on activity-domain tables only.
- Explicitly has **NO** grants on auth/billing/PII tables (``users``,
  ``families``, ``family_invitations``, ``family_subscriptions``,
  ``subscription_plans``, ``usage_tracking``, ``email_verification_tokens``,
  ``password_reset_tokens``, ``push_subscriptions``, ``kiosk_devices``).

## Activity-domain tables granted

    budget_accounts, budget_allocations, budget_categories,
    budget_categorization_rules, budget_category_groups, budget_custom_reports,
    budget_goals, budget_payees, budget_receipt_drafts,
    budget_recurring_transactions, budget_saved_filters, budget_tags,
    budget_transaction_items, budget_transaction_tags, budget_transactions,
    calendar_events, consequences, dm_messages, dm_threads,
    family_chat_messages, family_chat_reactions,
    gig_claims, gig_offerings,
    jarvis_messages, jarvis_pending_actions, jarvis_schedules,
    kid_pets, meal_plan_entries, notifications,
    point_transactions, pup_score_snapshots,
    recipes, rewards, shopping_items, shopping_lists,
    task_assignments, task_templates, tasks,
    user_reward_goals,
    a2a_webhook_deliveries, family_a2a_webhooks,
    budget_sync_state, onboarding_events

## Excluded tables (no grants)

    users, families, family_invitations, family_subscriptions,
    subscription_plans, usage_tracking,
    email_verification_tokens, password_reset_tokens,
    push_subscriptions, kiosk_devices,
    jarvis_mcp_tokens   ← only used for auth lookup on a SEPARATE session

## Production apply

After running ``alembic upgrade head`` on the production DB:

    GRANT jarvis_mcp TO familyapp;

This line is NOT in the migration because it requires knowing the exact name of
the app role in each environment (``familyapp`` in prod, may vary in CI).  Add
it to the post-deploy checklist or run it once manually.

Then set ``JARVIS_MCP_DB_ROLE=jarvis_mcp`` in the production ``.env``.

## Test environment

The test DB is built by SQLAlchemy ``create_all`` (not Alembic), so this
migration does NOT run there.  The live role tests in
``tests/mcp/test_restricted_role.py`` are skipped unless ``JARVIS_MCP_DB_ROLE``
is set.  To enable them locally: create the role in the test DB manually and
set the env var before running pytest.
"""

from alembic import op
import sqlalchemy as sa

revision = "mcp_restricted_role"
down_revision = "jarvis_mcp_token"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Tables granted to jarvis_mcp (activity/data domain only)
# ---------------------------------------------------------------------------

_GRANTED_TABLES = [
    # Budget
    "budget_accounts",
    "budget_allocations",
    "budget_categories",
    "budget_categorization_rules",
    "budget_category_groups",
    "budget_custom_reports",
    "budget_goals",
    "budget_payees",
    "budget_receipt_drafts",
    "budget_recurring_transactions",
    "budget_saved_filters",
    "budget_sync_state",
    "budget_tags",
    "budget_transaction_items",
    "budget_transaction_tags",
    "budget_transactions",
    # Calendar
    "calendar_events",
    # Consequences
    "consequences",
    # Chat / DM
    "dm_messages",
    "dm_threads",
    "family_chat_messages",
    "family_chat_reactions",
    # Gigs
    "gig_claims",
    "gig_offerings",
    # Jarvis (messages + schedules + pending actions only; NOT tokens)
    "jarvis_messages",
    "jarvis_pending_actions",
    "jarvis_schedules",
    # Pet
    "kid_pets",
    # Meals
    "meal_plan_entries",
    "recipes",
    # Notifications
    "notifications",
    # Points / analytics
    "onboarding_events",
    "point_transactions",
    "pup_score_snapshots",
    # Rewards
    "rewards",
    "user_reward_goals",
    # Shopping
    "shopping_items",
    "shopping_lists",
    # Tasks
    "task_assignments",
    "task_templates",
    "tasks",
    # Webhooks (activity logging only)
    "a2a_webhook_deliveries",
    "family_a2a_webhooks",
]

# ---------------------------------------------------------------------------
# Tables deliberately NOT granted (PII / auth / billing / secrets)
# ---------------------------------------------------------------------------
#
#   users                       — PII + password hashes
#   families                    — tenant root (family_id comes from the token)
#   family_invitations          — auth flow
#   family_subscriptions        — billing
#   subscription_plans          — billing catalogue
#   usage_tracking              — billing metering
#   email_verification_tokens   — auth secrets
#   password_reset_tokens       — auth secrets
#   push_subscriptions          — device tokens
#   kiosk_devices               — device secrets
#   jarvis_mcp_tokens           — bearer secrets (only used during auth, on a
#                                  separate pre-SET-ROLE session)


def upgrade() -> None:
    # Use raw SQL via execute_if so the migration is skipped on non-PG dialects
    # (e.g. SQLite used in some CI) without erroring out.
    conn = op.get_bind()

    # Create the role (idempotent: DO $$ block avoids error if it already exists)
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_mcp') THEN "
            "    CREATE ROLE jarvis_mcp NOLOGIN; "
            "  END IF; "
            "END $$"
        )
    )

    # Revoke all first (idempotent re-runs: start clean)
    conn.execute(sa.text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM jarvis_mcp"))

    # Grant CRUD on activity tables
    for table in _GRANTED_TABLES:
        conn.execute(
            sa.text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO jarvis_mcp"
            )
        )

    # Grant USAGE on the public schema so the role can see the tables
    conn.execute(sa.text("GRANT USAGE ON SCHEMA public TO jarvis_mcp"))

    # Grant sequences (needed for INSERT on tables with serial / UUID defaults
    # that use a sequence, e.g. some legacy integer PKs)
    conn.execute(
        sa.text(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO jarvis_mcp"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM jarvis_mcp"))
    conn.execute(
        sa.text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM jarvis_mcp")
    )
    conn.execute(sa.text("REVOKE USAGE ON SCHEMA public FROM jarvis_mcp"))
    conn.execute(
        sa.text(
            "DO $$ BEGIN "
            "  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_mcp') THEN "
            "    DROP ROLE jarvis_mcp; "
            "  END IF; "
            "END $$"
        )
    )
