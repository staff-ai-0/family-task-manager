"""Gemini review of photo proof on proof-required chores, plus the vision
downscale that keeps every review fast.

Chores with ``requires_proof`` park in the parent queue and award nothing until
a parent grades them. The AI review is ADVISORY there: it stores a score and a
one-line note for the parent and never approves, never credits points.
Bonus tasks (gigs) keep their own inline auto-approve path and are skipped here.
"""

import asyncio
import io
from datetime import date, timedelta

import pytest

from app.core.thumbnails import downscale_for_vision
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.services.task_assignment_service import TaskAssignmentService
from app.services.task_proof_validator import ProofValidation


def _jpeg(width: int, height: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (120, 80, 40)).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


class TestDownscaleForVision:
    def test_shrinks_a_phone_sized_photo(self):
        big = _jpeg(4032, 3024)
        out = downscale_for_vision(big, max_dim=1280)
        assert out is not None
        data, media_type = out
        assert media_type == "image/jpeg"
        assert len(data) < len(big)
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            assert max(im.size) == 1280

    def test_never_upscales(self):
        small = _jpeg(400, 300)
        out = downscale_for_vision(small, max_dim=1280)
        assert out is not None
        from PIL import Image

        with Image.open(io.BytesIO(out[0])) as im:
            assert im.size == (400, 300)

    def test_garbage_returns_none(self):
        assert downscale_for_vision(b"not an image") is None


async def _seed_chore(db, family, child, *, requires_proof=True, is_bonus=False):
    tmpl = TaskTemplate(
        title="Make the bed",
        points=10,
        interval_days=1,
        is_bonus=is_bonus,
        requires_proof=requires_proof,
        family_id=family.id,
    )
    db.add(tmpl)
    await db.flush()
    today = date.today()
    a = TaskAssignment(
        template_id=tmpl.id,
        assigned_to=child.id,
        family_id=family.id,
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.PENDING,
        assigned_date=today,
        week_of=today - timedelta(days=today.weekday()),
        proof_image_url="/uploads/gig-proofs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg",
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return tmpl, a


@pytest.fixture
def spy(monkeypatch):
    calls: list = []
    result = {"value": ProofValidation(score=0.9, explanation="Cama hecha")}

    async def fake(url, title, description=None):
        calls.append((url, title))
        return result["value"]

    monkeypatch.setattr("app.services.task_proof_validator.validate_proof_photo", fake)
    fake.calls = calls
    fake.result = result
    return fake


class TestReviewChoreProof:
    async def test_stores_advisory_score_and_never_approves(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user)
        test_child_user.points = 0
        await db_session.commit()

        await TaskAssignmentService.review_chore_proof(db_session, a.id)

        await db_session.refresh(a)
        assert a.ai_validation_score == pytest.approx(0.9)
        assert a.ai_validation_notes == "Cama hecha"
        assert a.approval_status == ApprovalStatus.PENDING  # a parent still grades
        await db_session.refresh(test_child_user)
        assert test_child_user.points == 0
        assert [c[1] for c in spy.calls] == ["Make the bed"]

    async def test_low_score_is_stored_too(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user)
        spy.result["value"] = ProofValidation(score=0.05, explanation="Es un selfie")

        await TaskAssignmentService.review_chore_proof(db_session, a.id)

        await db_session.refresh(a)
        assert a.ai_validation_score == pytest.approx(0.05)
        assert a.approval_status == ApprovalStatus.PENDING

    async def test_no_consent_makes_no_call(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        _, a = await _seed_chore(db_session, test_family, test_child_user)
        await TaskAssignmentService.review_chore_proof(db_session, a.id)
        assert spy.calls == []
        await db_session.refresh(a)
        assert a.ai_validation_score is None

    async def test_free_plan_makes_no_call(
        self, db_session, test_family, test_child_user, spy
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user)
        await TaskAssignmentService.review_chore_proof(db_session, a.id)
        assert spy.calls == []

    async def test_gigs_are_left_to_the_inline_path(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user, is_bonus=True)
        await TaskAssignmentService.review_chore_proof(db_session, a.id)
        assert spy.calls == []

    async def test_chore_without_proof_requirement_is_skipped(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user, requires_proof=False)
        await TaskAssignmentService.review_chore_proof(db_session, a.id)
        assert spy.calls == []

    async def test_already_reviewed_is_not_reviewed_again(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user)
        a.ai_validation_score = 0.5
        await db_session.commit()
        await TaskAssignmentService.review_chore_proof(db_session, a.id)
        assert spy.calls == []

    async def test_no_signal_leaves_row_untouched(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user)
        spy.result["value"] = None
        await TaskAssignmentService.review_chore_proof(db_session, a.id)
        await db_session.refresh(a)
        assert a.ai_validation_score is None

    async def test_a_validator_crash_never_propagates(
        self, db_session, test_family, test_child_user, plus_subscription, monkeypatch
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user)

        async def boom(*_a, **_k):
            raise RuntimeError("provider down")

        monkeypatch.setattr("app.services.task_proof_validator.validate_proof_photo", boom)
        await TaskAssignmentService.review_chore_proof(db_session, a.id)  # must not raise


class TestValidatorIsBounded:
    async def test_a_hung_provider_yields_no_signal(self, monkeypatch):
        from app.services import task_proof_validator as v

        monkeypatch.setattr(v.settings, "LITELLM_API_KEY", "sk-test")
        monkeypatch.setattr(v, "PROOF_LLM_TIMEOUT_SECONDS", 0.05)

        async def img(_url):
            return _jpeg(200, 200), "image/jpeg"

        monkeypatch.setattr(v, "_load_image_bytes", img)

        class Slow:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_k):
                        import time

                        time.sleep(0.5)

        monkeypatch.setattr(v, "get_llm_client", lambda: Slow())
        result = await asyncio.wait_for(v.validate_proof_photo("/uploads/x.jpg", "Make bed"), 2)
        assert result is None

    async def test_sends_a_downscaled_image_with_room_for_thinking_tokens(self, monkeypatch):
        from app.services import task_proof_validator as v

        monkeypatch.setattr(v.settings, "LITELLM_API_KEY", "sk-test")
        big = _jpeg(4032, 3024)

        async def img(_url):
            return big, "image/jpeg"

        monkeypatch.setattr(v, "_load_image_bytes", img)
        seen = {}

        class Msg:
            content = '{"score": 0.8, "explanation": "ok"}'

        class Choice:
            message = Msg()
            finish_reason = "stop"

        class Completion:
            choices = [Choice()]

        class Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        seen.update(kw)
                        return Completion()

        monkeypatch.setattr(v, "get_llm_client", lambda: Client())
        result = await v.validate_proof_photo("/uploads/x.jpg", "Make bed")
        assert result is not None and result.score == pytest.approx(0.8)
        uri = seen["messages"][0]["content"][0]["image_url"]["url"]
        assert len(uri) < len(big)  # base64 of the SHRUNK image, not the original
        assert seen["max_tokens"] >= 2048


class TestCompleteRouteSchedulesReview:
    """The kid's request must return without waiting on Gemini: the route only
    SCHEDULES the review. (The review itself is covered above.)"""

    async def _kid_headers(self, client):
        login = await client.post(
            "/api/auth/login",
            json={"email": "child@test.com", "password": "password123"},
        )
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    async def test_proof_completion_schedules_one_review(
        self, client, db_session, test_family, test_child_user, monkeypatch
    ):
        import uuid

        tmpl = TaskTemplate(
            title="Clean the bathroom", points=20, interval_days=1,
            requires_proof=True, is_bonus=False, family_id=test_family.id,
        )
        db_session.add(tmpl)
        await db_session.flush()
        today = date.today()
        a = TaskAssignment(
            template_id=tmpl.id, assigned_to=test_child_user.id,
            family_id=test_family.id, status=AssignmentStatus.PENDING,
            assigned_date=today, week_of=today - timedelta(days=today.weekday()),
        )
        db_session.add(a)
        await db_session.commit()

        scheduled: list = []

        async def spy(assignment_id):
            scheduled.append(assignment_id)

        monkeypatch.setattr(
            TaskAssignmentService, "review_chore_proof_background", staticmethod(spy)
        )
        r = await client.patch(
            f"/api/task-assignments/{a.id}/complete",
            json={
                "proof_text": "listo",
                "proof_image_url": f"/uploads/gig-proofs/{uuid.uuid4().hex}.jpg",
            },
            headers=await self._kid_headers(client),
        )
        assert r.status_code == 200, r.text
        assert scheduled == [a.id]

    async def test_chore_without_photo_schedules_nothing(
        self, client, db_session, test_family, test_child_user, monkeypatch
    ):
        tmpl = TaskTemplate(
            title="Feed the dog", points=5, interval_days=1,
            requires_proof=False, is_bonus=False, family_id=test_family.id,
        )
        db_session.add(tmpl)
        await db_session.flush()
        today = date.today()
        a = TaskAssignment(
            template_id=tmpl.id, assigned_to=test_child_user.id,
            family_id=test_family.id, status=AssignmentStatus.PENDING,
            assigned_date=today, week_of=today - timedelta(days=today.weekday()),
        )
        db_session.add(a)
        await db_session.commit()

        scheduled: list = []

        async def spy(assignment_id):
            scheduled.append(assignment_id)

        monkeypatch.setattr(
            TaskAssignmentService, "review_chore_proof_background", staticmethod(spy)
        )
        r = await client.patch(
            f"/api/task-assignments/{a.id}/complete",
            json={},
            headers=await self._kid_headers(client),
        )
        assert r.status_code == 200, r.text
        assert scheduled == []
