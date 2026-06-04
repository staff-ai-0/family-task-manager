"""rename frankie -> jarvis (tables, indexes, check constraints)

Renames the AI-assistant tables created by frankie_v1 / frankie_sch_v1 to the
new "jarvis" brand. Pure metadata operations in Postgres (ALTER ... RENAME) —
fast, lock-light, fully data-preserving. No row rewrites.

NOTE: the historical migrations (frankie_v1, frankie_sch_v1) are left untouched
on purpose — they record the schema as it existed at that point. This migration
carries the rename forward.

Revision ID: jarvis_rename_v1
Revises: gig_tables
Create Date: 2026-06-04
"""
from alembic import op


revision = "jarvis_rename_v1"
down_revision = "gig_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("frankie_messages", "jarvis_messages")
    op.rename_table("frankie_schedules", "jarvis_schedules")
    op.execute(
        "ALTER INDEX IF EXISTS ix_frankie_family_created "
        "RENAME TO ix_jarvis_family_created"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_frankie_sched_active_next "
        "RENAME TO ix_jarvis_sched_active_next"
    )
    op.execute(
        "ALTER TABLE jarvis_messages "
        "RENAME CONSTRAINT chk_frankie_role TO chk_jarvis_role"
    )
    op.execute(
        "ALTER TABLE jarvis_schedules "
        "RENAME CONSTRAINT chk_frankie_channel TO chk_jarvis_channel"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE jarvis_schedules "
        "RENAME CONSTRAINT chk_jarvis_channel TO chk_frankie_channel"
    )
    op.execute(
        "ALTER TABLE jarvis_messages "
        "RENAME CONSTRAINT chk_jarvis_role TO chk_frankie_role"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_jarvis_sched_active_next "
        "RENAME TO ix_frankie_sched_active_next"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_jarvis_family_created "
        "RENAME TO ix_frankie_family_created"
    )
    op.rename_table("jarvis_schedules", "frankie_schedules")
    op.rename_table("jarvis_messages", "frankie_messages")
