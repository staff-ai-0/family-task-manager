"""Monthly show-and-tell nudge: once per family-local month, parents only,
only when a proof chore lacks a fresh baseline and AI review is available.
The notification row is the only dedupe record."""
import ast
import pathlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.chore_baseline import ChoreBaseline
from app.models.family import Family
from app.models.notification import Notification, NotificationType as NT
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.services.ping_service import PingService

UTC = ZoneInfo("UTC")


def _now(hour=12, tz=UTC, month_offset=0):
    """Day 15 of the real current month (+offset), at local `hour` in tz, so
    the rows' real created_at always sits in the same local month."""
    real = datetime.now(tz)
    m = real.month - 1 + month_offset
    return datetime(real.year + m // 12, m % 12 + 1, 15, hour, 0, tzinfo=tz)


async def _family(db, tz="UTC", consent=True, name="F"):
    f = Family(name=name, timezone=tz, ai_processing_consent=consent)
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return f


async def _user(db, family, role=UserRole.PARENT, lang="en", **kw):
    u = User(email=f"{uuid4().hex[:8]}@test.com", password_hash=get_password_hash("x"),
             name="U", role=role, family_id=family.id, email_verified=True, points=0,
             preferred_lang=lang, **kw)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _template(db, family, proof=True):
    t = TaskTemplate(title="Make bed", family_id=family.id, requires_proof=proof, is_active=True, points=5)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _rows(db, family=None):
    q = select(Notification).where(Notification.type == NT.SHOW_AND_TELL)
    if family is not None:
        q = q.where(Notification.family_id == family.id)
    return list((await db.execute(q)).scalars().all())


@pytest.fixture
def paid():
    with patch("app.core.premium.family_tier_allows", new=AsyncMock(return_value=True)) as m:
        yield m


async def _due_family(db, **kw):
    f = await _family(db, **kw)
    await _template(db, f)
    p = await _user(db, f)
    return f, p


async def test_fires_once_when_due_consent_paid(db_session, paid):
    f, p = await _due_family(db_session)
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 1
    rows = await _rows(db_session, f)
    assert len(rows) == 1 and rows[0].user_id == p.id and rows[0].link == "/parent"


async def test_second_tick_same_month_sends_nothing(db_session, paid):
    f, _ = await _due_family(db_session)
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 1
    assert await PingService.run_monthly_show_and_tell(db_session, _now(hour=15)) == 0
    assert len(await _rows(db_session, f)) == 1


async def test_next_calendar_month_sends_again(db_session, paid):
    f, _ = await _due_family(db_session)
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 1
    assert await PingService.run_monthly_show_and_tell(db_session, _now(month_offset=1)) == 1
    assert len(await _rows(db_session, f)) == 2


async def test_before_ten_family_local_sends_nothing(db_session, paid):
    await _due_family(db_session)
    assert await PingService.run_monthly_show_and_tell(db_session, _now(hour=9)) == 0
    assert await _rows(db_session) == []


@pytest.mark.parametrize("hour,expected", [(10, 1), (20, 1), (21, 0), (23, 0)])
async def test_hour_window_bounds(db_session, paid, hour, expected):
    f, _ = await _due_family(db_session)
    assert await PingService.run_monthly_show_and_tell(db_session, _now(hour=hour)) == expected
    assert len(await _rows(db_session, f)) == expected


async def test_late_miss_retries_next_in_window_tick_once(db_session, paid):
    f, _ = await _due_family(db_session)
    assert await PingService.run_monthly_show_and_tell(db_session, _now(hour=22)) == 0
    assert await PingService.run_monthly_show_and_tell(db_session, _now(hour=11)) == 1
    assert await PingService.run_monthly_show_and_tell(db_session, _now(hour=12)) == 0


async def test_hour_gate_uses_family_timezone(db_session, paid):
    await _due_family(db_session, tz="America/Mexico_City")
    mx = ZoneInfo("America/Mexico_City")
    # 09:30 in Mexico City is already past 10:00 UTC: must still be blocked.
    early = _now(hour=9, tz=mx).replace(minute=30)
    assert early.astimezone(UTC).hour >= 14
    assert await PingService.run_monthly_show_and_tell(db_session, early.astimezone(UTC)) == 0
    # 10:00 in Mexico City is only ~16:00 UTC: allowed.
    assert await PingService.run_monthly_show_and_tell(db_session, _now(hour=10, tz=mx).astimezone(UTC)) == 1


async def test_not_due_when_baselines_fresh(db_session, paid):
    f = await _family(db_session)
    t = await _template(db_session, f)
    await _user(db_session, f)
    db_session.add(ChoreBaseline(family_id=f.id, template_id=t.id, image_url="/uploads/x.jpg",
                                 position=0, created_at=datetime.now(timezone.utc)))
    await db_session.commit()
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 0


async def test_stale_baseline_is_due(db_session, paid):
    f = await _family(db_session)
    t = await _template(db_session, f)
    await _user(db_session, f)
    db_session.add(ChoreBaseline(family_id=f.id, template_id=t.id, image_url="/uploads/x.jpg", position=0,
                                 created_at=datetime.now(timezone.utc) - timedelta(days=400)))
    await db_session.commit()
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 1


async def test_no_proof_templates_sends_nothing(db_session, paid):
    f = await _family(db_session)
    await _template(db_session, f, proof=False)
    await _user(db_session, f)
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 0


async def test_no_consent_sends_nothing(db_session, paid):
    await _due_family(db_session, consent=False)
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 0


async def test_free_plan_sends_nothing(db_session):
    await _due_family(db_session)  # real family_tier_allows: no subscription = free
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 0
    assert await _rows(db_session) == []


async def test_parents_only_active_approved(db_session, paid):
    f, p = await _due_family(db_session)
    await _user(db_session, f, UserRole.CHILD)
    await _user(db_session, f, UserRole.TEEN)
    await _user(db_session, f, UserRole.PARENT, is_active=False)
    await _user(db_session, f, UserRole.PARENT, approval_status="pending")
    p2 = await _user(db_session, f)
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 2
    assert {r.user_id for r in await _rows(db_session, f)} == {p.id, p2.id}


async def test_other_family_untouched(db_session, paid):
    f, _ = await _due_family(db_session, name="A")
    g = await _family(db_session, name="B")
    await _template(db_session, g, proof=False)  # nothing due
    await _user(db_session, g)
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 1
    assert await _rows(db_session, g) == []
    assert len(await _rows(db_session, f)) == 1


async def test_dedupe_is_per_family(db_session, paid):
    await _due_family(db_session, name="A")
    g, _ = await _due_family(db_session, name="B")
    assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 2
    assert len(await _rows(db_session, g)) == 1


async def test_es_en_by_member_language(db_session, paid):
    f = await _family(db_session)
    await _template(db_session, f)
    es = await _user(db_session, f, lang="es")
    en = await _user(db_session, f, lang="en")
    await PingService.run_monthly_show_and_tell(db_session, _now())
    by = {r.user_id: r for r in await _rows(db_session, f)}
    assert by[es.id].title.startswith("Hora de mostrar y contar")
    assert by[en.id].title.startswith("Show and tell")


async def test_failure_in_one_family_does_not_block_others(db_session, paid):
    await _due_family(db_session, name="A")
    await _due_family(db_session, name="B")
    from app.services.baseline_service import BaselineService
    real = BaselineService.status
    calls = {"n": 0}

    async def flaky(db, fid, now=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return await real(db, fid, now)

    with patch.object(BaselineService, "status", new=staticmethod(flaky)):
        assert await PingService.run_monthly_show_and_tell(db_session, _now()) == 1


def test_main_wires_monthly_nudge_in_its_own_try():
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_smart_ping_sweep")
    owners = {}
    for t in (n for n in ast.walk(fn) if isinstance(n, ast.Try)):
        text = "\n".join(ast.get_source_segment(src, s) or "" for s in t.body)
        for name in ("run_evening_sweep", "run_monthly_show_and_tell"):
            if name in text:
                owners[name] = t
    assert set(owners) == {"run_evening_sweep", "run_monthly_show_and_tell"}
    assert owners["run_evening_sweep"] is not owners["run_monthly_show_and_tell"]
    assert all(t.handlers for t in owners.values())


def test_main_rolls_back_shared_session_after_evening_failure():
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_smart_ping_sweep")
    evening = next(t for t in ast.walk(fn) if isinstance(t, ast.Try)
                   and "run_evening_sweep" in "\n".join(ast.get_source_segment(src, s) or "" for s in t.body))
    handler_src = "\n".join(ast.get_source_segment(src, s) or "" for s in evening.handlers[0].body)
    assert "session.rollback()" in handler_src
