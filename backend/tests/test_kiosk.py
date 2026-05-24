"""Kiosk device + snapshot tests (W3.3)."""

import pytest
from sqlalchemy import select

from app.models.kiosk_device import KioskDevice


class TestKioskDevice:
    async def test_token_unique_per_device(self, db_session, test_family):
        d1 = KioskDevice(family_id=test_family.id, name="A", token="tokenA" * 8)
        d2 = KioskDevice(family_id=test_family.id, name="B", token="tokenB" * 8)
        db_session.add_all([d1, d2])
        await db_session.commit()
        rows = (await db_session.execute(select(KioskDevice))).scalars().all()
        assert len({r.token for r in rows}) == len(rows)

    async def test_revoke_via_delete(self, db_session, test_family):
        d = KioskDevice(family_id=test_family.id, name="X", token="tokX" * 12)
        db_session.add(d)
        await db_session.commit()
        await db_session.delete(d)
        await db_session.commit()
        rows = (await db_session.execute(select(KioskDevice))).scalars().all()
        assert rows == []
