"""Inbound a2a endpoints for the bank-email-matcher agent.

Machine-to-machine, authenticated by per-family HMAC (the same secret as the
price-checker integration, stored in family_a2a_webhooks). No user session —
the agent signs requests with the family's secret.

Signature scheme (mirrors price-checker):
    X-A2A-Family:    <family_id>
    X-A2A-Signature: sha256=<hmac_sha256(secret, message)>
  - GET  /candidates    message = "candidates:<days>"
  - POST /reconcile     message = raw JSON body
  - POST /transactions  message = raw JSON body

Endpoints:
  GET  /candidates    → recent transactions the agent matches alerts against
  POST /reconcile     → mark a matched transaction cleared
  POST /transactions  → create a transaction from an unmatched bank alert
                        (idempotent on external_id via imported_id)
"""

import hashlib
import hmac
import logging
from datetime import date as _date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.budget import BudgetAccount, BudgetTransaction
from app.services.budget.a2a_webhook_service import A2AWebhookService

router = APIRouter()
logger = logging.getLogger(__name__)


async def _family_and_secret(db: AsyncSession, family_hdr: str) -> tuple[UUID, str]:
    try:
        family_id = UUID(family_hdr)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid family id")
    cfg = await A2AWebhookService.get_config(db, family_id)
    if cfg is None or not cfg.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "family not registered")
    return family_id, cfg.secret


def _verify(secret: str, message: bytes, signature: str) -> None:
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")


@router.get("/candidates")
async def list_candidates(
    days: int = Query(35, ge=1, le=120),
    x_a2a_family: str = Header(default=""),
    x_a2a_signature: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Recent non-deleted transactions for the agent to match alerts against."""
    family_id, secret = await _family_and_secret(db, x_a2a_family)
    _verify(secret, f"candidates:{days}".encode("utf-8"), x_a2a_signature)

    from app.models.budget import BudgetPayee
    cutoff = _date.today() - timedelta(days=days)
    rows = (await db.execute(
        select(BudgetTransaction, BudgetPayee.name)
        .outerjoin(BudgetPayee, BudgetTransaction.payee_id == BudgetPayee.id)
        .where(
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.deleted_at.is_(None),
            BudgetTransaction.parent_id.is_(None),
            BudgetTransaction.date >= cutoff,
        ).order_by(BudgetTransaction.date.desc())
    )).all()

    return {
        "transactions": [
            {
                "transaction_id": str(t.id),
                "date": t.date.isoformat(),
                "amount_cents": int(t.amount),
                "payee": payee_name,
                "card_last4": t.card_last4,
                "cleared": bool(t.cleared),
            }
            for t, payee_name in rows
        ]
    }


class ReconcileBody(BaseModel):
    transaction_id: UUID
    bank_ref: str = ""


@router.post("/reconcile")
async def reconcile_transaction(
    request: Request,
    x_a2a_family: str = Header(default=""),
    x_a2a_signature: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Mark a matched transaction as cleared (bank confirmed it)."""
    raw = await request.body()
    family_id, secret = await _family_and_secret(db, x_a2a_family)
    _verify(secret, raw, x_a2a_signature)

    import json
    try:
        body = ReconcileBody(**json.loads(raw))
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid body")

    txn = (await db.execute(
        select(BudgetTransaction).where(
            BudgetTransaction.id == body.transaction_id,
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if txn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transaction not found")

    txn.cleared = True
    if body.bank_ref and not (txn.notes or "").endswith(body.bank_ref):
        txn.notes = ((txn.notes or "") + f" · conf. {body.bank_ref}").strip()
    await db.commit()
    return {"status": "reconciled", "transaction_id": str(txn.id)}


class CreateBody(BaseModel):
    merchant: str | None = None
    amount_cents: int = Field(..., gt=0)
    direction: str = "debit"  # debit=expense, credit=income
    kind: str = "purchase"  # purchase|transfer|withdrawal|card_payment|deposit|refund|fee|other
    date: _date
    card_last4: str | None = None
    currency: str = "MXN"
    bank: str | None = None
    external_id: str = Field(..., min_length=1)


@router.post("/transactions")
async def create_from_alert(
    request: Request,
    x_a2a_family: str = Header(default=""),
    x_a2a_signature: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Create a transaction from an unmatched bank alert (idempotent)."""
    raw = await request.body()
    family_id, secret = await _family_and_secret(db, x_a2a_family)
    _verify(secret, raw, x_a2a_signature)

    import json
    try:
        body = CreateBody(**json.loads(raw))
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid body: {exc}")

    # Idempotency: external_id stored in imported_id.
    existing = (await db.execute(
        select(BudgetTransaction).where(
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.imported_id == body.external_id,
            BudgetTransaction.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing is not None:
        return {"status": "exists", "transaction_id": str(existing.id)}

    # Resolve account by card last4, else first account.
    from app.services.budget.account_matching_service import AccountMatchingService
    match = await AccountMatchingService.match(
        db, family_id, user_id=None, card_last4=body.card_last4,
        receipt_currency=body.currency, override_account_id=None,
    )
    account_id = match.account_id
    if account_id is None:
        account_id = (await db.execute(
            select(BudgetAccount.id).where(
                BudgetAccount.family_id == family_id,
                BudgetAccount.deleted_at.is_(None),
                BudgetAccount.closed.is_(False),
            ).order_by(BudgetAccount.sort_order).limit(1)
        )).scalar_one_or_none()
    if account_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "family has no account")

    # Resolve / create payee.
    payee_id = None
    if body.merchant:
        from app.services.budget.payee_service import PayeeService
        payee = await PayeeService.get_or_create_by_name(db, family_id, body.merchant)
        payee_id = payee.id

    signed = body.amount_cents if body.direction == "credit" else -body.amount_cents
    txn = BudgetTransaction(
        family_id=family_id,
        account_id=account_id,
        date=body.date,
        amount=signed,
        payee_id=payee_id,
        card_last4=body.card_last4,
        notes=(f"{body.merchant or ''}".strip() or None),
        cleared=True,  # came from the bank, so it's confirmed
        reconciled=False,
        imported_id=body.external_id,
    )
    db.add(txn)
    await db.flush()

    # Categorize: kind-based transfer (LLM-classified) → text transfer detection
    # → learned payee default → AI. The matcher's `kind` is the strongest signal
    # (e.g. a "Transferencia a BBVA" whose merchant is just "BBVA MEXICO").
    from app.services.budget.transfer_detector import (
        resolve_transfer_category_for_kind,
        resolve_transfer_category_id,
    )
    cat = await resolve_transfer_category_for_kind(db, family_id, body.kind)
    if cat is None:
        cat = await resolve_transfer_category_id(db, family_id, body.merchant, txn.notes)
    if cat is None and payee_id is not None:
        from app.models.budget import BudgetPayee
        payee_row = await db.get(BudgetPayee, payee_id)
        if payee_row is not None and payee_row.default_category_id:
            cat = payee_row.default_category_id
    if cat is None:
        # AI categorization is paid-only; free/downgraded families still get
        # the transaction, just uncategorized.
        from app.core.premium import family_tier_allows
        if await family_tier_allows(db, family_id, "ai_features"):
            from app.services.budget.category_ai_service import CategoryAIService
            try:
                cat = await CategoryAIService.suggest(
                    db, family_id, body.merchant, is_income=(body.direction == "credit"),
                )
            except Exception:
                logger.exception("AI categorize failed for bank-sync txn")
    if cat is not None:
        txn.category_id = cat
        if payee_id is not None:
            from app.models.budget import BudgetPayee
            payee_row = await db.get(BudgetPayee, payee_id)
            if payee_row is not None and not payee_row.default_category_id:
                payee_row.default_category_id = cat

    await db.commit()
    await db.refresh(txn)
    return {"status": "created", "transaction_id": str(txn.id)}
