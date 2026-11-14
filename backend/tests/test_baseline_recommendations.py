"""POST /api/task-templates/{id}/baselines/recommendations: AI tips, stores nothing."""
import io
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select

from app.core.security import get_password_hash
from app.models.chore_baseline import ChoreBaseline
from app.models.family import Family
from app.models.notification import Notification
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


def _jpeg(color=(10, 120, 10)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "UPLOADS_ROOT", str(tmp_path))
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
    (tmp_path / "chore-baselines").mkdir()
    (tmp_path / "gig-proofs").mkdir()
    return tmp_path


@pytest.fixture
def llm():
    with patch("app.core.llm.OpenAI") as mock_openai:
        c = MagicMock()
        mock_openai.return_value = c
        create = c.chat.completions.create

        def set_content(content):
            msg = MagicMock()
            msg.content = content
            choice = MagicMock()
            choice.message = msg
            completion = MagicMock()
            completion.choices = [choice]
            create.return_value = completion

        create.set_content = set_content
        set_content('{"suggestions": ["Tuck the corners", "Smooth the pillow"]}')
        yield create


async def _consent(db, family, value=True):
    family.ai_processing_consent = value
    await db.commit()


async def _template(db, family, title="Make bed"):
    t = TaskTemplate(title=title, description="Neat bed", family_id=family.id, requires_proof=True, points=5)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


def _url(t):
    return f"/api/task-templates/{t.id}/baselines/recommendations"


async def _seed(db, uploads, family, child, tmpl, n_baselines=2, n_proofs=4):
    for i in range(n_baselines):
        name = f"b{i}.jpg"
        (uploads / "chore-baselines" / name).write_bytes(_jpeg((i * 40, 0, 0)))
        db.add(ChoreBaseline(
            family_id=family.id, template_id=tmpl.id, image_url=f"/uploads/chore-baselines/{name}",
            position=i,
        ))
    today = date.today()
    for i in range(n_proofs):
        name = f"p{i}.jpg"
        (uploads / "gig-proofs" / name).write_bytes(_jpeg((0, i * 40, 0)))
        db.add(TaskAssignment(
            template_id=tmpl.id, assigned_to=child.id, family_id=family.id,
            status=AssignmentStatus.COMPLETED, approval_status=ApprovalStatus.APPROVED,
            assigned_date=today - timedelta(days=i), week_of=today - timedelta(days=today.weekday()),
            proof_image_url=f"/uploads/gig-proofs/{name}", completion_grade="partial",
            approval_notes=f"note-{i}", ai_validation_notes=f"ai-{i}",
        ))
    await db.commit()


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_happy_path_parsed_and_capped(
    client, db_session, test_family, test_parent_user, auth_headers, plus_subscription, uploads, llm
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    llm.set_content(json.dumps({"suggestions": [f"tip {i} " + "x" * 300 for i in range(8)]}))
    r = await client.post(_url(t), headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_failed"] is False
    assert len(body["suggestions"]) == 5
    assert all(len(s) <= 160 for s in body["suggestions"])
    assert body["suggestions"][0].startswith("tip 0")


async def test_parses_fenced_json_and_drops_junk(
    client, db_session, test_family, test_parent_user, auth_headers, plus_subscription, uploads, llm
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    llm.set_content('```json\n{"suggestions": ["ok", "", 5, "  fine  "]}\n```')
    r = await client.post(_url(t), headers=auth_headers)
    assert r.json() == {"suggestions": ["ok", "fine"], "ai_failed": False}


@pytest.mark.parametrize(
    "content", [None, "", "not json at all", '{"suggestions": "nope"}', '{"x": 1}', '{"suggestions": []}']
)
async def test_garbage_is_ai_failed(
    client, db_session, test_family, test_parent_user, auth_headers, plus_subscription, uploads, llm, content
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    llm.set_content(content)
    r = await client.post(_url(t), headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"suggestions": [], "ai_failed": True}


async def test_llm_exception_is_ai_failed(
    client, db_session, test_family, test_parent_user, auth_headers, plus_subscription, uploads, llm
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    llm.side_effect = RuntimeError("boom")
    r = await client.post(_url(t), headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"suggestions": [], "ai_failed": True}


async def test_timeout_is_ai_failed(
    client, db_session, test_family, test_parent_user, auth_headers, plus_subscription, uploads, llm, monkeypatch
):
    import time

    from app.services import baseline_advisor

    monkeypatch.setattr(baseline_advisor, "ADVISOR_LLM_TIMEOUT_SECONDS", 0.05)
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    llm.side_effect = lambda **kw: time.sleep(0.5)
    r = await client.post(_url(t), headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"suggestions": [], "ai_failed": True}


async def test_free_plan_is_upgrade_required(
    client, db_session, test_family, test_parent_user, auth_headers, uploads, llm
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    r = await client.post(_url(t), headers=auth_headers)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "upgrade_required"
    llm.assert_not_called()


async def test_no_consent_blocks_before_llm(
    client, db_session, test_family, test_parent_user, auth_headers, plus_subscription, uploads, llm
):
    await _consent(db_session, test_family, False)
    t = await _template(db_session, test_family)
    r = await client.post(_url(t), headers=auth_headers)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "ai_consent_required"
    llm.assert_not_called()


async def test_kid_is_403(
    client, db_session, test_family, test_parent_user, test_child_user, plus_subscription, uploads, llm
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    kid = await _login(client, "child@test.com")
    assert (await client.post(_url(t), headers=kid)).status_code == 403
    llm.assert_not_called()


async def test_other_familys_template_is_404(
    client, db_session, test_family, test_parent_user, auth_headers, plus_subscription, uploads, llm
):
    await _consent(db_session, test_family)
    other = Family(name="Other")
    db_session.add(other)
    await db_session.commit()
    t = await _template(db_session, other, title="Theirs")
    r = await client.post(_url(t), headers=auth_headers)
    assert r.status_code == 404
    llm.assert_not_called()


async def test_request_has_baselines_then_proofs_and_context(
    client, db_session, test_family, test_parent_user, test_child_user, auth_headers,
    plus_subscription, uploads, llm
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    await _seed(db_session, uploads, test_family, test_child_user, t, n_baselines=2, n_proofs=4)
    # another family's proof must never leak in
    other = Family(name="Other")
    db_session.add(other)
    await db_session.commit()
    ou = User(email="o@test.com", password_hash=get_password_hash("password123"), name="O",
              role=UserRole.CHILD, family_id=other.id, email_verified=True, points=0)
    db_session.add(ou)
    await db_session.commit()
    (uploads / "gig-proofs" / "leak.jpg").write_bytes(_jpeg((255, 255, 255)))
    db_session.add(TaskAssignment(
        template_id=t.id, assigned_to=ou.id, family_id=other.id, status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.APPROVED, assigned_date=date.today(), week_of=date.today(),
        proof_image_url="/uploads/gig-proofs/leak.jpg", approval_notes="LEAK",
    ))
    await db_session.commit()

    r = await client.post(_url(t), headers=auth_headers)
    assert r.status_code == 200, r.text
    kw = llm.call_args.kwargs
    assert kw["max_tokens"] == 8192
    content = kw["messages"][0]["content"]
    imgs = [p for p in content if p["type"] == "image_url"]
    assert len(imgs) == 2 + 3  # 2 baselines + last 3 proofs (4th and other family's excluded)
    text = [p for p in content if p["type"] == "text"][0]["text"]
    assert "Make bed" in text and "Neat bed" in text
    assert "note-0" in text and "ai-0" in text and "partial" in text
    assert "note-3" not in text
    assert "LEAK" not in text


async def test_language_follows_parent(
    client, db_session, test_family, test_parent_user, auth_headers, plus_subscription, uploads, llm
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    test_parent_user.preferred_lang = "en"
    await db_session.commit()
    await client.post(_url(t), headers=auth_headers)
    text = [p for p in llm.call_args.kwargs["messages"][0]["content"] if p["type"] == "text"][0]["text"]
    assert "English" in text
    test_parent_user.preferred_lang = "es"
    await db_session.commit()
    await client.post(_url(t), headers=auth_headers)
    text = [p for p in llm.call_args.kwargs["messages"][0]["content"] if p["type"] == "text"][0]["text"]
    assert "Spanish" in text


async def test_stores_nothing(
    client, db_session, test_family, test_parent_user, test_child_user, auth_headers,
    plus_subscription, uploads, llm
):
    await _consent(db_session, test_family)
    t = await _template(db_session, test_family)
    await _seed(db_session, uploads, test_family, test_child_user, t)

    async def counts():
        out = []
        for m in (ChoreBaseline, TaskAssignment, TaskTemplate, Notification):
            out.append((await db_session.execute(select(func.count()).select_from(m))).scalar_one())
        return out

    before = await counts()
    files = sorted(p.name for p in uploads.rglob("*"))
    assert (await client.post(_url(t), headers=auth_headers)).status_code == 200
    assert await counts() == before
    assert sorted(p.name for p in uploads.rglob("*")) == files
