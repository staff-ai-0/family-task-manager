"""Chore expiry: a covered chore stays its owner's for its whole due day and
expires at the midnight that ends it, in the family timezone. Nothing is ever
released to the family (the evening cutoff and "up for grabs" were removed
2026-11-25)."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.exceptions import ChoreExpiredException, ForbiddenException
from app.core.security import get_password_hash
from app.models.notification import Notification
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.early_bird_service import EarlyBirdService
from app.services.task_assignment_service import TaskAssignmentService

MX = ZoneInfo("America/Mexico_City")


def _today() -> date:
    return datetime.now(MX).date()


def _at(day, hh, mm, ss=0):
    return datetime.combine(day, time(hh, mm, ss), tzinfo=MX)


def _next_morning(day):
    return _at(day + timedelta(days=1), 8, 0)


async def _enable(db, family, on=True):
    family.timezone = "America/Mexico_City"
    family.early_bird_enabled = on
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(days=30)
    family.early_bird_deadline = time(11, 0)
    family.early_bird_days = None
    # What every family still has stored from the old rules. Nothing reads
    # these columns any more: the tests below would fail at 20:30 if it did.
    family.chore_cutoff = time(20, 30)
    family.grab_window_end = time(22, 30)
    await db.commit()


async def _user(db, family, name, role=UserRole.TEEN):
    u = User(email=f"{name.lower()}-{uuid4().hex[:6]}@example.com",
             password_hash=get_password_hash("password123"), name=name, role=role,
             family_id=family.id, email_verified=True, points=0)
    db.add(u)
    await db.commit()
    return u


async def _tpl(db, family, *, exempt=False, bonus=False, allowed_roles=None, title="Dishes"):
    t = TaskTemplate(id=uuid4(), title=title, points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
                     family_id=family.id, early_bird_exempt=exempt, allowed_roles=allowed_roles)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, tpl, day, status=AssignmentStatus.PENDING):
    a = TaskAssignment(family_id=tpl.family_id, template_id=tpl.id, assigned_to=kid.id,
                       status=status, assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    day = _today()
    tpl = await _tpl(db_session, test_family)
    a = await _assign(db_session, test_teen_user, tpl, day)
    return db_session, test_family, test_teen_user, tpl, a, day


# ------------------------------------------------- the owner has the whole day

@pytest.mark.parametrize("hh,mm,ss", [(20, 30, 0), (21, 5, 0), (22, 30, 0), (23, 59, 59)])
async def test_owner_completion_any_time_on_the_due_day_ok(ctx, hh, mm, ss):
    """20:30 was the old evening cutoff and 22:30 the end of the old grab
    window: the owner can report straight through both."""
    db, fam, owner, tpl, a, day = ctx
    done = await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=_at(day, hh, mm, ss))
    assert done.status == AssignmentStatus.COMPLETED


async def test_owner_completion_after_midnight_expired(ctx):
    db, fam, owner, tpl, a, day = ctx
    with pytest.raises(ChoreExpiredException):
        await TaskAssignmentService.complete_assignment(
            db, a.id, fam.id, owner.id, now=_at(day + timedelta(days=1), 0, 0, 0))
    await db.refresh(a)
    assert a.status == AssignmentStatus.PENDING


async def test_day_end_is_family_local_midnight(ctx):
    """Mexico City is UTC-6: the day ends at 06:00 UTC of the next date, not at
    00:00 UTC (18:00 local) and not at 24:00 UTC."""
    db, fam, owner, tpl, a, day = ctx
    a_id, fam_id, owner_id = a.id, fam.id, owner.id
    nxt = day + timedelta(days=1)
    with pytest.raises(ChoreExpiredException):
        await TaskAssignmentService.complete_assignment(
            db, a_id, fam_id, owner_id,
            now=datetime(nxt.year, nxt.month, nxt.day, 6, 0, 0, tzinfo=timezone.utc))
    await db.rollback()
    done = await TaskAssignmentService.complete_assignment(
        db, a_id, fam_id, owner_id,
        now=datetime(nxt.year, nxt.month, nxt.day, 5, 59, 59, tzinfo=timezone.utc))
    assert done.status == AssignmentStatus.COMPLETED


async def test_evening_completion_counts_for_the_ladder(ctx):
    """Reported at 21:00 on its day: done for the weekly pay (not early)."""
    from app.services.early_bird_rules import completed_in_time, done_early
    db, fam, owner, tpl, a, day = ctx
    await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=_at(day, 21, 0))
    cfg = await EarlyBirdService.config(db, fam.id)
    row = (await EarlyBirdService.covered_rows(db, cfg, fam.id, owner.id, day, day))[0]
    assert completed_in_time(row, cfg) is True
    assert done_early(row, cfg) is False


async def test_nothing_is_released_in_the_evening(ctx):
    """No sweep tick writes an up-for-grabs notice, at the old cutoff or later."""
    db, fam, owner, tpl, a, day = ctx
    await _user(db, fam, "Sib")
    for hh, mm in ((20, 30), (20, 35), (21, 0), (22, 29), (23, 55)):
        await EarlyBirdService.run_sweep(db, now=_at(day, hh, mm))
    rows = (await db.execute(select(Notification).where(
        Notification.family_id == fam.id, Notification.type == "up_for_grabs"))).scalars().all()
    assert rows == []
    await db.refresh(a)
    assert a.status == AssignmentStatus.PENDING and a.assigned_to == owner.id


# ---------------------------------------------------------------- expiry

async def test_mark_done_for_kid_after_the_day_ended_ok(ctx, test_parent_user):
    db, fam, owner, tpl, a, day = ctx
    # Yesterday's row is past its day whatever the wall clock says.
    a = await _assign(db, owner, await _tpl(db, fam, title="Old"), day - timedelta(days=1),
                      status=AssignmentStatus.OVERDUE)
    await TaskAssignmentService.mark_done_for_kid(
        db, assignment_id=a.id, family_id=fam.id, parent_id=test_parent_user.id,
        note="she did it")
    await db.refresh(a)
    assert a.status == AssignmentStatus.COMPLETED


async def test_exempt_never_expires(db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    day = _today()
    ex = await _assign(db_session, test_teen_user,
                       await _tpl(db_session, test_family, exempt=True), day)
    done = await TaskAssignmentService.complete_assignment(
        db_session, ex.id, test_family.id, test_teen_user.id, now=_next_morning(day))
    assert done.status == AssignmentStatus.COMPLETED


async def test_early_bird_off_never_expires(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_enabled = False
    await db.commit()
    done = await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=_next_morning(day))
    assert done.status == AssignmentStatus.COMPLETED


async def test_expiry_http_409_code(client, ctx):
    """Yesterday's open chore is past its day by the real clock."""
    db, fam, owner, tpl, a, day = ctx
    old = await _assign(db, owner, await _tpl(db, fam, title="Old"), day - timedelta(days=1),
                        status=AssignmentStatus.OVERDUE)
    r = await client.post("/api/auth/login",
                          json={"email": "teen@test.com", "password": "password123"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await client.patch(f"/api/task-assignments/{old.id}/complete", headers=h)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "chore_expired"


# ------------------------------------------- R6: expired rows are not blockers

async def _bonus_done(db, fam, owner, day, now):
    b = await _assign(db, owner, await _tpl(db, fam, bonus=True, title="Gig"), day)
    return await TaskAssignmentService.complete_assignment(
        db, b.id, fam.id, owner.id, proof_text="did it", now=now)


async def test_yesterdays_open_chore_does_not_block_bonus(ctx):
    db, fam, owner, tpl, a, day = ctx
    a.assigned_date = day - timedelta(days=1)
    a.status = AssignmentStatus.OVERDUE
    await db.commit()
    done = await _bonus_done(db, fam, owner, day, _at(day, 9, 0))
    assert done.status == AssignmentStatus.COMPLETED


@pytest.mark.parametrize("hh,mm", [(20, 29), (21, 0), (23, 59)])
async def test_todays_open_chore_in_the_evening_still_blocks_bonus(ctx, hh, mm):
    """Still the kid's all day, so it still gates bonus tasks all day (it
    stopped gating at 20:30 while the chore was released then)."""
    db, fam, owner, tpl, a, day = ctx
    with pytest.raises(ForbiddenException, match="open mandatory"):
        await _bonus_done(db, fam, owner, day, _at(day, hh, mm))


async def test_early_bird_off_expired_chore_still_blocks_bonus(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_enabled = False
    a.assigned_date = day - timedelta(days=1)
    a.status = AssignmentStatus.OVERDUE
    await db.commit()
    with pytest.raises(ForbiddenException, match="open mandatory"):
        await _bonus_done(db, fam, owner, day, _at(day, 9, 0))


async def test_expired_chore_does_not_block_claim_gig(ctx):
    db, fam, owner, tpl, a, day = ctx
    a.assigned_date = day - timedelta(days=1)  # expired by the real clock
    a.status = AssignmentStatus.OVERDUE
    await db.commit()
    g = await _assign(db, owner, await _tpl(db, fam, bonus=True, title="Gig"), day)
    out = await TaskAssignmentService.claim_gig(db, g.id, fam.id, owner.id)
    assert out.status == AssignmentStatus.CLAIMED


async def test_early_bird_off_chore_still_blocks_claim_gig(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_enabled = False
    a.assigned_date = day - timedelta(days=1)
    a.status = AssignmentStatus.OVERDUE
    await db.commit()
    g = await _assign(db, owner, await _tpl(db, fam, bonus=True, title="Gig"), day)
    with pytest.raises(ForbiddenException):
        await TaskAssignmentService.claim_gig(db, g.id, fam.id, owner.id)


async def test_atrasadas_excludes_expired_keeps_exempt(ctx):
    db, fam, owner, tpl, a, day = ctx
    y = day - timedelta(days=1)
    a.assigned_date = y
    a.status = AssignmentStatus.OVERDUE
    ex = await _assign(db, owner, await _tpl(db, fam, exempt=True, title="Evening"), y,
                       status=AssignmentStatus.OVERDUE)
    await db.commit()
    rows = await TaskAssignmentService.list_open_mandatory_before(
        db, owner.id, fam.id, day, now=_at(day, 9, 0))
    assert [r.id for r in rows] == [ex.id]


async def test_atrasadas_early_bird_off_keeps_all(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_enabled = False
    a.assigned_date = day - timedelta(days=1)
    a.status = AssignmentStatus.OVERDUE
    await db.commit()
    rows = await TaskAssignmentService.list_open_mandatory_before(db, owner.id, fam.id, day)
    assert [r.id for r in rows] == [a.id]


async def test_waiting_count_excludes_expired_keeps_exempt(ctx):
    from app.services.ping_service import PingService
    db, fam, owner, tpl, a, day = ctx
    y = day - timedelta(days=1)
    a.assigned_date = y
    a.status = AssignmentStatus.OVERDUE
    await _assign(db, owner, await _tpl(db, fam, exempt=True, title="Evening"), y,
                  status=AssignmentStatus.OVERDUE)
    await db.commit()
    assert await PingService.waiting_count(db, owner) == 1


async def test_kiosk_overdue_list_excludes_expired(client, ctx):
    from app.models.kiosk_device import KioskDevice
    db, fam, owner, tpl, a, day = ctx
    kid = await _user(db, fam, "Kiosky", UserRole.CHILD)
    y = day - timedelta(days=1)
    await _assign(db, kid, await _tpl(db, fam, title="Gone"), y, status=AssignmentStatus.OVERDUE)
    await _assign(db, kid, await _tpl(db, fam, exempt=True, title="Evening"), y,
                  status=AssignmentStatus.OVERDUE)
    dev = KioskDevice(family_id=fam.id, name="Hall", token="kiosktesttoken" * 4)
    db.add(dev)
    await db.commit()
    parent = await _user(db, fam, "Par", UserRole.PARENT)
    r = await client.post("/api/auth/login", json={"email": parent.email, "password": "password123"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await client.put(f"/api/kiosk/member-prefs/{kid.id}", json={"pin": "4321"}, headers=h)
    assert r.status_code == 200, r.text
    r = await client.post("/api/kiosk/pin-view", json={
        "token": dev.token, "user_id": str(kid.id), "pin": "4321"})
    assert r.status_code == 200, r.text
    assert [c["title"] for c in r.json()["overdue_chores"]] == ["Evening"]


# ------------------------------------------------------------ mutation killers

async def test_bonus_task_never_409_after_the_day_ended(db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    day = _today()
    done = await _bonus_done(db_session, test_family, test_teen_user, day, _next_morning(day))
    assert done.status == AssignmentStatus.COMPLETED


async def test_inactive_day_never_409(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_days = [(day.weekday() + 1) % 7]  # today is not an active day
    await db.commit()
    done = await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=_next_morning(day))
    assert done.status == AssignmentStatus.COMPLETED


async def test_single_now_checks_and_stamps_same_instant(ctx):
    db, fam, owner, tpl, a, day = ctx
    instant = _at(day, 23, 59, 59).replace(microsecond=999000)
    done = await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=instant)
    assert done.completed_at == instant


# --------------------------------------- R9: a parent send-back stays redoable

PHOTO = "/uploads/gig-proofs/" + "ab" * 16 + ".jpg"


async def _sent_back(db, fam, owner, parent, day):
    """A proof chore the teen submitted at 20:00 that the parent sent back:
    reopened as PENDING + approval REJECTED (approve_gig reject path)."""
    from app.models.task_assignment import ApprovalStatus
    tpl = await _tpl(db, fam, title="Room")
    tpl.requires_proof = True
    await db.commit()
    row = await _assign(db, owner, tpl, day)
    await TaskAssignmentService.complete_assignment(
        db, row.id, fam.id, owner.id, proof_image_url=PHOTO, now=_at(day, 20, 0))
    await TaskAssignmentService.approve_gig(
        db, row.id, fam.id, parent.id, approve=False, notes="redo it")
    await db.refresh(row)
    assert (row.status, row.approval_status) == (
        AssignmentStatus.PENDING, ApprovalStatus.REJECTED)
    return row


async def test_sent_back_proof_chore_redo_the_next_day_ok(ctx, test_parent_user):
    """Sent back in the evening, redone the next morning: the send-back notice
    told the kid to redo it, so a 409 there would be a dead end."""
    from app.models.task_assignment import ApprovalStatus
    db, fam, owner, tpl, a, day = ctx
    row = await _sent_back(db, fam, owner, test_parent_user, day)
    done = await TaskAssignmentService.complete_assignment(
        db, row.id, fam.id, owner.id, proof_image_url=PHOTO, now=_next_morning(day))
    assert (done.status, done.approval_status) == (
        AssignmentStatus.COMPLETED, ApprovalStatus.PENDING)


async def test_plain_open_row_still_409_the_next_day(ctx, test_parent_user):
    """The send-back exemption is per row: the kid's other open chore of that
    day is expired the next morning."""
    db, fam, owner, tpl, a, day = ctx
    await _sent_back(db, fam, owner, test_parent_user, day)
    with pytest.raises(ChoreExpiredException):
        await TaskAssignmentService.complete_assignment(
            db, a.id, fam.id, owner.id, now=_next_morning(day))


async def test_sent_back_row_blocks_bonus_until_redone(ctx, test_parent_user):
    """Not "resolved" like an expired row: the next morning it still gates
    bonus tasks, while the plain open ``a`` of the same day no longer does."""
    db, fam, owner, tpl, a, day = ctx
    row = await _sent_back(db, fam, owner, test_parent_user, day)
    morning = _next_morning(day)
    assert await TaskAssignmentService.has_open_mandatory_through(
        db, owner.id, fam.id, day, now=morning)
    with pytest.raises(ForbiddenException, match="open mandatory"):
        await _bonus_done(db, fam, owner, day, morning)
    await TaskAssignmentService.complete_assignment(
        db, row.id, fam.id, owner.id, proof_image_url=PHOTO, now=morning)
    assert not await TaskAssignmentService.has_open_mandatory_through(
        db, owner.id, fam.id, day, now=morning + timedelta(minutes=5))


async def test_sent_back_row_stays_in_atrasadas(ctx, test_parent_user):
    """Yesterday's send-back is still the kid's to redo, so it is listed."""
    db, fam, owner, tpl, a, day = ctx
    a.status = AssignmentStatus.COMPLETED  # only the send-back is open
    await db.commit()
    row = await _sent_back(db, fam, owner, test_parent_user, day)
    row.assigned_date = day - timedelta(days=1)
    await db.commit()
    rows = await TaskAssignmentService.list_open_mandatory_before(
        db, owner.id, fam.id, day, now=_at(day, 9, 0))
    assert [r.id for r in rows] == [row.id]


async def _approved_redo_in_time(db, fam, owner, parent, day, redo_at) -> bool:
    from app.services.early_bird_rules import completed_in_time
    row = await _sent_back(db, fam, owner, parent, day)
    await TaskAssignmentService.complete_assignment(
        db, row.id, fam.id, owner.id, proof_image_url=PHOTO, now=redo_at)
    await TaskAssignmentService.approve_gig(db, row.id, fam.id, parent.id, approve=True)
    cfg = await EarlyBirdService.config(db, fam.id)
    covered = {r.assignment_id: r for r in await EarlyBirdService.covered_rows(
        db, cfg, fam.id, owner.id, day, day)}
    assert covered[row.id].status == AssignmentStatus.COMPLETED
    return completed_in_time(covered[row.id], cfg, grace=True)


async def test_same_evening_redo_counts_for_the_ladder(ctx, test_parent_user):
    db, fam, owner, tpl, a, day = ctx
    assert await _approved_redo_in_time(
        db, fam, owner, test_parent_user, day, _at(day, 21, 5)) is True


async def test_next_day_redo_counts_late_for_the_ladder(ctx, test_parent_user):
    """The redo after the day ended is done, but not "completed in time"."""
    db, fam, owner, tpl, a, day = ctx
    assert await _approved_redo_in_time(
        db, fam, owner, test_parent_user, day, _next_morning(day)) is False


# ------------------------------------------------ gate cost (Early Bird off)

async def _statements(db, coro):
    from sqlalchemy import event
    seen = []
    bind = db.get_bind()
    sync_engine = getattr(bind, "sync_engine", bind)

    def record(conn, cursor, statement, *a):
        seen.append(" ".join(statement.split()).lower())

    event.listen(sync_engine, "before_cursor_execute", record)
    try:
        result = await coro
    finally:
        event.remove(sync_engine, "before_cursor_execute", record)
    return result, seen


async def test_gate_with_early_bird_off_is_the_plain_count(ctx):
    """Early Bird off: the bonus/gig gate is the pre-feature COUNT — it never
    loads assignment rows or their templates (it runs on every gig list/claim)."""
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_enabled = False
    await db.commit()
    for expect in (True, False):
        if not expect:
            a.status = AssignmentStatus.COMPLETED
            await db.commit()
        got, seen = await _statements(db, TaskAssignmentService.has_open_mandatory_through(
            db, owner.id, fam.id, day, now=_at(day, 21, 0)))
        assert got is expect
        assert any(s.startswith("select count(*)") for s in seen), seen
        assert not any(s.startswith("select task_assignments.id") for s in seen), seen
        assert not any(s.startswith("select task_templates") for s in seen), seen


async def test_gate_with_early_bird_on_drops_rows_once_their_day_ended(ctx):
    """Early Bird on: open all day (the old 20:30 cutoff included), resolved
    from the midnight that ends the day (R6: expired = resolved)."""
    db, fam, owner, tpl, a, day = ctx
    for hh, mm in ((20, 29), (20, 30), (23, 59)):
        assert await TaskAssignmentService.has_open_mandatory_through(
            db, owner.id, fam.id, day, now=_at(day, hh, mm)) is True
    assert await TaskAssignmentService.has_open_mandatory_through(
        db, owner.id, fam.id, day, now=_at(day + timedelta(days=1), 0, 0)) is False
