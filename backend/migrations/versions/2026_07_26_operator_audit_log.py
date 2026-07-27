"""Create operator_audit_log — append-only trail of platform-operator actions.

No foreign keys by design: the row must survive the purge of the family and
the deletion of the operator account it describes.

Revision ID: operator_audit_log
Revises: superadmin_flag
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "operator_audit_log"
down_revision = "superadmin_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_audit_log",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_family_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column(
            "result", sa.String(length=16), nullable=False, server_default="ok"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_operator_audit_log_action", "operator_audit_log", ["action"]
    )
    op.create_index(
        "ix_operator_audit_log_target_family_id",
        "operator_audit_log",
        ["target_family_id"],
    )
    op.create_index(
        "ix_operator_audit_log_created_at", "operator_audit_log", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_operator_audit_log_created_at", "operator_audit_log")
    op.drop_index("ix_operator_audit_log_target_family_id", "operator_audit_log")
    op.drop_index("ix_operator_audit_log_action", "operator_audit_log")
    op.drop_table("operator_audit_log")
