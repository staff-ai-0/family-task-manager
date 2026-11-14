"""Chore baselines: per-template reference photos (parent-only, family-scoped)."""
import io
import os
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.chore_baseline import ChoreBaseline
from app.models.family import Family
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.services.baseline_service import (
    BASELINE_STALE_DAYS,
    MAX_BASELINES_PER_TEMPLATE,
    MAX_BASELINES_TO_AI,
    BaselineService,
)
from app.services.family_export_service import EXPORTED_FAMILY_TABLES


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _template(db, family, title="Make bed", proof=True, active=True):
    t = TaskTemplate(title=title, family_id=family.id, requires_proof=proof, is_active=active, points=5)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _upload(client, headers, tid, caption=None, data=None, ctype="image/jpeg"):
    return await client.post(
        f"/api/task-templates/{tid}/baselines",
        files={"file": ("a.jpg", data if data is not None else _jpeg(), ctype)},
        data={"caption": caption} if caption else None,
        headers=headers,
    )


@pytest.fixture
async def other_parent(db_session):
    fam = Family(name="Other")
    db_session.add(fam)
    await db_session.commit()
    u = User(email="other@test.com", password_hash=get_password_hash("password123"), name="O",
             role=UserRole.PARENT, family_id=fam.id, email_verified=True, points=0)
    db_session.add(u)
    await db_session.commit()
    return fam, u


def _path(url, thumb=False):
    from app.core.thumbnails import thumb_filename
    name = url.rsplit("/", 1)[1]
    return os.path.join(settings.UPLOADS_ROOT, "chore-baselines", thumb_filename(name) if thumb else name)


async def test_upload_list_roundtrip(client, db_session, test_family, test_parent_user, auth_headers):
    t = await _template(db_session, test_family)
    r = await _upload(client, auth_headers, t.id, caption="Corners tucked")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["image_url"].startswith("/uploads/chore-baselines/")
    assert body["caption"] == "Corners tucked"
    assert os.path.isfile(_path(body["image_url"]))
    assert os.path.isfile(_path(body["image_url"], thumb=True))
    lst = await client.get(f"/api/task-templates/{t.id}/baselines", headers=auth_headers)
    assert lst.status_code == 200
    assert [b["id"] for b in lst.json()] == [body["id"]]


async def test_fifth_upload_is_409_baseline_limit(client, db_session, test_family, test_parent_user, auth_headers):
    t = await _template(db_session, test_family)
    for _ in range(MAX_BASELINES_PER_TEMPLATE):
        assert (await _upload(client, auth_headers, t.id)).status_code == 201
    r = await _upload(client, auth_headers, t.id)
    assert r.status_code == 409
    assert r.json()["code"] == "baseline_limit"
    n = (await db_session.execute(select(func.count()).select_from(ChoreBaseline))).scalar_one()
    assert n == MAX_BASELINES_PER_TEMPLATE


async def test_non_image_and_spoofed_are_415(client, db_session, test_family, test_parent_user, auth_headers):
    t = await _template(db_session, test_family)
    assert (await _upload(client, auth_headers, t.id, data=b"hi", ctype="text/plain")).status_code == 415
    assert (await _upload(client, auth_headers, t.id, data=b"not an image", ctype="image/jpeg")).status_code == 415


async def test_oversized_is_413(client, db_session, test_family, test_parent_user, auth_headers):
    t = await _template(db_session, test_family)
    big = b"\xff\xd8\xff" + b"\x00" * (15 * 1024 * 1024 + 1)
    assert (await _upload(client, auth_headers, t.id, data=big)).status_code == 413


async def test_caption_too_long_is_422(client, db_session, test_family, test_parent_user, auth_headers):
    t = await _template(db_session, test_family)
    assert (await _upload(client, auth_headers, t.id, caption="x" * 121)).status_code == 422


async def test_delete_removes_row_and_files(client, db_session, test_family, test_parent_user, auth_headers):
    t = await _template(db_session, test_family)
    b = (await _upload(client, auth_headers, t.id)).json()
    orig, thumb = _path(b["image_url"]), _path(b["image_url"], thumb=True)
    assert os.path.isfile(orig) and os.path.isfile(thumb)
    r = await client.delete(f"/api/task-templates/{t.id}/baselines/{b['id']}", headers=auth_headers)
    assert r.status_code == 204
    assert not os.path.exists(orig) and not os.path.exists(thumb)
    n = (await db_session.execute(select(func.count()).select_from(ChoreBaseline))).scalar_one()
    assert n == 0
    assert (await client.delete(f"/api/task-templates/{t.id}/baselines/{b['id']}", headers=auth_headers)).status_code == 404


async def test_kid_is_403(client, db_session, test_family, test_parent_user, test_child_user, auth_headers):
    t = await _template(db_session, test_family)
    b = (await _upload(client, auth_headers, t.id)).json()
    kid = await _login(client, "child@test.com")
    assert (await client.get(f"/api/task-templates/{t.id}/baselines", headers=kid)).status_code == 403
    assert (await _upload(client, kid, t.id)).status_code == 403
    assert (await client.delete(f"/api/task-templates/{t.id}/baselines/{b['id']}", headers=kid)).status_code == 403
    assert (await client.get("/api/task-templates/baselines/status", headers=kid)).status_code == 403


async def test_cross_family_isolation(client, db_session, test_family, test_parent_user, auth_headers, other_parent):
    fam_b, _ = other_parent
    t = await _template(db_session, test_family)
    b = (await _upload(client, auth_headers, t.id)).json()
    hb = await _login(client, "other@test.com")
    assert (await client.get(f"/api/task-templates/{t.id}/baselines", headers=hb)).status_code == 404
    assert (await _upload(client, hb, t.id)).status_code == 404
    assert (await client.delete(f"/api/task-templates/{t.id}/baselines/{b['id']}", headers=hb)).status_code == 404
    # Own template, A's baseline id: still 404 and A's row survives.
    tb = await _template(db_session, fam_b, title="B chore")
    assert (await client.delete(f"/api/task-templates/{tb.id}/baselines/{b['id']}", headers=hb)).status_code == 404
    assert os.path.isfile(_path(b["image_url"])) and os.path.isfile(_path(b["image_url"], thumb=True))
    assert (await client.get(b["image_url"], headers=hb)).status_code == 404
    assert (await client.get(b["image_url"], headers=auth_headers)).status_code == 200
    n = (await db_session.execute(select(func.count()).select_from(ChoreBaseline))).scalar_one()
    assert n == 1


async def test_serve_thumb_and_traversal(client, db_session, test_family, test_parent_user, auth_headers):
    t = await _template(db_session, test_family)
    b = (await _upload(client, auth_headers, t.id)).json()
    r = await client.get(b["image_url"] + "?size=thumb", headers=auth_headers)
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert (await client.get("/uploads/chore-baselines/nope.jpg", headers=auth_headers)).status_code == 404
    for bad in ("..%2fsecret", ".hidden", "%2e%2e%2fsecret", "..%5csecret"):
        got = await client.get(f"/uploads/chore-baselines/{bad}", headers=auth_headers)
        assert got.status_code in (400, 404), (bad, got.status_code)
    assert (await client.get(b["image_url"])).status_code in (401, 403)


async def test_status_route_not_shadowed_and_due_logic(client, db_session, test_family, test_parent_user, auth_headers):
    none_t = await _template(db_session, test_family, title="None")
    stale_t = await _template(db_session, test_family, title="Stale")
    fresh_t = await _template(db_session, test_family, title="Fresh")
    await _template(db_session, test_family, title="NoProof", proof=False)
    await _template(db_session, test_family, title="Inactive", active=False)
    await _upload(client, auth_headers, stale_t.id)
    await _upload(client, auth_headers, fresh_t.id)
    old = datetime.now(timezone.utc) - timedelta(days=BASELINE_STALE_DAYS + 1)
    row = (await db_session.execute(select(ChoreBaseline).where(ChoreBaseline.template_id == stale_t.id))).scalar_one()
    row.created_at = old
    await db_session.commit()

    r = await client.get("/api/task-templates/baselines/status", headers=auth_headers)
    assert r.status_code == 200, r.text
    by = {x["title"]: x for x in r.json()}
    assert set(by) == {"None", "Stale", "Fresh"}
    assert by["None"]["due"] is True and by["None"]["baseline_count"] == 0 and by["None"]["last_baseline_at"] is None
    assert by["Stale"]["due"] is True and by["Stale"]["baseline_count"] == 1
    assert by["Fresh"]["due"] is False
    assert str(none_t.id) == by["None"]["template_id"]


async def test_status_other_family_excluded(db_session, test_family, other_parent):
    fam_b, _ = other_parent
    await _template(db_session, fam_b, title="B only")
    assert await BaselineService.status(db_session, test_family.id) == []


async def test_urls_for_ai_newest_first_capped(client, db_session, test_family, test_parent_user, auth_headers, other_parent):
    t = await _template(db_session, test_family)
    urls = []
    for i in range(MAX_BASELINES_PER_TEMPLATE):
        urls.append((await _upload(client, auth_headers, t.id)).json()["image_url"])
        row = (await db_session.execute(
            select(ChoreBaseline).where(ChoreBaseline.image_url == urls[-1]))).scalar_one()
        row.created_at = datetime.now(timezone.utc) - timedelta(days=10 - i)
        await db_session.commit()
    got = await BaselineService.urls_for_ai(db_session, test_family.id, t.id)
    assert got == list(reversed(urls))[:MAX_BASELINES_TO_AI]
    assert await BaselineService.urls_for_ai(db_session, other_parent[0].id, t.id) == []


async def test_export_registry_and_model_insert(db_session, test_family):
    assert "chore_baselines" in EXPORTED_FAMILY_TABLES
    t = await _template(db_session, test_family)
    db_session.add(ChoreBaseline(family_id=test_family.id, template_id=t.id,
                                 image_url="/uploads/chore-baselines/x.jpg", position=0))
    await db_session.commit()
    assert (await db_session.execute(select(func.count()).select_from(ChoreBaseline))).scalar_one() == 1


async def test_concurrent_adds_respect_cap(db_session, test_engine, test_family, test_parent_user):
    """Two overlapping adds with 3 existing: exactly one wins, the other gets
    baseline_limit (the template row lock serializes count+insert)."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.exceptions import BaselineLimitException

    t = await _template(db_session, test_family)
    for i in range(MAX_BASELINES_PER_TEMPLATE - 1):
        db_session.add(ChoreBaseline(family_id=test_family.id, template_id=t.id,
                                     image_url=f"/uploads/chore-baselines/s{i}.jpg", position=i))
    await db_session.commit()

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def one():
        async with maker() as s:
            user = await s.get(User, test_parent_user.id)
            return await BaselineService.add(s, user, t.id, _jpeg(), "image/jpeg", None)

    res = await asyncio.gather(one(), one(), return_exceptions=True)
    assert sum(isinstance(r, ChoreBaseline) for r in res) == 1, res
    assert sum(isinstance(r, BaselineLimitException) for r in res) == 1, res
    rows = (await db_session.execute(
        select(ChoreBaseline.position).where(ChoreBaseline.template_id == t.id))).scalars().all()
    assert len(rows) == MAX_BASELINES_PER_TEMPLATE and len(set(rows)) == len(rows)


async def test_failed_commit_removes_written_files(db_session, test_family, test_parent_user, monkeypatch):
    t = await _template(db_session, test_family)
    seen = []
    async def boom_commit():
        raise RuntimeError("db down")

    orig_write = __import__("app.core.async_fs", fromlist=["x"]).write_bytes

    async def spy(path, data):
        seen.append(path)
        await orig_write(path, data)

    monkeypatch.setattr("app.services.baseline_service.async_fs.write_bytes", spy)
    monkeypatch.setattr(db_session, "commit", boom_commit)
    with pytest.raises(RuntimeError):
        await BaselineService.add(db_session, test_parent_user, t.id, _jpeg(), "image/jpeg", "  ")
    assert len(seen) == 2 and not any(os.path.exists(p) for p in seen)


async def test_blank_caption_becomes_null(client, db_session, test_family, test_parent_user, auth_headers):
    t = await _template(db_session, test_family)
    r = await _upload(client, auth_headers, t.id, caption="   ")
    assert r.status_code == 201 and r.json()["caption"] is None
