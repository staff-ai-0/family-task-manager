"""chore_rules_v2 — cutoff, grab window, teen alarms, rules_version

Revision ID: chore_rules_v2
Revises: early_bird_past_periods
Create Date: 2026-11-12

Existing families keep every current value: the new columns take their
server defaults, and `early_bird_streak_cents` is NOT touched (the new 38000
default lives only in the Python model, for newly created families).
"""
import sqlalchemy as sa
from alembic import op

revision = "chore_rules_v2"
down_revision = "early_bird_past_periods"
branch_labels = None
depends_on = None

_TIMES = (
    ("chore_cutoff", "20:30"),
    ("grab_window_end", "22:30"),
    ("teen_alarm_1", "15:00"),
    ("teen_alarm_2", "19:00"),
)


def upgrade() -> None:
    for name, default in _TIMES:
        op.add_column(
            "families",
            sa.Column(name, sa.Time(), nullable=False, server_default=default),
        )
    op.add_column(
        "families",
        sa.Column("rules_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("families", "rules_version")
    for name, _ in reversed(_TIMES):
        op.drop_column("families", name)
