# Actual Budget vs FTM Budget Module -- Gap Analysis

**Date**: 2026-04-02
**Author**: Development Team
**Version**: 1.0

---

## 1. Executive Summary

This document provides a forensic 1:1 comparison between Actual Budget -- a sophisticated, local-first personal finance application with CRDT sync, custom query language, and multi-format import capabilities -- and the Family Task Manager's built-in budget module. The analysis catalogs 14 features that have been successfully ported to FTM, identifies 17 features that remain unimplemented, assigns priority tiers (P0/P1/P2) based on daily-workflow impact, and proposes a phased implementation roadmap. The goal is to give the team a clear picture of where FTM's budget module stands relative to Actual's full feature set and to guide future development investment.

---

## 2. Feature Parity Table

| # | Feature Area | Actual Budget | FTM Budget | Status | Gap Detail |
|---|-------------|--------------|------------|--------|------------|
| 1 | **Accounts** | Full CRUD, types (checking/savings/credit/investment/loan/mortgage/other), on-budget vs off-budget flag, close/reopen, balance calculation, starting balance as special transaction | Full CRUD, same type set (checking/savings/credit/investment/loan/other), on-budget/off-budget, close/reopen, balance calculation, starting balance transaction | ✅ Ported | Feature-complete for current needs |
| 2 | **Transactions** | CRUD, split transactions (parent/child model), transfers between accounts, cleared/reconciled status flags, `imported_id` for deduplication, `sort_order` for manual ordering | CRUD, split transactions (parent/child), transfers, cleared/reconciled flags, `imported_id` dedup, `sort_order` | ✅ Ported | Feature-complete |
| 3 | **Categories & Groups** | CRUD, income vs expense (`is_income`), archive/hide, `sort_order`, group-category hierarchy, tombstone soft-delete | CRUD, `is_income` flag, archive/hide, `sort_order`, group-category hierarchy | ✅ Ported | Feature-complete |
| 4 | **Payees** | CRUD, auto-creation during import, merge duplicates, favorites flag, learn-categories, lat/lng location | CRUD, auto-creation from CSV import | ✅ Ported | Missing merge, favorites, learn-categories, location (see #18, #23, #29) |
| 5 | **Envelope Budgeting** | Monthly allocations per category, rollover/carry-forward, "Ready to Assign" (a.k.a. "To Be Budgeted") calculation, upsert allocation | Monthly allocations per category, rollover carry-forward, "Ready to Assign" calculation, upsert allocation | ✅ Ported | Feature-complete |
| 6 | **Recurring Transactions** | Templates with daily/weekly/monthly/yearly patterns, configurable interval, auto-posting engine, next-date calculation, end modes (never/after-N/on-date), weekend skip/solve (before/after) | Templates with daily/weekly/monthly patterns, configurable interval, auto-posting, next-date calculation, basic `end_date` | ✅ Ported | Missing yearly frequency, "after N occurrences" end mode, weekend handling (see #19) |
| 7 | **Categorization Rules** | Exact/contains/startswith/regex on payee/description/both, priority ordering, multi-field actions (set payee, notes, amount, category), Handlebars formula templates, pre/post import stages | Exact/contains/startswith/regex on payee/description/both, priority ordering, single action: set category, suggest endpoint | ✅ Ported | Missing multi-action rules, formula templates, pre/post stages (see #16) |
| 8 | **Budget Goals** | Spending limit, savings target, percentage-of-income, weeks-of-spending, goal templates, auto-fill from goals, progress tracking | Spending limit and savings target types, progress tracking endpoint, period (monthly/quarterly/annual) | ✅ Ported | Missing percentage-of-income, weeks-of-spending, goal templates, auto-fill (see #20) |
| 9 | **CSV Import** | Column mapping, delimiter config (comma/semicolon/tab/pipe), dedup via `imported_id`, auto-payee creation, skip header rows, error reporting per row | Column mapping, delimiter config (comma/semicolon/tab), dedup via `imported_id`, auto-payee creation, skip headers, error reporting | ✅ Ported | Feature-complete for CSV. Missing OFX/QIF/CAMT formats (see #17) |
| 10 | **Reports** | Fully configurable report builder: any graph type (bar/line/area/donut/table), split by any dimension, custom date ranges, saved conditions, color schemes. Stored in `custom_reports` table | 4 hardcoded report types: spending (by category/group/month/payee), income-vs-expense (by month/week/day), net-worth, budget-analysis. Premium-gated | ✅ Ported | Functionally adequate for standard use. Missing configurable report builder (see #22) |
| 11 | **Month Locking** | Close/reopen months to prevent edits, status check | Close/reopen months, status check endpoint, list closed months | ✅ Ported | Feature-complete |
| 12 | **Transfers** | Account-to-account (linked transaction pair), category-to-category (allocation adjustment), cover-overspending | Account-to-account (creates 2 linked transactions), category-to-category (adjusts allocations), cover-overspending | ✅ Ported | Feature-complete |
| 13 | **Recycle Bin** | Soft delete via tombstone pattern for all entities, recovery window | Soft delete for transactions/accounts/categories/category_groups, 30-day recovery, permanent delete, empty bin | ✅ Ported | Feature-complete |
| 14 | **Month Budget View** | Complete monthly view: budgeted/actual/available per category, group rollup, "To Be Budgeted" summary, carryover display | Complete monthly view: budgeted/actual/available per category, category group rollup, "Ready to Assign" summary | ✅ Ported | Feature-complete |
| 15 | **Saved Transaction Filters** | `transaction_filters` table with named reusable filter conditions supporting AND/OR logic, saved per user | Inline filtering on transaction list page only; no persistence | ❌ Missing | Users must recreate filter combinations on every visit. No saved filter model or endpoints exist. **Priority: P0. Effort: Medium.** |
| 16 | **Advanced Rule Actions** | Rules can set any field (payee, notes, amount, category), use Handlebars formula templates, append/prepend to notes, have pre-import and post-import stages | Rules only set category field | ❌ Missing | Limits automation -- users cannot auto-set payee, clean up notes, or transform amounts via rules. **Priority: P0. Effort: Medium.** |
| 17 | **OFX/QIF/CAMT Import** | Supports OFX (Open Financial Exchange), QIF (Quicken Interchange Format), QFX, CAMT XML (ISO 20022 bank standard) | CSV only | ❌ Missing | Mexican banks commonly export OFX. Users must manually convert bank exports to CSV before importing. **Priority: P0. Effort: Medium.** |
| 18 | **Payee Merging** | Merge multiple duplicate payees into one target, updating all FK references (transactions, rules) atomically | No merge capability | ❌ Missing | Imported transactions create duplicates ("WALMART", "Walmart MX", "WAL-MART") that fragment reports and complicate categorization. **Priority: P0. Effort: Low.** |
| 19 | **Schedule End Modes** | End modes: "never", "after N occurrences", "on specific date". Weekend skip/solve: shift to Friday (before) or Monday (after). Yearly frequency | Basic `end_date` field only. No occurrence counting. No weekend handling. No yearly frequency | ❌ Missing | Users cannot create "repeat 12 times" or "skip weekends" schedules. Yearly bills (insurance, property tax) require workarounds. **Priority: P0. Effort: Low.** |
| 20 | **Budget Templates & Auto-Fill** | Auto-fill budget from: copy previous month, average of 3/6/12/N months, goal templates, fill underfunded, fill by target date | Manual allocation entry each month | ❌ Missing | Monthly budget setup is tedious and repetitive. Most users have stable spending patterns that could be auto-filled. **Priority: P1. Effort: Medium.** |
| 21 | **Tags** | Full transaction tagging system (M2M relationship via `transaction_tags` join table). Enables cross-category tracking: "vacation", "tax-deductible", "reimbursable" | No tagging system | ❌ Missing | Cannot track cross-cutting concerns. A "vacation" trip spanning food/transport/lodging categories cannot be aggregated. **Priority: P1. Effort: Medium.** |
| 22 | **Custom Reports & Dashboard Widgets** | `custom_reports` table: configurable graph type (bar/line/area/donut/table), split by dimension (category/payee/account/tag), date range, filter conditions, color scheme. `dashboard`/`dashboard_pages` tables for draggable widget layouts | 4 hardcoded report types with fixed dimensions | ❌ Missing | Power users cannot build custom views. Would require new models, a report builder UI, and chart rendering infrastructure. **Priority: P1. Effort: High.** |
| 23 | **Favorite Payees** | `favorite` boolean flag on payees, surfaced in transaction entry for quick access | No favorite flag | ❌ Missing | Minor UX improvement for transaction entry speed. **Priority: P1. Effort: Low.** |
| 24 | **Budget Export** | Exports full budget as importable zip archive (db.sqlite + metadata.json). Enables backup and migration | No export capability | ❌ Missing | Users cannot create portable backups or migrate data out of FTM. **Priority: P1. Effort: Medium.** |
| 25 | **Bank Sync** | Integrates with GoCardless (Europe), SimpleFIN (North America), Pluggy.ai (Brazil) for automatic bank connection and transaction import | No bank sync | ❌ Missing | Requires third-party API contracts, credential management, webhook handling. Very high complexity. Target market (Mexico) has limited provider support. **Priority: P2. Effort: Very High.** |
| 26 | **YNAB Import** | Imports from YNAB 4 (desktop) and YNAB 5 (nYNAB web). One-time migration tool parsing YNAB's export format | No YNAB import | ❌ Missing | One-time migration tool for users switching from YNAB. Niche audience for FTM's target market. **Priority: P2. Effort: Medium.** |
| 27 | **Multi-device CRDT Sync** | Conflict-free Replicated Data Types enable offline-first multi-device sync without a central server | Server-based architecture (PostgreSQL). All clients hit the API | ❌ N/A | Architecturally different paradigm. FTM's server-first model provides real-time consistency via PostgreSQL. CRDT sync is not applicable to FTM's architecture and would require a fundamental rewrite. **Priority: Deferred.** |
| 28 | **AQL Query Language** | Custom Actual Query Language for ad-hoc data queries, used internally by reports and filters | Standard SQLAlchemy ORM queries server-side | ❌ N/A | FTM's server-side ORM provides equivalent query capability. AQL exists because Actual runs client-side on SQLite and needed a query abstraction. Not needed for server architecture. **Priority: Deferred.** |
| 29 | **Payee Location Tracking** | Latitude/longitude fields on payee records for map-based visualization | No location data | ❌ Missing | Very niche feature. Privacy concerns with storing location data. Minimal user value for a family budgeting app. **Priority: P2. Effort: Low.** |
| 30 | **Encryption at Rest** | Client-side encryption of budget data on disk using user passphrase | PostgreSQL server-level security, TLS in transit | ❌ Missing | FTM relies on PostgreSQL access controls and Docker network isolation. Column-level encryption could be added but has performance implications and low user demand. **Priority: P2. Effort: High.** |
| 31 | **Custom Dashboard Pages** | `dashboard_pages` table with draggable widget layouts, persistent per-user configuration | No dashboard system | ❌ Missing | Depends on Custom Reports (#22) being implemented first. Would require drag-and-drop UI framework and widget persistence layer. **Priority: P2. Effort: High.** |

### Summary

| Status | Count |
|--------|-------|
| ✅ Ported | 14 |
| ❌ Missing (P0) | 5 |
| ❌ Missing (P1) | 5 |
| ❌ Missing (P2) | 5 |
| ❌ N/A (architectural) | 2 |
| **Total** | **31** |

---

## 3. Partial Parity Notes

The 14 ported features are functionally solid but several have nuances worth documenting for future enhancement:

### Reports
FTM implements 4 fixed report types (spending, income-vs-expense, net-worth, budget-analysis) with predefined split dimensions. Actual's report system is fully configurable: users pick graph type, split dimension, date range, and filter conditions, then save the result as a named report. FTM's reports are functionally adequate for standard personal finance use but lack the customization that power users expect. All FTM reports are premium-gated.

### Categorization Rules
FTM supports 4 match types (`exact`, `contains`, `startswith`, `regex`) across 3 target fields (`payee`, `description`, `both`) with priority-based ordering and a `/suggest` endpoint for rule recommendations. Actual extends this with multi-action rules (a single rule can set category AND rename payee AND append to notes), Handlebars formula templates for computed values, and separate pre-import and post-import rule stages. The gap primarily affects users with complex import workflows.

### Recurring Transactions
FTM has daily, weekly, and monthly frequencies with a configurable `interval` (e.g., every 2 weeks) and JSON `pattern` config for specifics (e.g., day-of-week for weekly). Missing capabilities: yearly frequency (needed for insurance premiums, annual subscriptions), "after N occurrences" end mode (e.g., "repeat 12 times for a car loan"), and weekend skip/solve behavior (shift Saturday/Sunday occurrences to the nearest Friday or Monday).

### CSV Import
FTM's CSV import is well-implemented with column mapping UI, configurable delimiters (comma/semicolon/tab), deduplication via `imported_id`, automatic payee creation, header row skipping, and per-row error reporting. The gap is format coverage: Actual supports OFX, QIF, QFX, and CAMT XML in addition to CSV. Mexican banks commonly provide OFX exports, making this a practical pain point for FTM's target user base.

### Budget Goals
FTM implements two goal types (`spending_limit` and `savings_target`) with progress tracking and configurable periods (monthly/quarterly/annual). Actual extends this with percentage-of-income goals, weeks-of-spending goals (e.g., "maintain 4 weeks of grocery spending"), goal templates that can auto-fill monthly allocations, and a "fill underfunded" action that distributes remaining funds across goals by priority.

### Payees
FTM has basic CRUD with auto-creation during CSV import. Actual adds several payee management features: merging duplicate payees (consolidating all FK references), a `favorite` flag for quick access during transaction entry, a `learn_categories` flag that auto-suggests categories based on historical payee usage, and latitude/longitude location tracking. Of these, payee merging (#18) has the highest practical impact.

---

## 4. Implementation Roadmap

### Phase 1 -- Core Workflow Gaps (P0)

Target: Eliminate friction in daily budget management workflows.

| Feature | Effort | Key Work |
|---------|--------|----------|
| **Payee Merging** (#18) | Low | New service method to merge payees, update all transaction/rule FKs, delete source payees. Single API endpoint. |
| **Schedule End Modes** (#19) | Low | Add `end_mode` enum (never/after_n/on_date), `occurrence_limit` int, `weekend_behavior` enum (skip_before/skip_after) to recurring transaction model. Update next-date calculator. Add yearly frequency. |
| **Saved Transaction Filters** (#15) | Medium | New `transaction_filters` model (name, family_id, conditions JSON, created_by). CRUD endpoints. Frontend filter save/load UI. |
| **Advanced Rule Actions** (#16) | Medium | Extend rule model with `actions` JSON array (each action: field + operation + value). Update rule application engine to process multiple actions. |
| **OFX/QIF/CAMT Import** (#17) | Medium | Add parser modules for each format (use `ofxparse` for OFX, custom parser for QIF, `lxml` for CAMT XML). Route through existing transaction creation pipeline. Format detection in import endpoint. |

### Phase 2 -- Experience Enhancement (P1)

Target: Reduce repetitive manual work and enable richer data modeling.

| Feature | Effort | Key Work |
|---------|--------|----------|
| **Favorite Payees** (#23) | Low | Add `is_favorite` boolean to payee model. Migration. Filter endpoint. Frontend star toggle. |
| **Budget Templates & Auto-Fill** (#20) | Medium | New service with strategies: copy-previous-month, average-N-months, fill-from-goals. New endpoint accepting strategy + parameters. Frontend auto-fill button with strategy picker. |
| **Tags** (#21) | Medium | New `tags` and `transaction_tags` models. CRUD endpoints. Tag picker component in transaction form. Extend report service to support tag dimension. Migration for 2 new tables. |
| **Budget Export** (#24) | Medium | Export endpoint that serializes all budget data (accounts, categories, transactions, allocations, rules, goals) to JSON, packages as zip. Import endpoint for restore. |

### Phase 3 -- Power Features (P1/P2)

Target: Differentiate FTM for advanced users.

| Feature | Effort | Key Work |
|---------|--------|----------|
| **Custom Reports & Dashboard Widgets** (#22) | High | New `custom_reports` model with graph type, dimensions, conditions, color config. Report builder UI with chart library integration. Substantial frontend investment. |
| **Bank Sync** (#25) | Very High | Third-party API integration (evaluate Pluggy.ai for Mexico/LatAm). Credential vault, webhook receiver, transaction reconciliation, error handling. Ongoing maintenance cost. Only pursue if target market demand validates the investment. |

### Deferred (N/A or Low Priority)

These features are either architecturally inapplicable to FTM or serve niche audiences that do not justify the implementation cost at this stage:

- **YNAB Import** (#26) -- Niche migration tool. Reconsider if user acquisition strategy targets YNAB switchers.
- **Multi-device CRDT Sync** (#27) -- Not applicable. FTM's server-first PostgreSQL architecture provides real-time consistency without CRDT complexity.
- **AQL Query Language** (#28) -- Not applicable. SQLAlchemy ORM serves the same purpose server-side.
- **Payee Location Tracking** (#29) -- Privacy concerns outweigh minimal utility.
- **Encryption at Rest** (#30) -- PostgreSQL server security is sufficient. Reconsider if handling sensitive financial data under regulatory requirements.
- **Custom Dashboard Pages** (#31) -- Depends on Custom Reports (#22). Defer until report builder exists.

---

## 5. Technical Reference

### Actual Budget Source Locations

| Area | Path |
|------|------|
| Core server logic | `actual/packages/loot-core/src/server/` |
| Database schema (AQL) | `actual/packages/loot-core/src/server/aql/schema/index.ts` |
| Type definitions | `actual/packages/loot-core/src/types/models/` |
| Public API methods | `actual/packages/api/methods.ts` |
| Desktop UI components | `actual/packages/desktop-client/src/components/` |
| Budget page | `actual/packages/desktop-client/src/components/budget/` |
| Reports UI | `actual/packages/desktop-client/src/components/reports/` |
| Transaction filters | `actual/packages/desktop-client/src/components/filters/` |
| Rule editor | `actual/packages/desktop-client/src/components/rules/` |
| Import handlers | `actual/packages/loot-core/src/server/accounts/` |
| Sync/CRDT engine | `actual/packages/loot-core/src/server/sync/` |
| Schedule logic | `actual/packages/loot-core/src/server/schedules/` |

### FTM Budget Source Locations

| Area | Path |
|------|------|
| Models (all 7 tables) | `backend/app/models/budget.py` |
| Schemas (Pydantic) | `backend/app/schemas/budget.py` |
| **Services** | |
| -- Account service | `backend/app/services/budget/account_service.py` |
| -- Transaction service | `backend/app/services/budget/transaction_service.py` |
| -- Category service | `backend/app/services/budget/category_service.py` |
| -- Allocation service | `backend/app/services/budget/allocation_service.py` |
| -- Payee service | `backend/app/services/budget/payee_service.py` |
| -- Recurring transactions | `backend/app/services/budget/recurring_transaction_service.py` |
| -- Categorization rules | `backend/app/services/budget/categorization_rule_service.py` |
| -- Goals | `backend/app/services/budget/goal_service.py` |
| -- CSV import | `backend/app/services/budget/csv_import_service.py` |
| -- Reports | `backend/app/services/budget/report_service.py` |
| -- Month locking | `backend/app/services/budget/month_locking_service.py` |
| -- Transfers | `backend/app/services/budget/transfer_service.py` |
| -- Recycle bin | `backend/app/services/budget/recycle_bin_service.py` |
| **Routes** | |
| -- Accounts | `backend/app/api/routes/budget/accounts.py` |
| -- Transactions | `backend/app/api/routes/budget/transactions.py` |
| -- Categories | `backend/app/api/routes/budget/categories.py` |
| -- Allocations | `backend/app/api/routes/budget/allocations.py` |
| -- Payees | `backend/app/api/routes/budget/payees.py` |
| -- Recurring transactions | `backend/app/api/routes/budget/recurring_transactions.py` |
| -- Categorization rules | `backend/app/api/routes/budget/categorization_rules.py` |
| -- Goals | `backend/app/api/routes/budget/goals.py` |
| -- Reports | `backend/app/api/routes/budget/reports.py` |
| -- Month locking | `backend/app/api/routes/budget/months.py` |
| -- Month budget view | `backend/app/api/routes/budget/month.py` |
| -- Transfers | `backend/app/api/routes/budget/transfers.py` |
| -- Recycle bin | `backend/app/api/routes/budget/recycle_bin.py` |
| **Frontend pages** | |
| -- Budget index | `frontend/src/pages/budget/index.astro` |
| -- Transactions | `frontend/src/pages/budget/transactions.astro` |
| -- Import | `frontend/src/pages/budget/import.astro` |
| -- Month view | `frontend/src/pages/budget/month/` |
| -- Reports | `frontend/src/pages/budget/reports/` |
| -- Settings | `frontend/src/pages/budget/settings.astro` |
| -- Accounts (parent) | `frontend/src/pages/parent/finances/accounts/` |
| -- Categories (parent) | `frontend/src/pages/parent/finances/categories/` |
| -- Transactions (parent) | `frontend/src/pages/parent/finances/transactions/` |

---

## Appendix: Effort Estimation Key

| Effort | Description |
|--------|-------------|
| **Low** | 1-2 days. Model change + migration + 1-2 endpoints + minimal UI. |
| **Medium** | 3-7 days. New service module, multiple endpoints, frontend page/component, tests. |
| **High** | 1-3 weeks. Significant new subsystem, complex UI (builder/editor), multiple models, extensive testing. |
| **Very High** | 3+ weeks. Third-party integrations, ongoing maintenance, security review, external API contracts. |
