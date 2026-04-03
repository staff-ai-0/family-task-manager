# Budget Feature Gap Closure — Design Specification

**Date**: 2026-04-02
**Status**: Approved
**Scope**: Backend-only (models, services, routes, schemas, tests) for 10 features in 3 waves

---

## Context

Forensic code review of Actual Budget vs FTM's budget module identified 17 missing features. This spec covers 10 features (5 P0 + 5 P1) organized into 3 implementation waves. Frontend UI is deferred to a separate cycle.

---

## Wave 1 — Quick Wins (Low effort)

### Feature 1: Payee Merging

**Model changes**: None.

**New endpoint**: `POST /api/budget/payees/merge`

**Request schema** (`PayeeMergeRequest`):
```python
class PayeeMergeRequest(BaseModel):
    target_id: UUID  # Payee to keep
    source_ids: list[UUID]  # Payees to merge into target
```

**Response**: `PayeeResponse` (the target payee)

**Service logic** (`payee_service.py`):
1. Verify target and all sources belong to family
2. Update `budget_transactions.payee_id` from each source to target
3. Update `budget_categorization_rules` where any source is referenced in `actions` JSONB
4. Update `budget_recurring_transactions.payee_id` from each source to target
5. Delete source payees
6. All in single transaction

---

### Feature 2: Schedule End Modes

**Model changes** (`BudgetRecurringTransaction`):
```python
end_mode: Mapped[str] = mapped_column(
    String(20), default="never", nullable=False,
    comment="'never', 'on_date', 'after_n'"
)
occurrence_limit: Mapped[Optional[int]] = mapped_column(
    Integer, nullable=True,
    comment="Max occurrences for after_n mode"
)
occurrence_count: Mapped[int] = mapped_column(
    Integer, default=0, nullable=False,
    comment="Current occurrence count"
)
weekend_behavior: Mapped[str] = mapped_column(
    String(20), default="none", nullable=False,
    comment="'none', 'before' (Fri), 'after' (Mon)"
)
```

**Schema changes**:
- Add `end_mode`, `occurrence_limit`, `weekend_behavior` to `RecurringTransactionCreate` and `RecurringTransactionUpdate`
- Add `occurrence_count` to `RecurringTransactionResponse`
- Allow `recurrence_type` to include `"yearly"`

**Service changes** (`recurring_transaction_service.py`):
- `calculate_next_occurrence`: Add yearly frequency handling, weekend adjustment
- `post_transaction`: Increment `occurrence_count`, auto-deactivate when `occurrence_count >= occurrence_limit`
- Migration: Default existing rows to `end_mode="on_date"` if `end_date` is set, else `"never"`

---

### Feature 3: Favorite Payees

**Model changes** (`BudgetPayee`):
```python
is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

**Schema changes**:
- Add `is_favorite` to `PayeeCreate`, `PayeeUpdate`, `PayeeResponse`

**Route changes** (`payees.py`):
- Add `favorites_only: bool = False` query param to list endpoint

---

## Wave 2 — Core Enhancements (Medium effort)

### Feature 4: Saved Transaction Filters

**New model** (`BudgetSavedFilter`):
```python
class BudgetSavedFilter(Base):
    __tablename__ = "budget_saved_filters"

    id: UUID (PK)
    family_id: UUID (FK families)
    name: str (max 200)
    conditions: JSONB  # [{field, operator, value}, ...]
    conditions_op: str  # "and" or "or"
    created_by: UUID (FK users)
    created_at, updated_at: DateTime
```

**Conditions JSONB format**:
```json
[
  {"field": "account_id", "operator": "eq", "value": "uuid-here"},
  {"field": "amount", "operator": "gte", "value": -50000},
  {"field": "date", "operator": "between", "value": ["2026-01-01", "2026-03-31"]}
]
```

Supported fields: `account_id, category_id, payee_id, date, amount, cleared, reconciled, notes`
Supported operators: `eq, neq, gt, gte, lt, lte, contains, between, in`

**New service**: `saved_filter_service.py` — CRUD extending `BaseFamilyService`

**New route file**: `saved_filters.py`
- `GET /api/budget/saved-filters` — list
- `POST /api/budget/saved-filters` — create
- `GET /api/budget/saved-filters/{id}` — get
- `PUT /api/budget/saved-filters/{id}` — update
- `DELETE /api/budget/saved-filters/{id}` — delete

---

### Feature 5: Advanced Rule Actions

**Model changes** (`BudgetCategorizationRule`):
```python
actions: Mapped[Optional[list]] = mapped_column(
    JSONB, nullable=True, default=None,
    comment="Multi-field actions: [{field, operation, value}, ...]"
)
```

**Actions JSONB format**:
```json
[
  {"field": "category", "operation": "set", "value": "uuid-of-category"},
  {"field": "notes", "operation": "append", "value": " [auto-categorized]"},
  {"field": "payee", "operation": "set", "value": "uuid-of-payee"}
]
```

Supported fields: `category, payee, notes`
Supported operations: `set, append, prepend`

**Schema changes**:
- Add `actions` (optional) to `CategorizationRuleCreate`, `CategorizationRuleUpdate`, `CategorizationRuleResponse`
- New `RuleAction` schema: `{field: str, operation: str, value: str}`

**Service changes** (`categorization_rule_service.py`):
- `apply_rule(transaction, rule)` — new method that applies all actions from a matched rule
- Backward compat: if `actions` is null, behave as before (set `category_id`)
- `suggest_category` renamed to `apply_matching_rules` — returns applied actions, not just category

---

### Feature 6: Tags

**New models**:
```python
class BudgetTag(Base):
    __tablename__ = "budget_tags"

    id: UUID (PK)
    family_id: UUID (FK families, indexed)
    name: str (max 100)
    color: Optional[str] (max 20, e.g., "#3B82F6")
    created_at, updated_at: DateTime

    UniqueConstraint("family_id", "name", name="uq_tag_family_name")

class BudgetTransactionTag(Base):
    __tablename__ = "budget_transaction_tags"

    id: UUID (PK)
    transaction_id: UUID (FK budget_transactions, ondelete CASCADE)
    tag_id: UUID (FK budget_tags, ondelete CASCADE)

    UniqueConstraint("transaction_id", "tag_id", name="uq_transaction_tag")
```

**Schemas**:
- `TagCreate`: `{name, color?}`
- `TagUpdate`: `{name?, color?}`
- `TagResponse`: `{id, name, color, family_id, created_at, updated_at}`
- `TransactionTagsUpdate`: `{tag_ids: list[UUID]}`

**New service**: `tag_service.py`
- CRUD for tags
- `set_transaction_tags(transaction_id, tag_ids)` — replace all tags for a transaction
- `get_transaction_tags(transaction_id)` — list tags for a transaction

**New route file**: `tags.py`
- `GET /api/budget/tags` — list family tags
- `POST /api/budget/tags` — create
- `PUT /api/budget/tags/{id}` — update
- `DELETE /api/budget/tags/{id}` — delete
- `GET /api/budget/transactions/{id}/tags` — get transaction tags
- `PUT /api/budget/transactions/{id}/tags` — set transaction tags

---

## Wave 3 — Power Features (Medium-High effort)

### Feature 7: OFX/QIF/CAMT Import

**New dependency**: `ofxparse` (for OFX/QFX parsing)

**New service**: `file_import_service.py`

**Shared data structure**:
```python
@dataclass
class ImportedTransaction:
    date: date
    amount: int  # in cents
    payee_name: str
    notes: str = ""
    imported_id: str = ""  # for dedup
```

**Parsers**:
- `parse_ofx(file_bytes: bytes) -> list[ImportedTransaction]` — uses ofxparse
- `parse_qif(file_bytes: bytes) -> list[ImportedTransaction]` — custom line parser
- `parse_camt(file_bytes: bytes) -> list[ImportedTransaction]` — lxml XML parser
- `detect_format(filename: str, content: bytes) -> str` — returns "csv"|"ofx"|"qif"|"camt"

**Route changes** (`transactions.py`):
- Extend `POST /api/budget/transactions/import/csv` to accept all formats
- Or add new `POST /api/budget/transactions/import/file` that auto-detects format
- After parsing, reuse existing transaction creation pipeline (dedup, payee creation, rule application)

---

### Feature 8: Budget Templates & Auto-Fill

**No new models.**

**New service methods** in `allocation_service.py`:
```python
async def auto_fill(family_id, target_month, strategy, params=None):
    """Auto-fill budget allocations for target month."""
    ...

async def _copy_previous_month(family_id, target_month):
    """Copy all allocations from previous month."""
    ...

async def _average_n_months(family_id, target_month, n):
    """Set allocations to average of last N months' actual spending."""
    ...

async def _fill_from_goals(family_id, target_month):
    """Set allocations from category goal_amount fields."""
    ...
```

**New endpoint**: `POST /api/budget/allocations/auto-fill`

**Request schema** (`AutoFillRequest`):
```python
class AutoFillRequest(BaseModel):
    target_month: date  # first day of month
    strategy: str  # "copy_previous", "average_3", "average_6", "average_12", "from_goals"
    overwrite_existing: bool = False  # skip categories that already have allocations
```

**Response**: `{filled_count: int, skipped_count: int, allocations: list[AllocationResponse]}`

---

### Feature 9: Budget Export

**No new models.**

**New service**: `export_service.py`
```python
async def export_budget(family_id) -> bytes:
    """Export all budget data as ZIP archive."""
    # Query: accounts, categories, groups, transactions, allocations,
    #        payees, rules, goals, recurring, tags, saved_filters
    # Serialize to JSON
    # Package as ZIP: budget_data.json + metadata.json
    ...

async def import_budget(family_id, zip_bytes) -> dict:
    """Restore budget from exported ZIP."""
    # Clear existing budget data for family
    # Deserialize and recreate all entities
    # Return import stats
    ...
```

**New endpoints**:
- `GET /api/budget/export` — returns ZIP file download
- `POST /api/budget/import-backup` — accepts ZIP file upload, restores data

---

### Feature 10: Custom Reports

**New model** (`BudgetCustomReport`):
```python
class BudgetCustomReport(Base):
    __tablename__ = "budget_custom_reports"

    id: UUID (PK)
    family_id: UUID (FK families, indexed)
    name: str (max 200)
    config: JSONB  # full report configuration
    created_by: UUID (FK users)
    created_at, updated_at: DateTime
```

**Config JSONB format**:
```json
{
  "graph_type": "bar",
  "group_by": "category",
  "balance_type": "expense",
  "date_range": "last_3_months",
  "start_date": "2026-01-01",
  "end_date": "2026-03-31",
  "show_empty": false,
  "conditions": [
    {"field": "account_id", "operator": "in", "value": ["uuid1", "uuid2"]}
  ]
}
```

**Schemas**:
- `CustomReportCreate`: `{name, config}`
- `CustomReportUpdate`: `{name?, config?}`
- `CustomReportResponse`: `{id, name, config, family_id, created_by, created_at, updated_at}`

**New service**: `custom_report_service.py`
- CRUD extending `BaseFamilyService`
- `generate_data(report)` — reads config, delegates to `report_service.py` methods

**New route file**: `custom_reports.py`
- `GET /api/budget/custom-reports` — list
- `POST /api/budget/custom-reports` — create
- `GET /api/budget/custom-reports/{id}` — get
- `PUT /api/budget/custom-reports/{id}` — update
- `DELETE /api/budget/custom-reports/{id}` — delete
- `GET /api/budget/custom-reports/{id}/data` — execute and return report data

---

## Database Migrations

- **Wave 1 migration**: ALTER TABLE `budget_payees` (add `is_favorite`), ALTER TABLE `budget_recurring_transactions` (add `end_mode`, `occurrence_limit`, `occurrence_count`, `weekend_behavior`)
- **Wave 2 migration**: CREATE TABLE `budget_saved_filters`, `budget_tags`, `budget_transaction_tags`; ALTER TABLE `budget_categorization_rules` (add `actions`)
- **Wave 3 migration**: CREATE TABLE `budget_custom_reports`

## Testing Strategy

Each feature gets tests covering:
- Model creation and constraints
- Service business logic (happy path + edge cases)
- API endpoint integration (auth, validation, CRUD)
- Inter-feature interactions where applicable

## Files Changed Per Wave

**Wave 1** (modify existing):
- `backend/app/models/budget.py` — add columns
- `backend/app/schemas/budget.py` — extend schemas
- `backend/app/services/budget/payee_service.py` — add merge method
- `backend/app/services/budget/recurring_transaction_service.py` — update calc/post
- `backend/app/api/routes/budget/payees.py` — add merge endpoint, favorites filter
- `backend/migrations/versions/` — 1 new migration
- `backend/tests/` — new test file

**Wave 2** (new + modify):
- `backend/app/models/budget.py` — add 3 models + 1 column
- `backend/app/schemas/budget.py` — add schemas
- `backend/app/services/budget/saved_filter_service.py` — new
- `backend/app/services/budget/tag_service.py` — new
- `backend/app/services/budget/categorization_rule_service.py` — extend
- `backend/app/api/routes/budget/saved_filters.py` — new
- `backend/app/api/routes/budget/tags.py` — new
- `backend/app/api/routes/budget/categorization_rules.py` — extend
- `backend/app/main.py` — register new routers
- `backend/migrations/versions/` — 1 new migration
- `backend/tests/` — new test files

**Wave 3** (new + modify):
- `backend/app/models/budget.py` — add 1 model
- `backend/app/schemas/budget.py` — add schemas
- `backend/app/services/budget/file_import_service.py` — new
- `backend/app/services/budget/export_service.py` — new
- `backend/app/services/budget/custom_report_service.py` — new
- `backend/app/services/budget/allocation_service.py` — extend
- `backend/app/api/routes/budget/transactions.py` — extend import
- `backend/app/api/routes/budget/allocations.py` — add auto-fill
- `backend/app/api/routes/budget/custom_reports.py` — new
- `backend/app/api/routes/budget/export.py` — new
- `backend/app/main.py` — register new routers
- `backend/requirements.txt` — add ofxparse, lxml
- `backend/migrations/versions/` — 1 new migration
- `backend/tests/` — new test files
