"""L1: FamilyChatService.list_messages resolved the before_id pagination
anchor without a family_id filter, so a caller could pass a foreign family's
message id and have its timestamp used as the cutoff — an existence/timing
oracle. The anchor lookup must be family-scoped."""
from datetime import datetime, timedelta

import pytest

from app.models.family import Family
from app.models.user import User, UserRole
from app.models.family_chat import FamilyChatMessage
from app.services.family_chat_service import FamilyChatService


@pytest.mark.asyncio
async def test_foreign_before_id_anchor_is_ignored(
    db_session, test_family, test_parent_user
):
    base = datetime(2026, 1, 1, 12, 0, 0)

    # Second family with one OLD message.
    other = Family(name="Other Fam")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_user = User(
        email="other@test.com",
        password_hash="x",
        name="Other",
        role=UserRole.PARENT,
        family_id=other.id,
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    foreign_msg = FamilyChatMessage(
        family_id=other.id,
        sender_id=other_user.id,
        body="foreign",
        created_at=base,  # oldest of all
    )
    db_session.add(foreign_msg)

    # Our family has 3 NEWER messages.
    for i in range(1, 4):
        db_session.add(
            FamilyChatMessage(
                family_id=test_family.id,
                sender_id=test_parent_user.id,
                body=f"ours-{i}",
                created_at=base + timedelta(minutes=i),
            )
        )
    await db_session.commit()
    await db_session.refresh(foreign_msg)

    # A foreign anchor must NOT scope our results to "older than the foreign
    # message" (which would leak its timing). It should be ignored entirely.
    rows = await FamilyChatService.list_messages(
        db_session, family_id=test_family.id, before_id=foreign_msg.id
    )
    assert len(rows) == 3, "foreign before_id must be ignored, not used as cutoff"
