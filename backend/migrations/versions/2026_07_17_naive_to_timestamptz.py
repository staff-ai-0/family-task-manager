"""Convert the last naive timestamp columns to timestamptz.

Companion to the aware-defaults sweep: these 14 columns (5 tables) still
stored naive wall-clock values. Every historical writer used UTC wall time
(datetime.utcnow or now(utc).replace(tzinfo=None)), so reinterpreting the
stored values AT TIME ZONE 'UTC' is lossless.

Revision ID: naive_to_timestamptz
Revises: drop_legacy_tasks
"""
from alembic import op

revision = "naive_to_timestamptz"
down_revision = "drop_legacy_tasks"
branch_labels = None
depends_on = None

# (table, column) — every remaining TIMESTAMP WITHOUT TIME ZONE with app writes
_COLUMNS = [
    ("users", "created_at"),
    ("users", "updated_at"),
    ("users", "email_verified_at"),
    ("users", "consented_at"),
    ("users", "approved_at"),
    ("families", "created_at"),
    ("families", "updated_at"),
    ("families", "ai_processing_consent_at"),
    ("family_invitations", "created_at"),
    ("family_invitations", "expires_at"),
    ("family_invitations", "accepted_at"),
    ("password_reset_tokens", "created_at"),
    ("password_reset_tokens", "expires_at"),
    ("onboarding_events", "created_at"),
]


def upgrade() -> None:
    for table, col in _COLUMNS:
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {col} '
            f"TYPE TIMESTAMPTZ USING {col} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for table, col in _COLUMNS:
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {col} '
            f"TYPE TIMESTAMP USING {col} AT TIME ZONE 'UTC'"
        )
