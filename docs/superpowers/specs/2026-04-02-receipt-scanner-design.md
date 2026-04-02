# AI Receipt Scanner — Design Spec

**Date:** 2026-04-02
**Status:** Approved
**Depends on:** Premium Subscription System (Spec 1)
**Scope:** Camera capture, Ollama vision via AgentIA Orchestrator, split transaction creation, receipt image storage

---

## Overview

Add a "Escanear Recibo" button to the budget month page. Users take a photo or upload an image of a receipt. The image is sent to the AgentIA Orchestrator (which routes to Ollama with a configurable vision model). The AI extracts the store name, date, and individual line items with amounts and suggested categories. The user reviews and edits the extracted data, then confirms to create a parent + split transactions, a payee, and store the receipt image.

## User Flow

1. User taps **"Escanear Recibo"** on the monthly budget page (next to "Nueva Transacción")
2. Navigates to receipt scan page with camera capture + file upload
3. User takes photo or selects image → sees image preview
4. User selects target **account** from dropdown
5. User taps **"Procesar Recibo"**
6. Image uploads to backend → backend forwards to AgentIA Orchestrator → AI extracts data
7. Loading overlay: *"Analizando recibo..."* (3-15 seconds depending on model)
8. Review screen shows: store name, date, line items table (description, amount, category dropdown per row)
9. User can edit any field, change categories, remove items, add items, adjust amounts
10. User taps **"Crear Transacciones"** → backend creates payee + parent transaction + split transactions + stores image
11. Redirects to month view with toast: *"Recibo procesado: N transacciones creadas"*

## Architecture

```
Frontend (Astro)
    │
    │  POST /api/budget/receipts/scan
    │  (multipart: image + account_id)
    │
    ▼
FastAPI Backend
    │
    │  1. Save image to /uploads/receipts/{family_id}/{uuid}.jpg
    │  2. Check premium access (require_feature("receipt_scan"))
    │  3. Forward image to Orchestrator
    │
    │  POST http://{AGENTIA_ORCHESTRATOR_URL}/api/v1/process
    │  (image + prompt + model config)
    │
    ▼
AgentIA Orchestrator (10.1.0.99:8082)
    │
    │  Routes to configured vision model
    │
    ▼
Ollama (10.1.0.99:11434)
    │  Default model: minicpm-v
    │  Configurable via RECEIPT_VISION_MODEL env var
    │
    ▼
Structured JSON response → Backend parses → Returns to Frontend
```

## AI Vision Processing

### Configuration

| Env Variable | Default | Description |
|-------------|---------|-------------|
| `AGENTIA_ORCHESTRATOR_URL` | `http://10.1.0.99:8082` | Orchestrator base URL |
| `AGENTIA_API_KEY` | (required) | API key for orchestrator auth |
| `RECEIPT_VISION_MODEL` | `minicpm-v` | Ollama model name (configurable for any vision model) |
| `RECEIPT_UPLOAD_DIR` | `/app/uploads/receipts` | Filesystem path for stored images |
| `RECEIPT_MAX_IMAGE_SIZE_MB` | `10` | Max upload size |

### Prompt

The backend constructs a prompt that includes the family's category names for better suggestions:

```
System: You are a receipt parser. Extract data from the receipt image 
and return ONLY valid JSON with this exact structure:

{
  "store_name": "Store Name",
  "date": "YYYY-MM-DD",
  "items": [
    {
      "description": "Item description as shown on receipt",
      "amount": 3250,
      "suggested_category": "Category Name"
    }
  ],
  "subtotal": 7750,
  "tax": 1240,
  "total": 8990,
  "currency": "MXN"
}

Rules:
- All amounts in cents (integer, no decimals). Example: $32.50 = 3250
- Date in YYYY-MM-DD format
- Suggest category from this list: {family_categories}
- If an item can't be categorized, use "Uncategorized"
- If item description is unclear, transcribe as-is from receipt
- Include tax as a separate item if visible on receipt
- currency should be the currency shown on the receipt, default MXN
```

### Response Parsing

The `ReceiptService` parses the AI JSON response with fallbacks:

1. Extract JSON from response (handle markdown code blocks, extra text)
2. Validate required fields (store_name, date, items, total)
3. Validate amounts are integers > 0
4. Match `suggested_category` against family's actual categories (fuzzy match by name)
5. If parsing fails entirely, return error with raw AI response for debugging

### Category Matching

For each item's `suggested_category`:

1. Exact match against family's category names (case-insensitive)
2. If no exact match, check existing `BudgetCategorizationRule` patterns against item description
3. If still no match, leave category as null (user must pick manually)

## API Endpoints

All require PARENT role + premium access.

### `POST /api/budget/receipts/scan`

Upload and process a receipt image.

**Request:** `multipart/form-data`
- `image` (file): Receipt image (JPEG, PNG, HEIC — max 10MB)
- `account_id` (UUID): Target budget account

**Dependencies:** `require_parent_role`, `require_feature("receipt_scan")`

**Processing:**
1. Validate image type and size
2. Save image to `{RECEIPT_UPLOAD_DIR}/{family_id}/{uuid}.{ext}`
3. Resize if needed (max 1920px on longest side for Ollama)
4. Send to Orchestrator with vision prompt
5. Parse AI response
6. Match categories
7. Return structured data

**Response:** `200 OK`

```json
{
  "receipt_id": "uuid",
  "image_path": "receipts/{family_id}/{uuid}.jpg",
  "store_name": "Walmart Supercenter",
  "date": "2026-04-02",
  "items": [
    {
      "description": "Leche Lala 1L",
      "amount": 3250,
      "suggested_category_id": "uuid-or-null",
      "suggested_category_name": "Groceries"
    }
  ],
  "subtotal": 7750,
  "tax": 1240,
  "total": 8990,
  "currency": "MXN",
  "confidence": "high"
}
```

**Errors:**
- `400` — Invalid image type/size
- `403` — Premium required or usage limit reached
- `422` — AI could not parse receipt (returns partial data if available)
- `503` — Orchestrator/Ollama unreachable

### `POST /api/budget/receipts/confirm`

Create transactions from reviewed receipt data.

**Request:** `application/json`

```json
{
  "receipt_id": "uuid",
  "account_id": "uuid",
  "store_name": "Walmart Supercenter",
  "date": "2026-04-02",
  "items": [
    {
      "description": "Leche Lala 1L",
      "amount": -3250,
      "category_id": "uuid"
    },
    {
      "description": "Pan Bimbo",
      "amount": -4500,
      "category_id": "uuid"
    },
    {
      "description": "IVA",
      "amount": -1240,
      "category_id": "uuid-or-null"
    }
  ]
}
```

**Processing:**
1. Validate month is not locked
2. Find or create `BudgetPayee` from `store_name`
3. Calculate total from items
4. Create parent `BudgetTransaction` with `is_parent=True`, total amount, payee, date, `receipt_image_path`
5. Create split `BudgetTransaction` per item with `parent_id`, individual category, amount
6. Increment `usage_tracking` for `"receipt_scan"`
7. Return created transactions

**Response:** `201 Created`

```json
{
  "parent_transaction_id": "uuid",
  "split_count": 3,
  "total_amount": -8990,
  "payee": "Walmart Supercenter",
  "message": "Recibo procesado: 3 transacciones creadas"
}
```

### `GET /api/budget/receipts/{receipt_id}/image`

Serve the stored receipt image.

**Response:** Image file with appropriate content-type.

## Database Changes

### New Field on `BudgetTransaction`

| Column | Type | Notes |
|--------|------|-------|
| `receipt_image_path` | VARCHAR(500) | Nullable. Relative path: `receipts/{family_id}/{uuid}.jpg`. Only set on parent transactions. |

**Migration:** Add nullable column, no data backfill needed.

### Docker Volume

Add to `docker-compose.yml`:

```yaml
backend:
  volumes:
    - receipt_uploads:/app/uploads/receipts

volumes:
  receipt_uploads:
```

## Frontend

### New Page: `frontend/src/pages/budget/receipts/scan.astro`

Single page with 3 client-side phases (no page navigation during the flow):

**Phase 1 — Capture:**
- Camera button: `<input type="file" accept="image/*" capture="environment">` (opens camera on mobile)
- Upload button: `<input type="file" accept="image/*">` (file picker)
- Image preview (canvas-based, with client-side resize to max 1920px before upload)
- Account selector dropdown (pre-populated from API)
- "Procesar Recibo" button (disabled until image + account selected)

**Phase 2 — Processing:**
- Overlay with spinner animation
- "Analizando recibo..." text
- Cancel button (aborts fetch)

**Phase 3 — Review:**
- Store name: editable text input (becomes payee)
- Date: editable date input
- Line items table:
  - Description (editable text)
  - Amount (editable number, displayed as currency)
  - Category (dropdown per row, populated with family's categories grouped by group)
  - Delete row button (×)
- "Agregar Item" button to add manual items
- Total display: sum of items (auto-calculated, highlighted if doesn't match AI total)
- Receipt image thumbnail (click to expand in modal)
- "Crear Transacciones" button
- "Cancelar" link back to month view

### Modified Page: `frontend/src/pages/budget/month/[year]/[month].astro`

Add "Escanear Recibo" button next to "Nueva Transacción":

```html
<a href="/budget/receipts/scan?year={year}&month={month}&account={defaultAccountId}"
   class="...button styles...">
    📷 Escanear Recibo
</a>
```

Same for parent route: `frontend/src/pages/parent/finances/month/[year]/[month].astro`

### Duplicate Page: `frontend/src/pages/parent/finances/receipts/scan.astro`

Mirror of the budget scan page for the parent finance route, following existing pattern.

## Image Handling

### Client-Side (before upload)
- Resize to max 1920px on longest side using canvas
- Convert to JPEG at 85% quality
- Display preview

### Server-Side (after upload)
- Validate MIME type (image/jpeg, image/png, image/heic)
- Validate file size (≤ 10MB after client resize)
- Save with UUID filename: `{RECEIPT_UPLOAD_DIR}/{family_id}/{uuid}.jpg`
- For Ollama: base64-encode the saved image

### Storage
- Docker named volume mounted at `/app/uploads/receipts`
- Path stored as relative: `receipts/{family_id}/{uuid}.jpg`
- No cleanup/expiry for now (images are small, ~200KB after resize)

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Orchestrator unreachable | Toast: "Servicio de IA no disponible. Intenta más tarde." |
| AI returns unparseable response | Show error with option to retry or enter manually |
| AI returns partial data (some items missing) | Show what was parsed, let user add missing items |
| Image too large (>10MB after resize) | Client-side error before upload |
| Unsupported image format | Client-side validation + server 400 |
| Usage limit reached | 403 → UpgradePrompt component |
| Month is locked | Disable scan button, show tooltip |
| Network timeout (>30s) | Abort with retry option |

## Files to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `backend/app/services/budget/receipt_service.py` | AI processing, image handling, category matching |
| `backend/app/api/routes/budget/receipts.py` | 3 endpoints: scan, confirm, get image |
| `backend/app/schemas/receipt.py` | Request/response schemas |
| `backend/alembic/versions/xxx_add_receipt_image_path.py` | Add column to budget_transactions |
| `frontend/src/pages/budget/receipts/scan.astro` | Scan page (budget route) |
| `frontend/src/pages/parent/finances/receipts/scan.astro` | Scan page (parent route) |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/main.py` | Register receipts router |
| `backend/app/core/config.py` | Add AGENTIA_*, RECEIPT_* env vars |
| `backend/app/models/budget.py` | Add `receipt_image_path` to BudgetTransaction |
| `docker-compose.yml` | Add receipt_uploads volume |
| `frontend/src/pages/budget/month/[year]/[month].astro` | Add "Escanear Recibo" button |
| `frontend/src/pages/parent/finances/month/[year]/[month].astro` | Add "Escanear Recibo" button |

## Testing

- Unit tests for `ReceiptService`:
  - JSON parsing with various AI response formats (clean, markdown-wrapped, with extra text)
  - Category matching (exact, rule-based, no match)
  - Image validation (type, size)
- Integration tests for endpoints:
  - Scan with mock Orchestrator response
  - Confirm creates correct parent + split transactions + payee
  - Image serving
  - Premium gating (403 without subscription)
  - Usage limit enforcement
- Frontend: manual testing on mobile (camera capture) and desktop (file upload)
