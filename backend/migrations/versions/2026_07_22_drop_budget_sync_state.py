"""Drop the dead budget_sync_state table.

Tracked synchronization state for the external "Actual Budget" sync engine,
decommissioned in Phase 10 (see CLAUDE.md — the external budget sync was
replaced by the native PostgreSQL budget system). Flagged as dead in the
2026-06-04 tech-debt audit (still open 7 weeks later); confirmed zero
service/route references at removal time — the only mentions were
family_export_service.py's export-exclusion list, describing it as "legacy
... with no user-authored content".

Revision ID: drop_budget_sync_state
Revises: cash_tx_week_of
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "drop_budget_sync_state"
down_revision = "cash_tx_week_of"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_budget_sync_state_family_id", "budget_sync_state")
    op.drop_table("budget_sync_state")


def downgrade() -> None:
    op.create_table(
        "budget_sync_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("last_sync_to_budget", sa.DateTime(timezone=True), nullable=True, comment="Last time points were synced to budget"),
        sa.Column("last_sync_from_budget", sa.DateTime(timezone=True), nullable=True, comment="Last time budget transactions were synced"),
        sa.Column("synced_point_transactions", postgresql.JSONB, nullable=False, server_default="{}", comment="Map of FTM transaction ID -> budget transaction ID"),
        sa.Column("synced_budget_transactions", postgresql.JSONB, nullable=False, server_default="{}", comment="Map of budget transaction ID -> FTM transaction ID"),
        sa.Column("sync_errors", postgresql.JSONB, nullable=False, server_default="[]", comment="Recent sync errors"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_budget_sync_state_family_id", "budget_sync_state", ["family_id"])
