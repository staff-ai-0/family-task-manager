"""Operator view of the teen check-ins: counts across families, no identities."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.family import Family
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.models.user import User, UserRole

URL = "/api/admin/teen-checkins"
NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


async def _teen(db, family, email):
    u = User(email=email, password_hash="x", name="Secret Name", role=UserRole.TEEN, family_id=family.id,
             email_verified=True, points=0)
    db.add(u)
    await db.commit()
    return u


async def _chore(db, family, teen, status):
    t = TaskTemplate(id=uuid4(), title="Secret Chore Title", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True, family_id=family.id)
    db.add(t)
    await db.commit()
    day = NOW().date() - timedelta(days=1)
    a = TaskAssignment(family_id=family.id, template_id=t.id, assigned_to=teen.id, status=status,
                       approval_status=ApprovalStatus.NONE, assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


def _row(family, teen, *, outcome="answered", reason="forgot", note=None, trigger="late", days_ago=1,
         assignment=None, lang="en"):
    return TeenCheckin(family_id=family.id, user_id=teen.id, assignment_id=assignment.id if assignment else None,
                       trigger=trigger, outcome=outcome, reason=reason if outcome == "answered" else None,
                       note=note, days_late=1, points=10, lang=lang, created_at=NOW() - timedelta(days=days_ago))


async def _crowd(db, n):
    """n more opted-in families, each with one teen and one answered check-in."""
    for i in range(n):
        fam = Family(name=f"Crowd {i}", teen_checkin_enabled=True)
        db.add(fam)
        await db.commit()
        teen = await _teen(db, fam, f"crowd{i}@test.com")
        db.add(_row(fam, teen, reason="no_time", days_ago=6))
    await db.commit()


async def _seed(db, test_family):
    test_family.teen_checkin_enabled = True
    other = Family(name="Secret Family Name", teen_checkin_enabled=True)
    db.add(other)
    await db.commit()
    t1 = await _teen(db, test_family, "t1@test.com")
    t2 = await _teen(db, other, "t2@test.com")
    done = await _chore(db, test_family, t1, AssignmentStatus.COMPLETED)
    still_open = await _chore(db, other, t2, AssignmentStatus.OVERDUE)
    db.add_all([
        _row(test_family, t1, reason="forgot", assignment=done),
        _row(test_family, t1, reason="not_fair", trigger="sent_back", days_ago=2),
        _row(test_family, t1, outcome="dismissed", days_ago=3),
        _row(other, t2, reason="app_problem", note="the photo button does nothing", assignment=still_open),
        _row(other, t2, reason="other", note="siempre me toca a mí", lang="es", days_ago=5),
        _row(other, t2, reason="too_hard", days_ago=40),                    # outside a 30-day window
    ])
    await db.commit()
    return other, t1, t2


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


class TestSummary:
    async def test_counts_span_families(self, client, db_session, superadmin_headers, test_family):
        await _seed(db_session, test_family)
        r = await client.get(URL, params={"days": 30}, headers=superadmin_headers)
        assert r.status_code == 200
        body = r.json()
        assert (body["days"], body["answered"], body["dismissed"], body["families"], body["teens"]) == (30, 4, 1, 2, 2)
        assert body["by_reason"] == {"too_hard": 0, "not_clear": 0, "no_time": 0, "not_fair": 1, "forgot": 1,
                                     "app_problem": 1, "other": 1}
        assert body["by_kind"] == {"chore": 2, "app": 1, "other": 1}
        assert body["by_trigger"] == {"late": 3, "sent_back": 1}
        assert body["done_afterwards"] == 1
        for value in (body["answered"], body["families"], body["done_afterwards"], body["by_reason"]["forgot"]):
            assert isinstance(value, int)

    async def test_a_longer_window_reaches_older_rows(self, client, db_session, superadmin_headers, test_family):
        await _seed(db_session, test_family)
        body = (await client.get(URL, params={"days": 90}, headers=superadmin_headers)).json()
        assert body["answered"] == 5 and body["by_reason"]["too_hard"] == 1

    async def test_notes_are_withheld_until_enough_families_take_part(self, client, db_session, superadmin_headers, test_family):
        await _seed(db_session, test_family)                       # 2 families: a note would point at one of them
        body = (await client.get(URL, params={"days": 30}, headers=superadmin_headers)).json()
        assert body["families"] == 2 and body["min_families_for_notes"] == 5
        assert body["notes"] == {"total": 0, "items": [], "withheld": True}
        assert "photo button" not in str(body)
        assert body["by_reason"]["app_problem"] == 1               # counts are still shown
        await _crowd(db_session, 2)                                # 4 families: still withheld
        assert (await client.get(URL, headers=superadmin_headers)).json()["notes"]["withheld"] is True

    async def test_notes_are_listed_newest_first_and_paged(self, client, db_session, superadmin_headers, test_family):
        await _seed(db_session, test_family)
        await _crowd(db_session, 3)                                # 5 families taking part
        body = (await client.get(URL, params={"days": 30}, headers=superadmin_headers)).json()
        assert body["families"] == 5 and body["notes"]["withheld"] is False
        assert body["notes"]["total"] == 2
        assert [n["note"] for n in body["notes"]["items"]] == ["the photo button does nothing", "siempre me toca a mí"]
        assert body["notes"]["items"][1]["lang"] == "es" and body["notes"]["items"][0]["reason"] == "app_problem"
        page = (await client.get(URL, params={"days": 30, "limit": 1, "offset": 1}, headers=superadmin_headers)).json()
        assert [n["note"] for n in page["notes"]["items"]] == ["siempre me toca a mí"] and page["notes"]["total"] == 2
        # A day, never a timestamp: a time would line up with "last seen" elsewhere in the console.
        for note in body["notes"]["items"]:
            assert len(note["created_at"]) == 10 and note["created_at"].count("-") == 2

    async def test_a_family_that_switched_off_or_is_being_deleted_is_left_out(self, client, db_session, superadmin_headers, test_family):
        other, _t1, _t2 = await _seed(db_session, test_family)
        await _crowd(db_session, 4)                                # 6 families, so notes are shown
        before = (await client.get(URL, headers=superadmin_headers)).json()
        assert before["families"] == 6 and before["notes"]["total"] == 2
        other.teen_checkin_enabled = False                         # the family with both notes says stop
        await db_session.commit()
        after = (await client.get(URL, headers=superadmin_headers)).json()
        assert after["families"] == 5 and after["notes"]["total"] == 0 and after["by_reason"]["app_problem"] == 0
        assert after["answered"] == before["answered"] - 2
        test_family.deleted_at = NOW()                             # inside the deletion grace window
        await db_session.commit()
        gone = (await client.get(URL, headers=superadmin_headers)).json()
        assert gone["families"] == 4 and gone["by_reason"]["forgot"] == 0 and gone["dismissed"] == 0

    async def test_nothing_in_the_answer_identifies_anyone(self, client, db_session, superadmin_headers, test_family):
        other, t1, t2 = await _seed(db_session, test_family)
        await _crowd(db_session, 3)                                # enough families for the notes to be listed
        r = await client.get(URL, params={"days": 90}, headers=superadmin_headers)
        keys = set(_keys(r.json()))
        assert not ({"family_id", "user_id", "assignment_id", "id", "name", "email", "title", "family", "user"} & keys)
        assert set(r.json()["notes"]["items"][0]) == {"created_at", "reason", "lang", "note"}
        text = r.text
        for secret in (str(test_family.id), str(other.id), str(t1.id), str(t2.id), "Secret Name",
                       "Secret Family Name", "Secret Chore Title", "t1@test.com"):
            assert secret not in text

    async def test_an_empty_platform_reads_as_zeroes(self, client, superadmin_headers):
        body = (await client.get(URL, headers=superadmin_headers)).json()
        assert body["days"] == 30 and body["answered"] == 0
        assert body["notes"] == {"total": 0, "items": [], "withheld": True}
        assert body["by_kind"] == {"chore": 0, "app": 0, "other": 0}

    async def test_bounds(self, client, superadmin_headers):
        # Two fixed windows only: arbitrary ones would let adjacent windows isolate one day's rows.
        for params in ({"days": 0}, {"days": 1}, {"days": 29}, {"days": 365}, {"limit": 0}, {"limit": 101}, {"offset": -1}):
            assert (await client.get(URL, params=params, headers=superadmin_headers)).status_code == 422
        for days in (30, 90):
            assert (await client.get(URL, params={"days": days}, headers=superadmin_headers)).status_code == 200


class TestAuthz:
    async def test_a_parent_gets_a_404(self, client, auth_headers):
        assert (await client.get(URL, headers=auth_headers)).status_code == 404

    async def test_anonymous_gets_no_data(self, client):
        assert (await client.get(URL)).status_code in (401, 403, 404)
