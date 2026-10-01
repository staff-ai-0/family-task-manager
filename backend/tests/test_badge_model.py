"""UX-D2 user_badges table constraints."""
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.user_badge import UserBadge


def _row(kid, badge="chores", tier=1):
    return UserBadge(family_id=kid.family_id, user_id=kid.id, badge=badge, tier=tier,
                     earned_at=datetime.now(timezone.utc))


async def test_a_tier_can_only_be_earned_once(db_session, test_child_user):
    db_session.add(_row(test_child_user))
    await db_session.commit()
    db_session.add(_row(test_child_user))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_tier_must_be_one_to_three(db_session, test_child_user):
    db_session.add(_row(test_child_user, tier=4))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_new_rows_start_unseen(db_session, test_child_user):
    row = _row(test_child_user, badge="cup")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    assert row.seen_at is None and row.id is not None
