"""AI access is a paid feature — free families must never reach the LLM.

Covers the 2026-07-16 gating audit leaks:
  1. POST /api/meals/recipes/import
  2. POST /api/budget/transactions/auto-categorize
  3. Jarvis schedules (create route + sweep_due executor)
  4. POST /api/task-templates/{id}/translate + auto-translate on create
  5. PUT /api/budget/a2a-webhook + bank-sync AI categorization

Free = family with no subscription row (resolves via DEFAULT_FREE_LIMITS).
Plus = active FamilySubscription on a plan with ai_features/a2a_webhook.
"""

import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models.a2a import FamilyA2AWebhook
from app.models.jarvis_schedule import JarvisSchedule


def _assert_upgrade_required(r):
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "upgrade_required"


# ---------------------------------------------------------------------------
# 1. Recipe import
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recipe_import_free_403(client: AsyncClient, auth_headers):
    r = await client.post(
        "/api/meals/recipes/import",
        json={"url": "https://example.com/recipe"},
        headers=auth_headers,
    )
    _assert_upgrade_required(r)


@pytest.mark.asyncio
async def test_recipe_import_plus_allowed(
    client: AsyncClient, auth_headers, plus_subscription, monkeypatch
):
    from app.services.recipe_importer import ImportedRecipe

    stub = ImportedRecipe(
        name="Tacos",
        description=None,
        ingredients_text="tortillas",
        prep_minutes=10,
        source_url="https://example.com/recipe",
        confidence=0.9,
    )
    monkeypatch.setattr(
        "app.api.routes.meals.import_recipe_from_url",
        AsyncMock(return_value=stub),
    )
    r = await client.post(
        "/api/meals/recipes/import",
        json={"url": "https://example.com/recipe"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Tacos"


# ---------------------------------------------------------------------------
# 2. Budget auto-categorize
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_categorize_free_403(client: AsyncClient, auth_headers):
    r = await client.post(
        "/api/budget/transactions/auto-categorize", headers=auth_headers
    )
    _assert_upgrade_required(r)


@pytest.mark.asyncio
async def test_auto_categorize_plus_allowed(
    client: AsyncClient, auth_headers, plus_subscription
):
    # No transactions and no LLM key — backfill returns counts without AI.
    r = await client.post(
        "/api/budget/transactions/auto-categorize", headers=auth_headers
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 3. Jarvis schedules — create route + sweep executor
# ---------------------------------------------------------------------------

SCHEDULE_PAYLOAD = {
    "name": "Resumen semanal",
    "prompt": "Dame un resumen de la semana",
    "cron_expr": "0 8 * * 1",
    "channel": "notification",
}


@pytest.mark.asyncio
async def test_schedule_create_free_403(client: AsyncClient, auth_headers):
    r = await client.post(
        "/api/jarvis/schedules/", json=SCHEDULE_PAYLOAD, headers=auth_headers
    )
    _assert_upgrade_required(r)


@pytest.mark.asyncio
async def test_schedule_create_plus_201(
    client: AsyncClient, auth_headers, plus_subscription
):
    r = await client.post(
        "/api/jarvis/schedules/", json=SCHEDULE_PAYLOAD, headers=auth_headers
    )
    assert r.status_code == 201, r.text


async def _due_schedule(db_session, family, user):
    s = JarvisSchedule(
        family_id=family.id,
        created_by=user.id,
        name="Due now",
        prompt="hola",
        cron_expr="0 8 * * *",
        channel="notification",
        is_active=True,
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


@pytest.mark.asyncio
async def test_sweep_due_skips_free_family(
    db_session, test_family, test_parent_user, monkeypatch
):
    from app.services.jarvis_schedule_service import JarvisScheduleService
    from app.services.jarvis_service import JarvisService

    chat = AsyncMock(return_value={"reply": "ok"})
    monkeypatch.setattr(JarvisService, "chat", chat)

    s = await _due_schedule(db_session, test_family, test_parent_user)
    fired = await JarvisScheduleService.sweep_due(db_session)

    assert chat.await_count == 0
    assert fired == 0
    # Schedule must still advance so it doesn't re-fire every sweep.
    await db_session.refresh(s)
    assert s.next_run_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_sweep_due_fires_plus_family(
    db_session, test_family, test_parent_user, plus_subscription, monkeypatch
):
    from app.services.jarvis_schedule_service import JarvisScheduleService
    from app.services.jarvis_service import JarvisService

    chat = AsyncMock(return_value={"reply": "ok"})
    monkeypatch.setattr(JarvisService, "chat", chat)

    await _due_schedule(db_session, test_family, test_parent_user)
    fired = await JarvisScheduleService.sweep_due(db_session)

    assert chat.await_count == 1
    assert fired == 1


# ---------------------------------------------------------------------------
# 4. Template translation — explicit endpoint + auto-translate on create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_template_translate_free_403(
    client: AsyncClient, auth_headers, test_family, mandatory_template_factory
):
    t = await mandatory_template_factory(family=test_family)
    r = await client.post(
        f"/api/task-templates/{t.id}/translate",
        json={"source_lang": "en", "target_lang": "es"},
        headers=auth_headers,
    )
    _assert_upgrade_required(r)


@pytest.mark.asyncio
async def test_template_translate_plus_allowed(
    client: AsyncClient,
    auth_headers,
    test_family,
    plus_subscription,
    mandatory_template_factory,
    monkeypatch,
):
    from app.services.translation_service import TranslationService

    monkeypatch.setattr(
        TranslationService,
        "translate_template_fields",
        AsyncMock(return_value={"title": "Lavar dientes", "description": None}),
    )
    t = await mandatory_template_factory(family=test_family)
    r = await client.post(
        f"/api/task-templates/{t.id}/translate",
        json={"source_lang": "en", "target_lang": "es"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_template_create_no_autotranslate_for_free(
    client: AsyncClient, auth_headers, monkeypatch
):
    from app.services.translation_service import TranslationService

    translate = AsyncMock(return_value={"title": "X", "description": None})
    monkeypatch.setattr(TranslationService, "translate_template_fields", translate)

    r = await client.post(
        "/api/task-templates/",
        json={"title": "Water the plants"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert translate.await_count == 0


@pytest.mark.asyncio
async def test_template_create_autotranslates_for_plus(
    client: AsyncClient, auth_headers, plus_subscription, monkeypatch
):
    from app.services.translation_service import TranslationService

    translate = AsyncMock(
        return_value={"title": "Regar las plantas", "description": None}
    )
    monkeypatch.setattr(TranslationService, "translate_template_fields", translate)

    r = await client.post(
        "/api/task-templates/",
        json={"title": "Water the plants"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert translate.await_count == 1
    assert r.json()["title_es"] == "Regar las plantas"


# ---------------------------------------------------------------------------
# 5. A2A webhook config + bank-sync AI categorization
# ---------------------------------------------------------------------------

A2A_SECRET = "test-secret-ai-gating-0123456789"


@pytest.mark.asyncio
async def test_a2a_webhook_put_free_403(client: AsyncClient, auth_headers):
    r = await client.put(
        "/api/budget/a2a-webhook",
        json={"url": "https://agent.example/hook", "enabled": True},
        headers=auth_headers,
    )
    _assert_upgrade_required(r)


@pytest.mark.asyncio
async def test_a2a_webhook_put_plus_allowed(
    client: AsyncClient, auth_headers, plus_subscription
):
    r = await client.put(
        "/api/budget/a2a-webhook",
        json={"url": "https://agent.example/hook", "enabled": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


def _a2a_sig(message: bytes) -> str:
    return "sha256=" + hmac.new(
        A2A_SECRET.encode(), message, hashlib.sha256
    ).hexdigest()


@pytest_asyncio.fixture
async def a2a_webhook_row(db_session, test_family):
    from app.models.budget import BudgetAccount

    db_session.add(
        FamilyA2AWebhook(
            family_id=test_family.id,
            url="https://agent.example/hook",
            secret=A2A_SECRET,
            enabled=True,
        )
    )
    db_session.add(
        BudgetAccount(
            family_id=test_family.id, name="Card", type="checking", sort_order=0
        )
    )
    await db_session.commit()
    return test_family


def _bank_alert_body() -> bytes:
    payload = {
        "merchant": "OXXO CENTRO",
        "amount_cents": 12345,
        "direction": "debit",
        "date": date.today().isoformat(),
        "currency": "MXN",
        "external_id": "bankalert:TEST:ai-gating:12345",
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


@pytest.mark.asyncio
async def test_bank_sync_create_skips_ai_for_free(
    client: AsyncClient, a2a_webhook_row, db_session, monkeypatch
):
    from app.services.budget.category_ai_service import CategoryAIService

    suggest = AsyncMock(return_value=None)
    monkeypatch.setattr(CategoryAIService, "suggest", suggest)

    body = _bank_alert_body()
    r = await client.post(
        "/api/budget/bank-sync/transactions",
        content=body,
        headers={
            "X-A2A-Family": str(a2a_webhook_row.id),
            "X-A2A-Signature": _a2a_sig(body),
        },
    )
    assert r.status_code == 200, r.text
    assert suggest.await_count == 0


# ---------------------------------------------------------------------------
# 6. Gig proof-photo AI validation (auto-approve) — paid-only on top of the
#    ai_processing_consent gate (see test_ai_consent_gate.py for consent).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gig_photo_ai_skipped_for_free(
    db_session, test_family, test_child_user, monkeypatch
):
    from app.models.task_assignment import ApprovalStatus
    from app.services.task_assignment_service import TaskAssignmentService
    from tests.test_ai_consent_gate import _seed_gig

    test_family.ai_processing_consent = True  # consent alone is not enough
    test_child_user.gig_trust_streak = 0
    await db_session.commit()
    tmpl, a = await _seed_gig(db_session, test_family, test_child_user)

    validate = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.services.task_proof_validator.validate_proof_photo", validate
    )

    result = await TaskAssignmentService.complete_assignment(
        db_session,
        a.id,
        test_family.id,
        test_child_user.id,
        proof_text="raked everything",
        proof_image_url="/uploads/gig-proofs/synthetic.jpg",
    )

    assert validate.await_count == 0
    assert result.approval_status == ApprovalStatus.PENDING  # manual HITL


@pytest.mark.asyncio
async def test_gig_photo_ai_runs_for_plus(
    db_session, test_family, test_child_user, plus_subscription, monkeypatch
):
    from app.models.task_assignment import ApprovalStatus
    from app.services.task_assignment_service import TaskAssignmentService
    from app.services.task_proof_validator import ProofValidation
    from tests.test_ai_consent_gate import _seed_gig

    test_family.ai_processing_consent = True
    test_child_user.gig_trust_streak = 0
    await db_session.commit()
    tmpl, a = await _seed_gig(db_session, test_family, test_child_user)

    validate = AsyncMock(
        return_value=ProofValidation(score=0.95, explanation="Leaves raked.")
    )
    monkeypatch.setattr(
        "app.services.task_proof_validator.validate_proof_photo", validate
    )

    result = await TaskAssignmentService.complete_assignment(
        db_session,
        a.id,
        test_family.id,
        test_child_user.id,
        proof_text="raked everything",
        proof_image_url="/uploads/gig-proofs/synthetic.jpg",
    )

    assert validate.await_count == 1
    assert result.approval_status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_bank_sync_create_uses_ai_for_plus(
    client: AsyncClient, a2a_webhook_row, plus_subscription, monkeypatch
):
    from app.services.budget.category_ai_service import CategoryAIService

    suggest = AsyncMock(return_value=None)
    monkeypatch.setattr(CategoryAIService, "suggest", suggest)

    body = _bank_alert_body()
    r = await client.post(
        "/api/budget/bank-sync/transactions",
        content=body,
        headers={
            "X-A2A-Family": str(a2a_webhook_row.id),
            "X-A2A-Signature": _a2a_sig(body),
        },
    )
    assert r.status_code == 200, r.text
    assert suggest.await_count == 1
