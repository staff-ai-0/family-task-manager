"""mandatory zero points + gig approval columns

Revision ID: gigs_v1_approval
Revises: seed_sub_plans_v1
Create Date: 2026-05-22

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "gigs_v1_approval"
down_revision = "seed_sub_plans_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. families.timezone
    op.add_column(
        "families",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE families SET timezone = 'UTC' WHERE timezone IS NULL")
    op.alter_column("families", "timezone", nullable=False, server_default="UTC")

    # 2. zero out mandatory template points
    op.execute("UPDATE task_templates SET points = 0 WHERE is_bonus = false")
    op.create_check_constraint(
        "chk_mandatory_zero_points",
        "task_templates",
        "is_bonus = true OR points = 0",
    )

    # 3. approval_status enum + columns on task_assignments
    approval_status = postgresql.ENUM(
        "none", "pending", "approved", "rejected",
        name="approval_status",
    )
    approval_status.create(bind, checkfirst=True)

    op.add_column(
        "task_assignments",
        sa.Column(
            "approval_status",
            sa.Enum("none", "pending", "approved", "rejected", name="approval_status", create_type=False),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column("task_assignments", sa.Column("proof_text", sa.Text(), nullable=True))
    op.add_column(
        "task_assignments",
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_assignments_approved_by_users",
        "task_assignments", "users",
        ["approved_by"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "task_assignments",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("task_assignments", sa.Column("approval_notes", sa.Text(), nullable=True))
    op.create_index(
        "idx_assignments_family_approval",
        "task_assignments",
        ["family_id", "approval_status"],
    )

    # 4. new transaction type value
    # NOTE: existing values use uppercase (TASK_COMPLETED, etc.) because the
    # SQLAlchemy column was declared without values_callable, so it sends the
    # Python enum NAME, not the value. Match that convention.
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'GIG_APPROVED'")

    # 5. seed default gig pack per existing family
    seed_default_gig_pack(bind)


def downgrade() -> None:
    op.drop_index("idx_assignments_family_approval", table_name="task_assignments")
    op.drop_constraint("fk_assignments_approved_by_users", "task_assignments", type_="foreignkey")
    op.drop_column("task_assignments", "approval_notes")
    op.drop_column("task_assignments", "approved_at")
    op.drop_column("task_assignments", "approved_by")
    op.drop_column("task_assignments", "proof_text")
    op.drop_column("task_assignments", "approval_status")

    bind = op.get_bind()
    sa.Enum(name="approval_status").drop(bind, checkfirst=True)

    op.drop_constraint("chk_mandatory_zero_points", "task_templates", type_="check")
    op.drop_column("families", "timezone")


DEFAULT_GIGS = [
    ("Learn a topic + writeup", "Pick something new (podman, git, a recipe). Read up, then write 5-10 sentences on what you learned.", 30),
    ("Read book chapter + discuss", "Read a chapter, then sit with a parent to discuss the main idea.", 20),
    ("Plan next 3 days of meals", "Propose breakfasts, lunches, and dinners for the next 3 days. List groceries needed.", 25),
    ("Help with grocery shopping", "Help compile the list, go to the store, and help carry/put away.", 15),
    ("Cook family dinner", "Plan, cook, and serve a family dinner with parent supervision.", 25),
    ("Tech-help parent (15 min)", "Help a parent with a phone/computer task for at least 15 minutes.", 10),
]


def seed_default_gig_pack(bind):
    family_ids = bind.execute(sa.text("SELECT id FROM families")).scalars().all()
    for family_id in family_ids:
        existing = bind.execute(
            sa.text(
                "SELECT title FROM task_templates "
                "WHERE family_id = :fid AND title = ANY(:titles)"
            ),
            {"fid": family_id, "titles": [t[0] for t in DEFAULT_GIGS]},
        ).scalars().all()
        existing_set = set(existing)
        for title, description, points in DEFAULT_GIGS:
            if title in existing_set:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO task_templates "
                    "(id, title, description, points, interval_days, assignment_type, "
                    " is_bonus, is_active, family_id, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :title, :desc, :points, 7, 'auto', "
                    " true, true, :fid, NOW(), NOW())"
                ),
                {"title": title, "desc": description, "points": points, "fid": family_id},
            )
