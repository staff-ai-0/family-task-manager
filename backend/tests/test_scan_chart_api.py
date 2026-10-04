"""UX-E1: the scan-chart endpoint — gate, upload rules, family scope, no writes."""
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import func, select

from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole

URL = "/api/task-templates/scan-chart"


def _completion(payload):
    msg = MagicMock(); msg.content = json.dumps(payload)
    choice = MagicMock(); choice.message = msg
    c = MagicMock(); c.choices = [choice]
    return c


def _vision(payload):
    patcher = patch("app.core.llm.OpenAI")
    mock_openai = patcher.start()
    client = MagicMock()
    client.chat.completions.create.return_value = _completion(payload)
    mock_openai.return_value = client
    return patcher, client


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _count_templates(db):
    return (await db.execute(select(func.count()).select_from(TaskTemplate))).scalar()


class TestScan:
    async def test_proposals_are_matched_and_flagged_and_nothing_is_written(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_parent_user, test_child_user, test_teen_user, monkeypatch,
    ):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        db_session.add(TaskTemplate(id=uuid4(), title="Feed the dog", points=10, interval_days=1, assignment_type=AssignmentType.AUTO,
                                    is_bonus=False, is_active=True, family_id=test_family.id))
        await db_session.commit()
        before = await _count_templates(db_session)
        patcher, llm = _vision({"doc_type": "chore_chart", "confidence": 0.9, "chores": [
            {"title": "feed the DOG", "points": 15, "days": ["mon"], "assignees": ["Test Child"]},
            {"title": "Take out trash", "points": 5, "days": ["weekends"], "assignees": ["Test Teen", "Nobody"]},
        ]})
        try:
            r = await client.post(URL, files={"file": ("chart.png", b"\x89PNG fake", "image/png")}, headers=auth_headers)
        finally:
            patcher.stop()
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["doc_type"] == "chore_chart" and body["confidence"] == 0.9 and len(body["chores"]) == 2
        a, b = body["chores"]
        assert a["assigned_user_ids"] == [str(test_child_user.id)] and a["duplicate_of"] is not None and a["days_of_week"] == [0]
        assert b["assigned_user_ids"] == [str(test_teen_user.id)] and b["unmatched_names"] == ["Nobody"] and b["duplicate_of"] is None
        assert b["days_of_week"] == [5, 6]
        assert await _count_templates(db_session) == before                      # the scan writes nothing
        prompt = llm.chat.completions.create.call_args.kwargs["messages"][0]["content"][1]["text"]
        assert "Test Child (child)" in prompt and "Test Parent (parent)" in prompt

    async def test_another_familys_members_and_chores_never_leak_in(
        self, client, db_session, auth_headers, plus_subscription, test_family, monkeypatch,
    ):
        from app.core import config
        from app.models.family import Family
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        stranger = User(email="stranger@test.com", password_hash="x", name="Zoe", role=UserRole.CHILD, family_id=other.id,
                        email_verified=True, points=0)
        db_session.add(stranger)
        db_session.add(TaskTemplate(id=uuid4(), title="Water plants", points=10, interval_days=1, assignment_type=AssignmentType.AUTO,
                                    is_bonus=False, is_active=True, family_id=other.id))
        await db_session.commit()
        patcher, llm = _vision({"confidence": 0.8, "chores": [{"title": "Water plants", "assignees": ["Zoe"]}]})
        try:
            r = await client.post(URL, files={"file": ("c.jpg", b"img", "image/jpeg")}, headers=auth_headers)
        finally:
            patcher.stop()
        c = r.json()["chores"][0]
        assert c["assigned_user_ids"] == [] and c["unmatched_names"] == ["Zoe"] and c["duplicate_of"] is None
        assert "Zoe" not in llm.chat.completions.create.call_args.kwargs["messages"][0]["content"][1]["text"]

    async def test_upload_rules(self, client, auth_headers, plus_subscription, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        assert (await client.post(URL, files={"file": ("c.txt", b"hello", "text/plain")}, headers=auth_headers)).status_code == 415
        assert (await client.post(URL, files={"file": ("c.png", b"", "image/png")}, headers=auth_headers)).status_code == 400

    async def test_model_failure_is_a_502(self, client, auth_headers, plus_subscription, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        with patch("app.core.llm.OpenAI") as mock_openai:
            c = MagicMock(); c.chat.completions.create.side_effect = RuntimeError("down"); mock_openai.return_value = c
            r = await client.post(URL, files={"file": ("c.png", b"img", "image/png")}, headers=auth_headers)
        assert r.status_code == 502

    async def test_kids_cannot_scan(self, client, test_child_user, plus_subscription):
        r = await client.post(URL, files={"file": ("c.png", b"img", "image/png")}, headers=await _login(client, "child@test.com"))
        assert r.status_code in (401, 403)
