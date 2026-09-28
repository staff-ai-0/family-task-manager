"""Mark stale chore reminders read (UX-A, 2026-09-27)

task_due ("You have N chores today") and task_assigned ("You have N new
chores") are superseded by the next reminder of the same type — from this
release NotificationService marks older unread ones read when a new one is
created. This clears the backlog from before that rule: prod had 664 such
unread rows out of 958, which kept every user's badge at 75–214.

Data only; no schema change. The reverse step is a no-op: read state is not
restorable and nothing depends on it.

Revision ID: mark_stale_reminders_read
Revises: jarvis_message_mode
Create Date: 2026-09-27
"""
from alembic import op

revision = "mark_stale_reminders_read"
down_revision = "jarvis_message_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE notifications
           SET is_read = true, read_at = now()
         WHERE is_read = false
           AND type IN ('task_due', 'task_assigned')
           AND created_at < now() - interval '2 days'
        """
    )


def downgrade() -> None:
    # Irreversible data cleanup — see module docstring.
    pass
