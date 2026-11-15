"""AI proof review compares the kid's photo against the family's baselines."""

import base64
import io
import os
from unittest.mock import MagicMock, patch

import pytest

from app.models.chore_baseline import ChoreBaseline
from app.models.family import Family
from app.services.task_assignment_service import TaskAssignmentService
from app.services.task_proof_validator import ProofValidation, validate_proof_photo
from tests.test_proof_chore_ai_review import _seed_chore


def _jpeg(color) -> bytes:
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


def _write(uploads, rel, color):
    (uploads / rel).write_bytes(_jpeg(color))
    return "/uploads/" + rel


@pytest.fixture
def llm():
    with patch("app.core.llm.OpenAI") as mock_openai:
        msg = MagicMock()
        msg.content = '{"score": 0.8, "explanation": "ok"}'
        choice = MagicMock()
        choice.message = msg
        completion = MagicMock()
        completion.choices = [choice]
        c = MagicMock()
        c.chat.completions.create.return_value = completion
        mock_openai.return_value = c
        yield c.chat.completions.create


def _content(create):
    return create.call_args.kwargs["messages"][0]["content"]


def _images(content):
    return [p for p in content if p["type"] == "image_url"]


def _text(content):
    return [p for p in content if p["type"] == "text"][0]["text"]


def _pixel(uri):
    from PIL import Image

    raw = base64.b64decode(uri.split(",", 1)[1])
    return Image.open(io.BytesIO(raw)).convert("RGB").getpixel((5, 5))


class TestValidatorBaselines:
    async def test_baselines_precede_proof_and_prompt_mentions_reference(self, uploads, llm):
        b1 = _write(uploads, "chore-baselines/b1.jpg", (255, 0, 0))
        b2 = _write(uploads, "chore-baselines/b2.jpg", (0, 255, 0))
        proof = _write(uploads, "gig-proofs/p.jpg", (0, 0, 255))
        res = await validate_proof_photo(proof, "Make bed", None, baseline_urls=[b1, b2])
        assert res is not None and res.score == pytest.approx(0.8)
        content = _content(llm)
        imgs = _images(content)
        assert len(imgs) == 3
        uris = [i["image_url"]["url"] for i in imgs]
        r, g, b = _pixel(uris[0])
        assert r > 200 and g < 60 and b < 60
        r, g, b = _pixel(uris[1])
        assert g > 200 and r < 60 and b < 60
        # proof LAST
        r, g, b = _pixel(uris[2])
        assert b > 200 and r < 60 and g < 60
        text = _text(content).lower()
        assert "reference" in text and "2" in text

    async def test_validator_caps_baselines_at_three(self, uploads, llm):
        urls = [
            _write(uploads, f"chore-baselines/c{i}.jpg", (255, 0, 0)) for i in range(5)
        ]
        proof = _write(uploads, "gig-proofs/p.jpg", (0, 0, 255))
        await validate_proof_photo(proof, "Make bed", None, baseline_urls=urls)
        assert len(_images(_content(llm))) == 4  # 3 baselines + proof

    async def test_traversal_url_is_never_read(self, uploads, llm, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside")
        (outside / "secret.jpg").write_bytes(_jpeg((255, 0, 0)))
        rel = os.path.relpath(outside / "secret.jpg", uploads)
        evil = "/uploads/" + rel
        assert ".." in evil
        proof = _write(uploads, "gig-proofs/p.jpg", (0, 0, 255))
        await validate_proof_photo(proof, "Make bed", None, baseline_urls=[evil])
        assert len(_images(_content(llm))) == 1
        from app.services.task_proof_validator import _strip_local_prefix

        assert _strip_local_prefix(evil) is None

    async def test_zero_baselines_same_shape_as_today(self, uploads, llm):
        proof = _write(uploads, "gig-proofs/p.jpg", (0, 0, 255))
        await validate_proof_photo(proof, "Make bed", None)
        content = _content(llm)
        assert len(_images(content)) == 1
        assert "reference" not in _text(content).lower()

    async def test_unreadable_baseline_is_skipped(self, uploads, llm):
        good = _write(uploads, "chore-baselines/ok.jpg", (255, 0, 0))
        missing = "/uploads/chore-baselines/nope.jpg"
        (uploads / "chore-baselines" / "bad.jpg").write_bytes(b"not an image")
        bad = "/uploads/chore-baselines/bad.jpg"
        proof = _write(uploads, "gig-proofs/p.jpg", (0, 0, 255))
        res = await validate_proof_photo(
            proof, "Make bed", None, baseline_urls=[missing, bad, good]
        )
        assert res is not None
        content = _content(llm)
        assert len(_images(content)) == 2
        assert "first 1 image" in _text(content).lower()

    async def test_all_baselines_unreadable_equals_today(self, uploads, llm):
        proof = _write(uploads, "gig-proofs/p.jpg", (0, 0, 255))
        await validate_proof_photo(
            proof, "Make bed", None, baseline_urls=["/uploads/chore-baselines/x.jpg"]
        )
        content = _content(llm)
        assert len(_images(content)) == 1
        assert "reference" not in _text(content).lower()


@pytest.fixture
def spy(monkeypatch):
    calls: list = []

    async def fake(url, title, description=None, baseline_urls=()):
        calls.append(list(baseline_urls))
        return ProofValidation(score=0.7, explanation="x")

    monkeypatch.setattr("app.services.task_proof_validator.validate_proof_photo", fake)
    fake.calls = calls
    return fake


class TestReviewChoreProofBaselines:
    async def test_passes_template_baselines_family_scoped(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        test_family.ai_processing_consent = True
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        tmpl, a = await _seed_chore(db_session, test_family, test_child_user)
        db_session.add(
            ChoreBaseline(
                family_id=test_family.id,
                template_id=tmpl.id,
                image_url="/uploads/chore-baselines/mine.jpg",
                position=0,
            )
        )
        db_session.add(
            ChoreBaseline(
                family_id=other.id,
                template_id=tmpl.id,
                image_url="/uploads/chore-baselines/theirs.jpg",
                position=0,
            )
        )
        await db_session.commit()

        await TaskAssignmentService.review_chore_proof(db_session, a.id)

        assert spy.calls == [["/uploads/chore-baselines/mine.jpg"]]

    async def test_no_consent_makes_no_call(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        _, a = await _seed_chore(db_session, test_family, test_child_user)
        await TaskAssignmentService.review_chore_proof(db_session, a.id)
        assert spy.calls == []

    async def test_no_baselines_passes_empty(
        self, db_session, test_family, test_child_user, plus_subscription, spy
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()
        _, a = await _seed_chore(db_session, test_family, test_child_user)
        await TaskAssignmentService.review_chore_proof(db_session, a.id)
        assert spy.calls == [[]]
