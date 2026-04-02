# AI Receipt Scanner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Prerequisite:** The Premium Subscription System plan must be completed first. This plan depends on `require_feature("receipt_scan")`, `UsageService.increment()`, and the subscription models.

**Goal:** Add receipt photo scanning to the budget system. Users photograph a receipt, AI extracts line items, and the system creates a split transaction with auto-categorized items.

**Architecture:** Frontend page captures/uploads an image, sends it to a new FastAPI endpoint. The backend forwards the image to the AgentIA Orchestrator (which routes to Ollama with a configurable vision model), parses the AI response into structured data, matches categories, and returns results for user review. On confirmation, creates a parent + split transactions, a payee, and stores the receipt image.

**Tech Stack:** Python 3.12, FastAPI, httpx (async HTTP to Orchestrator), Astro 5, Tailwind CSS v4, Ollama (minicpm-v default)

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/services/budget/receipt_service.py` | AI processing: send image to Orchestrator, parse response, match categories |
| `backend/app/api/routes/budget/receipts.py` | 3 endpoints: scan, confirm, get image |
| `backend/app/schemas/receipt.py` | Pydantic schemas for receipt request/response |
| `frontend/src/pages/budget/receipts/scan.astro` | Receipt scan page (budget route) |
| `frontend/src/pages/parent/finances/receipts/scan.astro` | Receipt scan page (parent route) |
| `backend/tests/test_receipt.py` | Tests for receipt processing |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/core/config.py` | Add `AGENTIA_ORCHESTRATOR_URL`, `AGENTIA_API_KEY`, `RECEIPT_VISION_MODEL`, `RECEIPT_UPLOAD_DIR` |
| `backend/app/models/budget.py` | Add `receipt_image_path` to BudgetTransaction |
| `backend/app/api/routes/budget/__init__.py` | Register receipts router |
| `docker-compose.yml` | Add receipt_uploads volume |
| `frontend/src/pages/budget/month/[year]/[month].astro` | Add "Escanear Recibo" button |
| `frontend/src/pages/parent/finances/month/[year]/[month].astro` | Add "Escanear Recibo" button |

---

### Task 1: Config + Database Changes

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/models/budget.py`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add config variables**

Add these fields to the `Settings` class in `backend/app/core/config.py`, after the `LITELLM_MODEL` line:

```python
    # AgentIA Orchestrator (for AI features)
    AGENTIA_ORCHESTRATOR_URL: str = "http://10.1.0.99:8082"
    AGENTIA_API_KEY: str = ""
    RECEIPT_VISION_MODEL: str = "minicpm-v"
    RECEIPT_UPLOAD_DIR: str = "/app/uploads/receipts"
    RECEIPT_MAX_IMAGE_SIZE_MB: int = 10
```

- [ ] **Step 2: Add receipt_image_path to BudgetTransaction**

In `backend/app/models/budget.py`, add this field to the `BudgetTransaction` class, after the `transfer_account_id` field (around line 159):

```python
    receipt_image_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="Relative path to receipt image"
    )
```

Add `String` to the import if not already there (it's already imported on line 14).

- [ ] **Step 3: Add Docker volume for receipt uploads**

In `docker-compose.yml`, add a named volume for receipt storage:

Under the `backend` service's `volumes` section, add:
```yaml
      - receipt_uploads:/app/uploads/receipts
```

Under the top-level `volumes` section, add:
```yaml
  receipt_uploads:
```

- [ ] **Step 4: Generate and apply migration**

Run:
```bash
docker exec family_app_backend alembic revision --autogenerate -m "add receipt_image_path to budget_transactions"
docker exec family_app_backend alembic upgrade head
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/app/models/budget.py docker-compose.yml backend/alembic/versions/
git commit -m "feat: add receipt scanner config, receipt_image_path field, and upload volume"
```

---

### Task 2: Receipt Schemas

**Files:**
- Create: `backend/app/schemas/receipt.py`

- [ ] **Step 1: Create receipt schemas**

```python
# backend/app/schemas/receipt.py
"""Pydantic schemas for receipt scanning."""
from datetime import date as DateType
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ReceiptItem(BaseModel):
    """A single line item extracted from a receipt."""
    description: str
    amount: int = Field(..., description="Amount in cents (positive value)")
    suggested_category_id: Optional[UUID] = None
    suggested_category_name: Optional[str] = None


class ScanResponse(BaseModel):
    """Response from receipt scanning."""
    receipt_id: str
    image_path: str
    store_name: str
    date: str
    items: list[ReceiptItem]
    subtotal: Optional[int] = None
    tax: Optional[int] = None
    total: int
    currency: str = "MXN"


class ConfirmItem(BaseModel):
    """A line item for transaction creation."""
    description: str
    amount: int = Field(..., description="Amount in cents (negative for expenses)")
    category_id: Optional[UUID] = None


class ConfirmRequest(BaseModel):
    """Request to create transactions from reviewed receipt data."""
    receipt_id: str
    account_id: UUID
    store_name: str
    date: DateType
    items: list[ConfirmItem]


class ConfirmResponse(BaseModel):
    """Response after creating transactions."""
    parent_transaction_id: UUID
    split_count: int
    total_amount: int
    payee: str
    message: str
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/receipt.py
git commit -m "feat: add receipt scanning Pydantic schemas"
```

---

### Task 3: Receipt Service

**Files:**
- Create: `backend/app/services/budget/receipt_service.py`
- Create: `backend/tests/test_receipt.py`

- [ ] **Step 1: Write tests for receipt service**

```python
# backend/tests/test_receipt.py
"""Tests for AI receipt scanning."""
import pytest
import pytest_asyncio
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.services.budget.receipt_service import ReceiptService


# --- JSON Parsing Tests ---

class TestParseAIResponse:
    """Test parsing of AI vision model responses."""

    def test_parse_clean_json(self):
        raw = '''{
            "store_name": "Walmart",
            "date": "2026-04-02",
            "items": [
                {"description": "Leche 1L", "amount": 3250, "suggested_category": "Groceries"},
                {"description": "Pan Bimbo", "amount": 4500, "suggested_category": "Groceries"}
            ],
            "subtotal": 7750,
            "tax": 1240,
            "total": 8990,
            "currency": "MXN"
        }'''
        result = ReceiptService.parse_ai_response(raw)
        assert result["store_name"] == "Walmart"
        assert len(result["items"]) == 2
        assert result["total"] == 8990

    def test_parse_markdown_wrapped_json(self):
        raw = '''Here is the extracted data:
```json
{
    "store_name": "Costco",
    "date": "2026-04-01",
    "items": [{"description": "Item", "amount": 1000, "suggested_category": "Groceries"}],
    "total": 1000,
    "currency": "MXN"
}
```'''
        result = ReceiptService.parse_ai_response(raw)
        assert result["store_name"] == "Costco"

    def test_parse_invalid_json_raises(self):
        raw = "I cannot read this receipt clearly."
        with pytest.raises(ValueError, match="Could not parse"):
            ReceiptService.parse_ai_response(raw)

    def test_parse_missing_required_fields_raises(self):
        raw = '{"store_name": "Test"}'
        with pytest.raises(ValueError, match="Missing required"):
            ReceiptService.parse_ai_response(raw)


# --- Category Matching Tests ---

class TestMatchCategories:

    def test_exact_match(self):
        categories = [
            {"id": "cat-1", "name": "Groceries"},
            {"id": "cat-2", "name": "Gas"},
        ]
        result = ReceiptService.match_category("Groceries", categories)
        assert result == ("cat-1", "Groceries")

    def test_case_insensitive_match(self):
        categories = [{"id": "cat-1", "name": "Groceries"}]
        result = ReceiptService.match_category("groceries", categories)
        assert result == ("cat-1", "Groceries")

    def test_no_match_returns_none(self):
        categories = [{"id": "cat-1", "name": "Groceries"}]
        result = ReceiptService.match_category("Electronics", categories)
        assert result == (None, "Electronics")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_receipt.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ReceiptService**

```python
# backend/app/services/budget/receipt_service.py
"""
Receipt scanning service.

Handles: image upload, AI vision processing via AgentIA Orchestrator,
response parsing, and category matching.
"""
import base64
import json
import os
import re
from datetime import date
from typing import Optional
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.budget import (
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetPayee,
    BudgetTransaction,
)


class ReceiptService:
    """Processes receipt images via AI and creates transactions."""

    @staticmethod
    def parse_ai_response(raw: str) -> dict:
        """Parse AI response into structured receipt data.

        Handles: clean JSON, markdown-wrapped JSON, JSON with surrounding text.
        Raises ValueError if parsing fails or required fields missing.
        """
        # Try extracting JSON from markdown code block
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        text = match.group(1).strip() if match else raw.strip()

        # Try finding JSON object in text
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            text = text[brace_start : brace_end + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"Could not parse AI response as JSON")

        # Validate required fields
        required = ["store_name", "items", "total"]
        missing = [f for f in required if f not in data]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        # Default optional fields
        data.setdefault("date", date.today().isoformat())
        data.setdefault("currency", "MXN")
        data.setdefault("subtotal", None)
        data.setdefault("tax", None)

        return data

    @staticmethod
    def match_category(
        suggested: str, categories: list[dict]
    ) -> tuple[Optional[str], str]:
        """Match a suggested category name against family's categories.

        Returns (category_id, category_name). category_id is None if no match.
        """
        suggested_lower = suggested.lower()
        for cat in categories:
            if cat["name"].lower() == suggested_lower:
                return (cat["id"], cat["name"])
        return (None, suggested)

    @classmethod
    async def get_family_categories(
        cls, db: AsyncSession, family_id: UUID
    ) -> list[dict]:
        """Get all category names and IDs for a family."""
        query = (
            select(BudgetCategory.id, BudgetCategory.name)
            .where(
                and_(
                    BudgetCategory.family_id == family_id,
                    BudgetCategory.hidden == False,
                )
            )
        )
        result = await db.execute(query)
        return [{"id": str(row.id), "name": row.name} for row in result.all()]

    @classmethod
    async def save_image(cls, family_id: UUID, image_data: bytes, ext: str) -> str:
        """Save receipt image to disk. Returns relative path."""
        image_id = str(uuid4())
        rel_dir = f"receipts/{family_id}"
        abs_dir = os.path.join(settings.RECEIPT_UPLOAD_DIR, str(family_id))
        os.makedirs(abs_dir, exist_ok=True)

        filename = f"{image_id}.{ext}"
        abs_path = os.path.join(abs_dir, filename)
        with open(abs_path, "wb") as f:
            f.write(image_data)

        return f"{rel_dir}/{filename}"

    @classmethod
    async def process_image(
        cls, image_data: bytes, family_categories: list[dict]
    ) -> dict:
        """Send image to AgentIA Orchestrator for AI processing.

        Returns parsed receipt data with matched categories.
        """
        b64_image = base64.b64encode(image_data).decode("utf-8")

        category_names = [c["name"] for c in family_categories]
        prompt = (
            "You are a receipt parser. Extract data from the receipt image "
            "and return ONLY valid JSON with this structure:\n"
            '{\n  "store_name": "Store Name",\n  "date": "YYYY-MM-DD",\n'
            '  "items": [\n    {"description": "Item", "amount": 3250, '
            '"suggested_category": "Category"}\n  ],\n'
            '  "subtotal": 7750,\n  "tax": 1240,\n  "total": 8990,\n'
            '  "currency": "MXN"\n}\n\n'
            "Rules:\n"
            "- All amounts in cents (integer). Example: $32.50 = 3250\n"
            "- Date in YYYY-MM-DD format\n"
            f"- Suggest category from: {category_names}\n"
            '- If item unclear, transcribe as-is from receipt\n'
            "- Include tax as separate item if visible\n"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.AGENTIA_ORCHESTRATOR_URL}/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.AGENTIA_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.RECEIPT_VISION_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{b64_image}"
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 4096,
                },
            )
            response.raise_for_status()

        result = response.json()
        raw_text = result["choices"][0]["message"]["content"]
        parsed = cls.parse_ai_response(raw_text)

        # Match categories
        for item in parsed.get("items", []):
            suggested = item.get("suggested_category", "")
            cat_id, cat_name = cls.match_category(suggested, family_categories)
            item["suggested_category_id"] = cat_id
            item["suggested_category_name"] = cat_name

        return parsed

    @classmethod
    async def find_or_create_payee(
        cls, db: AsyncSession, family_id: UUID, name: str
    ) -> BudgetPayee:
        """Find existing payee by name or create new one."""
        query = select(BudgetPayee).where(
            and_(
                BudgetPayee.family_id == family_id,
                BudgetPayee.name == name,
            )
        )
        result = await db.execute(query)
        payee = result.scalar_one_or_none()

        if payee:
            return payee

        payee = BudgetPayee(family_id=family_id, name=name)
        db.add(payee)
        await db.flush()
        return payee

    @classmethod
    async def create_split_transactions(
        cls,
        db: AsyncSession,
        family_id: UUID,
        account_id: UUID,
        payee_id: UUID,
        transaction_date: date,
        items: list[dict],
        receipt_image_path: Optional[str] = None,
    ) -> BudgetTransaction:
        """Create parent + split transactions from receipt items.

        Returns the parent transaction.
        """
        total = sum(item["amount"] for item in items)

        # Create parent
        parent = BudgetTransaction(
            family_id=family_id,
            account_id=account_id,
            date=transaction_date,
            amount=total,
            payee_id=payee_id,
            is_parent=True,
            receipt_image_path=receipt_image_path,
        )
        db.add(parent)
        await db.flush()

        # Create splits
        for item in items:
            split = BudgetTransaction(
                family_id=family_id,
                account_id=account_id,
                date=transaction_date,
                amount=item["amount"],
                parent_id=parent.id,
                category_id=item.get("category_id"),
                notes=item.get("description", ""),
            )
            db.add(split)

        await db.commit()
        await db.refresh(parent)
        return parent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_receipt.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/budget/receipt_service.py backend/tests/test_receipt.py
git commit -m "feat: add ReceiptService for AI receipt parsing and transaction creation"
```

---

### Task 4: Receipt API Endpoints

**Files:**
- Create: `backend/app/api/routes/budget/receipts.py`
- Modify: `backend/app/api/routes/budget/__init__.py`
- Modify: `backend/tests/test_receipt.py` (add API tests)

- [ ] **Step 1: Create receipt API route**

```python
# backend/app/api/routes/budget/receipts.py
"""
Receipt scanning API endpoints.

POST /scan — upload and process receipt image
POST /confirm — create transactions from reviewed data
GET /{receipt_id}/image — serve stored receipt image
"""
import os
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.premium import require_feature
from app.models.user import User
from app.schemas.receipt import ConfirmRequest, ConfirmResponse, ScanResponse, ReceiptItem
from app.services.budget.receipt_service import ReceiptService
from app.services.usage_service import UsageService

router = APIRouter()

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif"}


@router.post("/scan", response_model=ScanResponse)
async def scan_receipt(
    image: UploadFile = File(...),
    account_id: str = Form(...),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Upload and process a receipt image."""
    # Check premium access
    await require_feature("receipt_scan", db, current_user)

    # Validate image
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {image.content_type}. Use JPEG, PNG, or HEIC.",
        )

    image_data = await image.read()
    max_bytes = settings.RECEIPT_MAX_IMAGE_SIZE_MB * 1024 * 1024
    if len(image_data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large. Maximum {settings.RECEIPT_MAX_IMAGE_SIZE_MB}MB.",
        )

    # Determine file extension
    ext_map = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/heic": "heic",
        "image/heif": "heif",
    }
    ext = ext_map.get(image.content_type, "jpg")

    # Save image
    family_id = current_user.family_id
    image_path = await ReceiptService.save_image(family_id, image_data, ext)
    receipt_id = image_path.split("/")[-1].rsplit(".", 1)[0]

    # Get family categories for AI prompt
    categories = await ReceiptService.get_family_categories(db, family_id)

    # Process with AI
    try:
        parsed = await ReceiptService.process_image(image_data, categories)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "parse_failed",
                "message": f"Could not process receipt: {str(e)}",
                "receipt_id": receipt_id,
                "image_path": image_path,
            },
        )

    # Build response
    items = []
    for item in parsed.get("items", []):
        items.append(ReceiptItem(
            description=item.get("description", ""),
            amount=abs(item.get("amount", 0)),
            suggested_category_id=item.get("suggested_category_id"),
            suggested_category_name=item.get("suggested_category_name"),
        ))

    return ScanResponse(
        receipt_id=receipt_id,
        image_path=image_path,
        store_name=parsed.get("store_name", "Unknown"),
        date=parsed.get("date", date.today().isoformat()),
        items=items,
        subtotal=parsed.get("subtotal"),
        tax=parsed.get("tax"),
        total=parsed.get("total", 0),
        currency=parsed.get("currency", "MXN"),
    )


@router.post("/confirm", response_model=ConfirmResponse, status_code=status.HTTP_201_CREATED)
async def confirm_receipt(
    data: ConfirmRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create transactions from reviewed receipt data."""
    family_id = current_user.family_id

    # Find or create payee
    payee = await ReceiptService.find_or_create_payee(db, family_id, data.store_name)

    # Build items for transaction creation
    items = []
    for item in data.items:
        items.append({
            "description": item.description,
            "amount": item.amount,  # Should be negative for expenses
            "category_id": item.category_id,
        })

    # Build image path from receipt_id
    image_path = None
    upload_dir = settings.RECEIPT_UPLOAD_DIR
    family_dir = os.path.join(upload_dir, str(family_id))
    if os.path.isdir(family_dir):
        for f in os.listdir(family_dir):
            if f.startswith(data.receipt_id):
                image_path = f"receipts/{family_id}/{f}"
                break

    # Create transactions
    parent = await ReceiptService.create_split_transactions(
        db=db,
        family_id=family_id,
        account_id=data.account_id,
        payee_id=payee.id,
        transaction_date=data.date,
        items=items,
        receipt_image_path=image_path,
    )

    # Track usage
    await UsageService.increment(db, family_id, "receipt_scan")

    total = sum(item.amount for item in data.items)
    return ConfirmResponse(
        parent_transaction_id=parent.id,
        split_count=len(data.items),
        total_amount=total,
        payee=data.store_name,
        message=f"Recibo procesado: {len(data.items)} transacciones creadas",
    )


@router.get("/{receipt_id}/image")
async def get_receipt_image(
    receipt_id: str,
    current_user: User = Depends(require_parent_role),
):
    """Serve a stored receipt image."""
    family_id = current_user.family_id
    family_dir = os.path.join(settings.RECEIPT_UPLOAD_DIR, str(family_id))

    if not os.path.isdir(family_dir):
        raise HTTPException(status_code=404, detail="Receipt not found")

    for f in os.listdir(family_dir):
        if f.startswith(receipt_id):
            return FileResponse(os.path.join(family_dir, f))

    raise HTTPException(status_code=404, detail="Receipt not found")
```

- [ ] **Step 2: Register the receipts router**

In `backend/app/api/routes/budget/__init__.py`, add the import and include:

Add to the import line:
```python
from app.api.routes.budget import categories, accounts, transactions, allocations, payees, month, transfers, reports, categorization_rules, goals, recurring_transactions, months, recycle_bin, receipts
```

Add after the last `include_router`:
```python
router.include_router(receipts.router, prefix="/receipts", tags=["budget-receipts"])
```

- [ ] **Step 3: Write API tests**

Add to `backend/tests/test_receipt.py`:

```python
from app.models.budget import BudgetAccount, BudgetCategoryGroup, BudgetCategory, BudgetPayee
from app.models.subscription import SubscriptionPlan, FamilySubscription, UsageTracking
from datetime import datetime, timedelta, timezone


@pytest_asyncio.fixture
async def plus_plan(db_session):
    plan = SubscriptionPlan(
        name="free", display_name="Free", display_name_es="Gratis",
        price_monthly_cents=0, price_annual_cents=0, sort_order=0,
        limits={
            "max_family_members": 4, "max_budget_accounts": 2,
            "max_budget_transactions_per_month": 30,
            "max_recurring_transactions": 0,
            "budget_reports": False, "budget_goals": False,
            "csv_import": False, "max_receipt_scans_per_month": 0,
            "ai_features": False,
        },
    )
    db_session.add(plan)

    plus = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        price_monthly_cents=500, price_annual_cents=5000, sort_order=1,
        limits={
            "max_family_members": 8, "max_budget_accounts": 5,
            "max_budget_transactions_per_month": 200,
            "max_recurring_transactions": 5,
            "budget_reports": True, "budget_goals": True,
            "csv_import": True, "max_receipt_scans_per_month": 15,
            "ai_features": True,
        },
    )
    db_session.add(plus)
    await db_session.commit()
    await db_session.refresh(plus)
    return plus


@pytest_asyncio.fixture
async def subscribed_family(db_session, test_family, plus_plan):
    now = datetime.now(timezone.utc)
    sub = FamilySubscription(
        family_id=test_family.id, plan_id=plus_plan.id,
        billing_cycle="monthly", status="active",
        current_period_start=now, current_period_end=now + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.commit()
    return sub


@pytest_asyncio.fixture
async def budget_account(db_session, test_family):
    account = BudgetAccount(
        family_id=test_family.id, name="Test Checking",
        type="checking", starting_balance=0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest_asyncio.fixture
async def budget_categories(db_session, test_family):
    group = BudgetCategoryGroup(
        family_id=test_family.id, name="Groceries & Food", sort_order=0,
    )
    db_session.add(group)
    await db_session.flush()

    cat = BudgetCategory(
        family_id=test_family.id, group_id=group.id,
        name="Groceries", sort_order=0,
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return [cat]


@pytest.mark.asyncio
async def test_confirm_creates_split_transactions(
    client, auth_headers, db_session, test_family,
    subscribed_family, budget_account, budget_categories,
):
    cat = budget_categories[0]
    response = await client.post(
        "/api/budget/receipts/confirm",
        headers=auth_headers,
        json={
            "receipt_id": str(uuid4()),
            "account_id": str(budget_account.id),
            "store_name": "Walmart Test",
            "date": date.today().isoformat(),
            "items": [
                {"description": "Leche", "amount": -3250, "category_id": str(cat.id)},
                {"description": "Pan", "amount": -4500, "category_id": str(cat.id)},
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["split_count"] == 2
    assert data["payee"] == "Walmart Test"


@pytest.mark.asyncio
async def test_confirm_creates_payee(
    client, auth_headers, db_session, test_family,
    subscribed_family, budget_account, budget_categories,
):
    response = await client.post(
        "/api/budget/receipts/confirm",
        headers=auth_headers,
        json={
            "receipt_id": str(uuid4()),
            "account_id": str(budget_account.id),
            "store_name": "New Store",
            "date": date.today().isoformat(),
            "items": [
                {"description": "Item", "amount": -1000},
            ],
        },
    )
    assert response.status_code == 201

    # Verify payee was created
    from sqlalchemy import select
    result = await db_session.execute(
        select(BudgetPayee).where(BudgetPayee.name == "New Store")
    )
    payee = result.scalar_one_or_none()
    assert payee is not None


@pytest.mark.asyncio
async def test_scan_blocked_without_subscription(
    client, auth_headers, db_session, test_family,
):
    # No subscription = free plan = no receipt scanning
    # Need free plan in DB
    free = SubscriptionPlan(
        name="free", display_name="Free", display_name_es="Gratis",
        price_monthly_cents=0, price_annual_cents=0, sort_order=0,
        limits={"max_receipt_scans_per_month": 0, "ai_features": False},
    )
    db_session.add(free)
    await db_session.commit()

    import io
    fake_image = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    response = await client.post(
        "/api/budget/receipts/scan",
        headers=auth_headers,
        files={"image": ("receipt.jpg", fake_image, "image/jpeg")},
        data={"account_id": str(uuid4())},
    )
    assert response.status_code == 403
```

- [ ] **Step 4: Run tests**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_receipt.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/budget/receipts.py backend/app/api/routes/budget/__init__.py backend/tests/test_receipt.py
git commit -m "feat: add receipt scanning API endpoints (scan, confirm, image)"
```

---

### Task 5: Frontend — Receipt Scan Page

**Files:**
- Create: `frontend/src/pages/budget/receipts/scan.astro`

- [ ] **Step 1: Read the existing new transaction page for layout pattern**

Read `frontend/src/pages/budget/transactions/new.astro` for the layout import, header, form style, and API call pattern.

- [ ] **Step 2: Create receipt scan page**

Create `frontend/src/pages/budget/receipts/scan.astro` with three client-side phases in a single page:

**Phase 1 — Capture:**
- Page title: "Escanear Recibo" / "Scan Receipt"
- Camera button: `<input type="file" accept="image/*" capture="environment">` (opens camera on mobile)
- Upload button: `<input type="file" accept="image/*">` (file picker for desktop)
- Image preview using `URL.createObjectURL()`
- Client-side resize before upload: use canvas to resize to max 1920px, convert to JPEG at 85% quality
- Account selector dropdown (populated from server-side API call to `/api/budget/accounts/`)
- "Procesar Recibo" button (disabled until image + account selected)

**Phase 2 — Processing:**
- Hide capture UI, show full-width loading overlay
- Spinner animation + "Analizando recibo..." text
- Submit image as `multipart/form-data` to `/api/budget/receipts/scan`
- On error: show toast with error message, return to Phase 1

**Phase 3 — Review:**
- Store name: editable text input
- Date: editable date input
- Line items table with editable rows:
  - Description (text input)
  - Amount (number input, displayed as currency)
  - Category (select dropdown per row, grouped by category group)
  - Delete row button (×)
- "Agregar Item" / "Add Item" button to add blank row
- Total: auto-calculated sum of items
- Receipt image thumbnail (click to enlarge)
- "Crear Transacciones" / "Create Transactions" button → POST to `/api/budget/receipts/confirm`
- "Cancelar" link back to month view
- On success: redirect to month view with toast

The script should be wrapped in `document.addEventListener('astro:page-load', ...)` for view transition compatibility. Use `is:inline` script with `define:vars` to pass server-side data (accounts, categories, token).

- [ ] **Step 3: Build and verify**

Run: `cd frontend && npx astro build`
Expected: Build passes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/budget/receipts/scan.astro
git commit -m "feat: add receipt scan page with camera capture, AI processing, and review UI"
```

---

### Task 6: Frontend — Parent Finance Route Copy + Scan Buttons

**Files:**
- Create: `frontend/src/pages/parent/finances/receipts/scan.astro`
- Modify: `frontend/src/pages/budget/month/[year]/[month].astro`
- Modify: `frontend/src/pages/parent/finances/month/[year]/[month].astro`

- [ ] **Step 1: Create parent finance scan page**

Copy `frontend/src/pages/budget/receipts/scan.astro` to `frontend/src/pages/parent/finances/receipts/scan.astro`. Adjust internal links to use `/parent/finances/` base route instead of `/budget/`.

- [ ] **Step 2: Add "Escanear Recibo" button to budget month page**

In `frontend/src/pages/budget/month/[year]/[month].astro`, find the "Nueva Transacción" button (search for the link to `/budget/transactions/new`). Add a second button next to it:

```html
<a href={`/budget/receipts/scan?year=${yearNum}&month=${monthNum}`}
   class="flex-1 flex items-center justify-center gap-2 bg-purple-600 text-white py-3 rounded-xl font-medium hover:bg-purple-700 transition-colors">
    <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/>
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"/>
    </svg>
    {lang === "es" ? "Escanear Recibo" : "Scan Receipt"}
</a>
```

- [ ] **Step 3: Add same button to parent finance month page**

Same change in `frontend/src/pages/parent/finances/month/[year]/[month].astro`, with link pointing to `/parent/finances/receipts/scan`.

- [ ] **Step 4: Build and verify**

Run: `cd frontend && npx astro build`
Expected: Build passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/parent/finances/receipts/scan.astro frontend/src/pages/budget/month/ frontend/src/pages/parent/finances/month/
git commit -m "feat: add scan receipt buttons to month pages and parent finance scan page"
```

---

### Task 7: Update Seed Data + Final Verification

**Files:**
- Modify: `backend/seed_data.py`

- [ ] **Step 1: Add AGENTIA env vars to docker-compose.yml**

In `docker-compose.yml`, add these environment variables to the `backend` service:

```yaml
      - AGENTIA_ORCHESTRATOR_URL=http://10.1.0.99:8082
      - AGENTIA_API_KEY=${AGENTIA_API_KEY:-}
      - RECEIPT_VISION_MODEL=minicpm-v
```

- [ ] **Step 2: Run full test suite**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v --tb=short`
Expected: All tests pass. No regressions.

- [ ] **Step 3: Build frontend**

Run: `cd frontend && npx astro build`
Expected: Build passes with no errors.

- [ ] **Step 4: Reseed and test manually**

Run:
```bash
docker cp backend/seed_data.py family_app_backend:/app/seed_data.py
docker exec -u root family_app_backend chmod 644 /app/seed_data.py
docker exec -e PYTHONPATH=/app family_app_backend python /app/seed_data.py
```

Then verify in browser:
- Login as mom@demo.com → Budget → Month view shows "Escanear Recibo" button
- Click button → scan page loads with camera/upload options
- Visit /parent/settings/subscription → shows Plus plan with usage

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add AgentIA Orchestrator config to docker-compose"
```
