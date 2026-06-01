"""Tests for the inbound bank-sync a2a endpoints (HMAC-signed, no session)."""

import hashlib
import hmac
import json
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models.a2a import FamilyA2AWebhook
from app.models.budget import BudgetAccount, BudgetTransaction

SECRET = "test-secret-bank-sync-0123456789"


def _sig(message: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def a2a_family(db_session, test_family):
    db_session.add(FamilyA2AWebhook(
        family_id=test_family.id,
        url="https://agent.example/hook",
        secret=SECRET,
        enabled=True,
    ))
    await db_session.commit()
    return test_family


@pytest_asyncio.fixture
async def account(db_session, test_family):
    acct = BudgetAccount(family_id=test_family.id, name="Card 9681",
                         type="checking", sort_order=0)
    db_session.add(acct)
    await db_session.commit()
    await db_session.refresh(acct)
    return acct


@pytest.mark.asyncio
async def test_candidates_requires_valid_signature(client: AsyncClient, a2a_family):
    r = await client.get(
        "/api/budget/bank-sync/candidates?days=35",
        headers={"X-A2A-Family": str(a2a_family.id), "X-A2A-Signature": "sha256=bad"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_candidates_returns_recent(client: AsyncClient, a2a_family, account, db_session):
    db_session.add(BudgetTransaction(
        family_id=a2a_family.id, account_id=account.id,
        date=date.today(), amount=-152296, card_last4="9681",
    ))
    await db_session.commit()

    r = await client.get(
        "/api/budget/bank-sync/candidates?days=35",
        headers={"X-A2A-Family": str(a2a_family.id), "X-A2A-Signature": _sig(b"candidates:35")},
    )
    assert r.status_code == 200
    txns = r.json()["transactions"]
    assert len(txns) == 1
    assert txns[0]["amount_cents"] == -152296
    assert txns[0]["card_last4"] == "9681"


@pytest.mark.asyncio
async def test_reconcile_marks_cleared(client: AsyncClient, a2a_family, account, db_session):
    txn = BudgetTransaction(
        family_id=a2a_family.id, account_id=account.id,
        date=date.today(), amount=-5000, cleared=False,
    )
    db_session.add(txn)
    await db_session.commit()
    await db_session.refresh(txn)

    body = json.dumps(
        {"transaction_id": str(txn.id), "bank_ref": "BBVA"},
        separators=(",", ":"), sort_keys=True,
    ).encode()
    r = await client.post(
        "/api/budget/bank-sync/reconcile",
        content=body,
        headers={"X-A2A-Family": str(a2a_family.id), "X-A2A-Signature": _sig(body)},
    )
    assert r.status_code == 200
    await db_session.refresh(txn)
    assert txn.cleared is True


@pytest.mark.asyncio
async def test_create_from_alert_and_idempotent(client: AsyncClient, a2a_family, account, db_session):
    payload = {
        "merchant": "PETRO 7 PETROMAX",
        "amount_cents": 84678,
        "direction": "debit",
        "date": date.today().isoformat(),
        "card_last4": "9681",
        "currency": "MXN",
        "bank": "BBVA",
        "external_id": "bankalert:BBVA:2026-05-29:84678",
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    headers = {"X-A2A-Family": str(a2a_family.id), "X-A2A-Signature": _sig(body)}

    # AI categorize disabled by no key — patch suggest to None for determinism.
    from unittest.mock import patch
    with patch("app.services.budget.category_ai_service.CategoryAIService.suggest", return_value=None):
        r1 = await client.post("/api/budget/bank-sync/transactions", content=body, headers=headers)
        assert r1.status_code == 200, r1.text
        assert r1.json()["status"] == "created"
        tid = r1.json()["transaction_id"]

        # Same external_id → idempotent, returns existing.
        r2 = await client.post("/api/budget/bank-sync/transactions", content=body, headers=headers)
        assert r2.json()["status"] == "exists"
        assert r2.json()["transaction_id"] == tid

    txn = await db_session.get(BudgetTransaction, __import__("uuid").UUID(tid))
    assert txn.amount == -84678  # debit → negative
    assert txn.cleared is True   # bank-confirmed
    assert txn.imported_id == payload["external_id"]


@pytest.mark.asyncio
async def test_unregistered_family_rejected(client: AsyncClient, test_family):
    r = await client.get(
        "/api/budget/bank-sync/candidates?days=35",
        headers={"X-A2A-Family": str(test_family.id), "X-A2A-Signature": _sig(b"candidates:35")},
    )
    assert r.status_code == 404  # no enabled webhook config
