"""remove_evening_release

Revision ID: remove_evening_release
Revises: chore_baselines
Create Date: 2026-11-25

Data only. The evening cutoff and "up for grabs" were removed: a chore stays
its owner's until midnight. The rules every member accepted have changed, so
every family's rules_version moves up one and each member is asked to read
and accept them again (families.chore_cutoff / grab_window_end stay in the
table, read by nothing).
"""
from alembic import op

revision = "remove_evening_release"
down_revision = "chore_baselines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE families SET rules_version = rules_version + 1")


def downgrade() -> None:
    # Back to the version the old rules were accepted under. Never below 1:
    # a family created after the upgrade already starts there.
    op.execute("UPDATE families SET rules_version = GREATEST(1, rules_version - 1)")
