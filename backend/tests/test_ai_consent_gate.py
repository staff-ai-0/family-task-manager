"""Parental opt-in gate for AI processing of kid-generated content (WS-OPTIN).

families.ai_processing_consent (default false) gates:
  1. AI gig-proof photo validation (task_proof_validator) — consent false
     means NO LLM call and the gig lands in the manual parent-approval queue.
  2. Jarvis/MCP chat reads (chat_message list/get) — consent false returns an
     'AI access disabled' result instead of message content.

Consent is captured via PATCH /api/families/me (parent only); either decision
stamps ai_processing_consent_at so 'never asked' (NULL) is distinguishable.
"""

import pytest
from datetime import date, timedelta
from httpx import AsyncClient
from sqlalchemy import select

from app.mcp.adapters_chat import AI_CHAT_ACCESS_DISABLED, MessageAdapter
from app.mcp.context import McpContext
from app.models.family import Family
from app.models.task_assignment import (
    TaskAssignment,
    AssignmentStatus,
    ApprovalStatus,
)
from app.models.task_template import TaskTemplate
from app.services.family_chat_service import FamilyChatService
from app.services.task_assignment_service import TaskAssignmentService


async def _seed_gig(db, family, child):
    tmpl = TaskTemplate(
        title="Rake the leaves",
        points=10,
        interval_days=7,
        is_bonus=True,
        family_id=family.id,
    )
    db.add(tmpl)
    await db.flush()
    today = date.today()
    week_monday = today - timedelta(days=today.weekday())
    a = TaskAssignment(
        template_id=tmpl.id,
        assigned_to=child.id,
        family_id=family.id,
        status=AssignmentStatus.PENDING,
        assigned_date=today,
        week_of=week_monday,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return tmpl, a


# ---------------------------------------------------------------------------
# 1. Gig proof photo validation gate
# ---------------------------------------------------------------------------


class TestProofValidatorConsentGate:
    async def test_consent_false_makes_no_llm_call_and_queues_manual(
        self, db_session, test_family, test_child_user, monkeypatch
    ):
        """Default (consent unset/false): no AI call at all; proof goes to the
        existing manual parent-approval queue."""
        assert test_family.ai_processing_consent is False  # migration default

        test_child_user.gig_trust_streak = 0
        test_child_user.points = 0
        await db_session.commit()
        tmpl, a = await _seed_gig(db_session, test_family, test_child_user)

        calls: list = []

        async def spy_validate(url, title, description=None):
            calls.append(url)
            from app.services.task_proof_validator import ProofValidation
            return ProofValidation(score=0.99, explanation="should never run")

        monkeypatch.setattr(
            "app.services.task_proof_validator.validate_proof_photo",
            spy_validate,
        )

        result = await TaskAssignmentService.complete_assignment(
            db_session,
            a.id,
            test_family.id,
            test_child_user.id,
            proof_text="raked everything",
            proof_image_url="/uploads/gig-proofs/synthetic.jpg",
        )

        assert calls == []  # gate honored: validator never invoked
        assert result.approval_status == ApprovalStatus.PENDING  # manual HITL
        assert result.ai_validation_score is None
        assert result.ai_validation_notes is None
        await db_session.refresh(test_child_user)
        assert test_child_user.points == 0  # nothing credited yet

    async def test_consent_true_uses_ai_path(
        self, db_session, test_family, test_child_user, plus_subscription, monkeypatch
    ):
        """With parental opt-in (and a paid plan — see test_ai_gating for the
        plan gate), the AI validator runs and can auto-approve."""
        test_family.ai_processing_consent = True
        test_child_user.gig_trust_streak = 0
        test_child_user.points = 0
        await db_session.commit()
        tmpl, a = await _seed_gig(db_session, test_family, test_child_user)

        calls: list = []

        async def fake_validate(url, title, description=None):
            calls.append(url)
            from app.services.task_proof_validator import ProofValidation
            return ProofValidation(score=0.95, explanation="Leaves raked.")

        monkeypatch.setattr(
            "app.services.task_proof_validator.validate_proof_photo",
            fake_validate,
        )

        result = await TaskAssignmentService.complete_assignment(
            db_session,
            a.id,
            test_family.id,
            test_child_user.id,
            proof_text="raked everything",
            proof_image_url="/uploads/gig-proofs/synthetic.jpg",
        )

        assert len(calls) == 1
        assert result.approval_status == ApprovalStatus.APPROVED
        assert result.ai_validation_score == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# 2. Jarvis/MCP chat read gate
# ---------------------------------------------------------------------------


class TestMcpChatReadConsentGate:
    async def test_consent_false_blocks_chat_reads(
        self, db_session, test_family, test_child_user
    ):
        """Without opt-in, list/get return a disabled marker — never content."""
        msg = await FamilyChatService.post_message(
            db_session,
            family_id=test_family.id,
            sender_id=test_child_user.id,
            body="secret kid message",
        )

        ctx = McpContext(
            family_id=test_family.id,
            user_id=test_child_user.id,
            role="PARENT",
            db=db_session,
        )
        adapter = MessageAdapter()

        listed = await adapter.list(ctx)
        assert listed == [AI_CHAT_ACCESS_DISABLED]
        assert all("secret kid message" not in str(row.get("body", "")) for row in listed)

        got = await adapter.get(ctx, msg.id)
        assert got == AI_CHAT_ACCESS_DISABLED
        assert "body" not in got

    async def test_consent_true_allows_chat_reads(
        self, db_session, test_family, test_child_user
    ):
        test_family.ai_processing_consent = True
        await db_session.commit()

        msg = await FamilyChatService.post_message(
            db_session,
            family_id=test_family.id,
            sender_id=test_child_user.id,
            body="hola familia",
        )

        ctx = McpContext(
            family_id=test_family.id,
            user_id=test_child_user.id,
            role="PARENT",
            db=db_session,
        )
        adapter = MessageAdapter()

        listed = await adapter.list(ctx)
        assert any(row.get("id") == str(msg.id) for row in listed)

        got = await adapter.get(ctx, msg.id)
        assert got["body"] == "hola familia"

    async def test_consent_false_still_allows_posting(
        self, db_session, test_family, test_parent_user
    ):
        """Create is NOT gated: Jarvis posting on the parent's behalf does not
        read kid content."""
        ctx = McpContext(
            family_id=test_family.id,
            user_id=test_parent_user.id,
            role="PARENT",
            db=db_session,
        )
        created = await MessageAdapter().create(ctx, {"body": "dinner at 8"})
        assert created["body"] == "dinner at 8"


# ---------------------------------------------------------------------------
# 3. Consent capture endpoint (PATCH /api/families/me)
# ---------------------------------------------------------------------------


class TestConsentToggleEndpoint:
    @pytest.mark.asyncio
    async def test_defaults_exposed_and_unset(
        self, client: AsyncClient, auth_headers
    ):
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["ai_processing_consent"] is False
        assert body["ai_processing_consent_at"] is None  # never asked

    @pytest.mark.asyncio
    async def test_parent_opt_in_stamps_timestamp(
        self, client: AsyncClient, auth_headers, db_session, test_family
    ):
        r = await client.patch(
            "/api/families/me",
            json={"ai_processing_consent": True},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ai_processing_consent"] is True
        assert body["ai_processing_consent_at"] is not None

        row = (
            await db_session.execute(
                select(Family).where(Family.id == test_family.id)
            )
        ).scalar_one()
        assert row.ai_processing_consent is True
        assert row.ai_processing_consent_at is not None

    @pytest.mark.asyncio
    async def test_parent_opt_out_also_stamps_timestamp(
        self, client: AsyncClient, auth_headers
    ):
        """An explicit 'no' is a decision too — timestamp set so the dashboard
        banner never re-prompts."""
        r = await client.patch(
            "/api/families/me",
            json={"ai_processing_consent": False},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ai_processing_consent"] is False
        assert body["ai_processing_consent_at"] is not None

    @pytest.mark.asyncio
    async def test_unrelated_update_does_not_stamp_decision(
        self, client: AsyncClient, auth_headers
    ):
        r = await client.patch(
            "/api/families/me",
            json={"timezone": "America/Mexico_City"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["ai_processing_consent_at"] is None

    @pytest.mark.asyncio
    async def test_child_cannot_toggle_consent(
        self, client: AsyncClient, test_child_user
    ):
        login = await client.post(
            "/api/auth/login",
            json={"email": "child@test.com", "password": "password123"},
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = await client.patch(
            "/api/families/me",
            json={"ai_processing_consent": True},
            headers=headers,
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_parent_cannot_toggle_other_family_via_legacy_put(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Family-scoped: legacy PUT /{family_id} against another family must
        be rejected."""
        other = Family(name="Other AI Family")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        r = await client.put(
            f"/api/families/{other.id}",
            json={"ai_processing_consent": True},
            headers=auth_headers,
        )
        assert r.status_code in (403, 404)

        row = (
            await db_session.execute(select(Family).where(Family.id == other.id))
        ).scalar_one()
        assert row.ai_processing_consent is False
