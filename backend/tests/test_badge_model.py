"""UX-D2 user_badges table constraints."""
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.family import Family
from app.models.user_badge import UserBadge


def _row(kid, badge="chores", tier=1, family_id=None):
    return UserBadge(family_id=family_id or kid.family_id, user_id=kid.id, badge=badge, tier=tier,
                     earned_at=datetime.now(timezone.utc))


async def test_a_tier_can_only_be_earned_once(db_session, test_child_user):
    db_session.add(_row(test_child_user))
    await db_session.commit()
    db_session.add(_row(test_child_user))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_the_same_tier_can_be_held_again_in_another_family(db_session, test_child_user):
    # A kid account can be moved to another family (invitation_service); the
    # old family's rows are invisible there, so they must not block the tier.
    other = Family(name="Other")
    db_session.add(other)
    await db_session.commit()
    db_session.add(_row(test_child_user))
    await db_session.commit()
    db_session.add(_row(test_child_user, family_id=other.id))
    await db_session.commit()


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
