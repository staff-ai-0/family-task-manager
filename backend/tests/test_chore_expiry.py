"""Chore rules v2: cutoff expiry (owner can no longer complete) and the
20:30-22:30 up-for-grabs window, in the family timezone."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.core.exceptions import (
    ChoreExpiredException, ConflictException, ForbiddenException, ValidationException,
)
from app.core.security import get_password_hash
from app.models.family import Family
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


async def _enable(db, family, on=True):
    family.timezone = "America/Mexico_City"
    family.early_bird_enabled = on
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(days=30)
    family.early_bird_deadline = time(11, 0)
    family.early_bird_days = None
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


# ---------------------------------------------------------------- window

@pytest.mark.parametrize("hh,mm,ss,listed", [
    (20, 29, 59, False), (20, 30, 0, True), (22, 29, 59, True), (22, 30, 0, False),
])
async def test_grab_window_boundaries(ctx, hh, mm, ss, listed):
    db, fam, owner, tpl, a, day = ctx
    rows = await EarlyBirdService.grabbable(db, fam.id, now=_at(day, hh, mm, ss))
    assert [r.assignment_id for r in rows] == ([a.id] if listed else [])


async def test_window_is_family_local_not_utc(ctx):
    db, fam, owner, tpl, a, day = ctx
    # 20:30 Mexico City is 02:30 UTC the next day: still "today" locally.
    now = _at(day, 20, 30).astimezone(timezone.utc)
    assert len(await EarlyBirdService.grabbable(db, fam.id, now=now)) == 1


async def test_child_owned_chore_is_listed(db_session, test_family, test_child_user):
    await _enable(db_session, test_family)
    day = _today()
    a = await _assign(db_session, test_child_user, await _tpl(db_session, test_family), day)
    rows = await EarlyBirdService.grabbable(db_session, test_family.id, now=_at(day, 21, 0))
    assert [r.assignment_id for r in rows] == [a.id]


async def test_exempt_and_bonus_never_listed(db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    day = _today()
    await _assign(db_session, test_teen_user, await _tpl(db_session, test_family, exempt=True), day)
    await _assign(db_session, test_teen_user, await _tpl(db_session, test_family, bonus=True), day)
    assert await EarlyBirdService.grabbable(db_session, test_family.id, now=_at(day, 21, 0)) == []


async def test_completed_chore_not_listed(ctx):
    db, fam, owner, tpl, a, day = ctx
    a.status = AssignmentStatus.COMPLETED
    await db.commit()
    assert await EarlyBirdService.grabbable(db, fam.id, now=_at(day, 21, 0)) == []


async def test_early_bird_off_lists_nothing(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_enabled = False
    await db.commit()
    assert await EarlyBirdService.grabbable(db, fam.id, now=_at(day, 21, 0)) == []


async def test_other_family_never_listed(ctx):
    db, fam, owner, tpl, a, day = ctx
    other = Family(name="Other")
    db.add(other)
    await db.commit()
    await _enable(db, other)
    kid = await _user(db, other, "Foreign")
    await _assign(db, kid, await _tpl(db, other), day)
    rows = await EarlyBirdService.grabbable(db, fam.id, now=_at(day, 21, 0))
    assert [r.assignment_id for r in rows] == [a.id]


# ------------------------------------------------------------------ take

async def test_any_member_incl_parent_may_take(ctx, test_parent_user):
    db, fam, owner, tpl, a, day = ctx
    row = await EarlyBirdService.take(db, fam.id, test_parent_user, a.id, now=_at(day, 21, 0))
    await db.refresh(a)
    assert a.status == AssignmentStatus.TAKEN and row.assigned_to == test_parent_user.id
    assert row.taken_from_id == a.id


async def test_owner_cannot_take_own(ctx):
    db, fam, owner, tpl, a, day = ctx
    with pytest.raises(ForbiddenException, match="own_chore"):
        await EarlyBirdService.take(db, fam.id, owner, a.id, now=_at(day, 21, 0))


async def test_role_not_in_allowed_roles_refused(db_session, test_family, test_teen_user,
                                                 test_parent_user):
    await _enable(db_session, test_family)
    day = _today()
    a = await _assign(db_session, test_teen_user,
                      await _tpl(db_session, test_family, allowed_roles=["teen"]), day)
    with pytest.raises(ForbiddenException, match="role_not_allowed"):
        await EarlyBirdService.take(db_session, test_family.id, test_parent_user, a.id,
                                    now=_at(day, 21, 0))


async def test_inactive_member_cannot_take(ctx):
    db, fam, owner, tpl, a, day = ctx
    sib = await _user(db, fam, "Sib")
    sib.is_active = False
    await db.commit()
    with pytest.raises(ForbiddenException, match="not_eligible"):
        await EarlyBirdService.take(db, fam.id, sib, a.id, now=_at(day, 21, 0))


@pytest.mark.parametrize("hh,mm,ss", [(20, 29, 59), (22, 30, 0), (23, 0, 0)])
async def test_take_outside_window_is_409_window_closed(ctx, hh, mm, ss):
    db, fam, owner, tpl, a, day = ctx
    sib = await _user(db, fam, "Sib")
    with pytest.raises(ConflictException, match="grab_window_closed"):
        await EarlyBirdService.take(db, fam.id, sib, a.id, now=_at(day, hh, mm, ss))
    await db.refresh(a)
    assert a.status == AssignmentStatus.PENDING


async def test_take_still_locks_both_rows(ctx):
    db, fam, owner, tpl, a, day = ctx
    sib = await _user(db, fam, "Sib")
    fam_id, a_id = fam.id, a.id
    row = await EarlyBirdService.take(db, fam_id, sib, a_id, now=_at(day, 21, 0))
    row_id = row.id
    for target in (a_id, row_id):
        with pytest.raises(ValidationException, match="Madrugador"):
            await TaskAssignmentService.patch_assignment(
                db, target, fam_id, status=AssignmentStatus.CANCELLED)
        await db.rollback()
    with pytest.raises(ValidationException, match="Madrugador"):
        await TaskAssignmentService.delete_by_id(db, row_id, fam_id)


async def test_taker_can_complete_after_cutoff(ctx):
    db, fam, owner, tpl, a, day = ctx
    sib = await _user(db, fam, "Sib")
    row = await EarlyBirdService.take(db, fam.id, sib, a.id, now=_at(day, 21, 0))
    done = await TaskAssignmentService.complete_assignment(
        db, row.id, fam.id, sib.id, now=_at(day, 21, 30))
    assert done.status == AssignmentStatus.COMPLETED


# ---------------------------------------------------------------- expiry

async def test_owner_completion_after_cutoff_expired(ctx):
    db, fam, owner, tpl, a, day = ctx
    with pytest.raises(ChoreExpiredException):
        await TaskAssignmentService.complete_assignment(
            db, a.id, fam.id, owner.id, now=_at(day, 20, 30))
    await db.refresh(a)
    assert a.status == AssignmentStatus.PENDING


async def test_owner_completion_before_cutoff_ok(ctx):
    db, fam, owner, tpl, a, day = ctx
    done = await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=_at(day, 20, 29, 59))
    assert done.status == AssignmentStatus.COMPLETED


async def test_mark_done_for_kid_after_cutoff_ok(ctx, test_parent_user):
    db, fam, owner, tpl, a, day = ctx
    # Yesterday's row is past its cutoff whatever the wall clock says.
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
        db_session, ex.id, test_family.id, test_teen_user.id, now=_at(day, 23, 0))
    assert done.status == AssignmentStatus.COMPLETED


async def test_early_bird_off_never_expires(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_enabled = False
    await db.commit()
    done = await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=_at(day, 23, 0))
    assert done.status == AssignmentStatus.COMPLETED


async def test_expiry_http_409_code(client, ctx):
    """Yesterday's open chore is past its cutoff by the real clock."""
    db, fam, owner, tpl, a, day = ctx
    old = await _assign(db, owner, await _tpl(db, fam, title="Old"), day - timedelta(days=1),
                        status=AssignmentStatus.OVERDUE)
    r = await client.post("/api/auth/login",
                          json={"email": "teen@test.com", "password": "password123"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await client.patch(f"/api/task-assignments/{old.id}/complete", headers=h)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "chore_expired"


# ------------------------------------------------------------------ push

async def _grab_rows(db, user):
    return (await db.execute(select(Notification).where(
        Notification.user_id == user.id, Notification.type == "up_for_grabs"))).scalars().all()


async def test_push_fires_at_cutoff_once_per_day(ctx):
    db, fam, owner, tpl, a, day = ctx
    sib = await _user(db, fam, "Sib")
    # Nothing at the 11:00 deadline any more, nor just before the cutoff.
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 11, 0)))["grabs"] == 0
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 20, 29)))["grabs"] == 0
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 20, 30))
    assert res["grabs"] >= 2
    assert len(await _grab_rows(db, sib)) == 1 and len(await _grab_rows(db, owner)) == 1
    await db.execute(update(Notification).values(created_at=_at(day, 20, 30)))
    await db.commit()
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 20, 35)))["grabs"] == 0
    assert len(await _grab_rows(db, sib)) == 1


# ------------------------------------------- R6: expired rows are not blockers

async def _bonus_done(db, fam, owner, day, now):
    b = await _assign(db, owner, await _tpl(db, fam, bonus=True, title="Gig"), day)
    return await TaskAssignmentService.complete_assignment(
        db, b.id, fam.id, owner.id, proof_text="did it", now=now)


async def test_yesterdays_untaken_chore_does_not_block_bonus(ctx):
    db, fam, owner, tpl, a, day = ctx
    a.assigned_date = day - timedelta(days=1)
    a.status = AssignmentStatus.OVERDUE
    await db.commit()
    done = await _bonus_done(db, fam, owner, day, _at(day, 9, 0))
    assert done.status == AssignmentStatus.COMPLETED


async def test_todays_untaken_chore_after_cutoff_does_not_block_bonus(ctx):
    db, fam, owner, tpl, a, day = ctx
    done = await _bonus_done(db, fam, owner, day, _at(day, 21, 0))
    assert done.status == AssignmentStatus.COMPLETED


async def test_before_cutoff_open_chore_still_blocks_bonus(ctx):
    db, fam, owner, tpl, a, day = ctx
    with pytest.raises(ForbiddenException, match="open mandatory"):
        await _bonus_done(db, fam, owner, day, _at(day, 20, 29))


async def test_early_bird_off_expired_chore_still_blocks_bonus(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_enabled = False
    await db.commit()
    with pytest.raises(ForbiddenException, match="open mandatory"):
        await _bonus_done(db, fam, owner, day, _at(day, 21, 0))


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

async def test_bonus_task_never_409_after_cutoff(db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    day = _today()
    done = await _bonus_done(db_session, test_family, test_teen_user, day, _at(day, 23, 0))
    assert done.status == AssignmentStatus.COMPLETED


async def test_inactive_day_never_409(ctx):
    db, fam, owner, tpl, a, day = ctx
    fam.early_bird_days = [(day.weekday() + 1) % 7]  # today is not an active day
    await db.commit()
    done = await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=_at(day, 23, 0))
    assert done.status == AssignmentStatus.COMPLETED


async def test_single_now_checks_and_stamps_same_instant(ctx):
    db, fam, owner, tpl, a, day = ctx
    instant = _at(day, 20, 29, 59).replace(microsecond=999000)
    done = await TaskAssignmentService.complete_assignment(
        db, a.id, fam.id, owner.id, now=instant)
    assert done.completed_at == instant


async def test_push_recipients_exact_and_since_is_cutoff(ctx, test_parent_user, test_child_user):
    db, fam, owner, tpl, a, day = ctx
    other = Family(name="Other")
    db.add(other)
    await db.commit()
    await _enable(db, other)
    foreign = await _user(db, other, "Foreign")
    await _assign(db, foreign, await _tpl(db, other), day)
    # A grab push stamped between the 11:00 deadline and the cutoff must not
    # dedup the cutoff push (the dedup window starts at the cutoff).
    db.add(Notification(family_id=fam.id, user_id=test_child_user.id, type="up_for_grabs",
                        title="old", created_at=_at(day, 15, 0)))
    await db.commit()
    await EarlyBirdService.run_sweep(db, now=_at(day, 20, 35))
    got = {n.user_id for n in (await db.execute(select(Notification).where(
        Notification.family_id == fam.id,
        Notification.type == "up_for_grabs", Notification.title != "old"))).scalars().all()}
    assert got == {owner.id, test_parent_user.id, test_child_user.id}
    # The other family is swept on its own: its kid is pushed, ours never see
    # its chores, and nothing of ours reached it.
    foreign_rows = (await db.execute(select(Notification).where(
        Notification.type == "up_for_grabs", Notification.user_id == foreign.id))).scalars().all()
    assert [n.family_id for n in foreign_rows] == [other.id]
