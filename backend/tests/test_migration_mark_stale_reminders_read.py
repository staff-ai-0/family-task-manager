"""The mark_stale_reminders_read data migration, exercised against real rows.

Alembic itself is covered by CI's upgrade/round-trip job; this pins the
UPDATE's semantics by running the migration's own SQL on seeded data.
"""
import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select, text, update

from app.models.notification import Notification, NotificationType as NT

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "2026_09_27_mark_stale_reminders_read.py"
)


def _migration_sql() -> str:
    spec = importlib.util.spec_from_file_location("mark_stale_reminders_read", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    captured: list[str] = []
    mod.op = SimpleNamespace(execute=lambda sql: captured.append(str(sql)))
    mod.upgrade()
    assert len(captured) == 1
    return captured[0]


def test_revision_chain():
    spec = importlib.util.spec_from_file_location("m", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "mark_stale_reminders_read"
    assert mod.down_revision == "jarvis_message_mode"


async def test_marks_only_old_unread_reminders_read(db_session, test_family, test_child_user):
    now = datetime.now(timezone.utc)
    rows = {
        "old_due": (NT.TASK_DUE, 3, True),
        "new_due": (NT.TASK_DUE, 1, False),
        "old_assigned": (NT.TASK_ASSIGNED, 5, True),
        "old_gig": (NT.GIG_APPROVED, 10, False),
    }
    ids = {}
    for title, (type_, age_days, _) in rows.items():
        n = Notification(
            family_id=test_family.id, user_id=test_child_user.id,
            type=type_, title=title,
        )
        db_session.add(n)
        await db_session.flush()
        await db_session.execute(
            update(Notification).where(Notification.id == n.id)
            .values(created_at=now - timedelta(days=age_days))
        )
        ids[title] = n.id
    await db_session.commit()

    await db_session.execute(text(_migration_sql()))
    await db_session.commit()

    for title, (_, _, should_be_read) in rows.items():
        is_read = (await db_session.execute(
            select(Notification.is_read).where(Notification.id == ids[title])
        )).scalar_one()
        assert bool(is_read) is should_be_read, title
