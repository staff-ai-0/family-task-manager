# Budget UX Redesign — Hub + Drawer

**Date:** 2026-04-09
**Status:** Approved
**Goal:** Reduce 21 budget pages to 6, optimize the daily loop (register expense → check month status) to 2 clicks.

---

## Problem

The current budget UI has 21 separate pages. Users only touch 3 regularly (month, transactions, scan receipt). Reports are interesting but buried behind too many navigations. Settings are fragmented across 5 sub-pages. Registering a single expense requires ~5 page navigations.

**Primary user:** Parents managing household finances.
**Daily loop:** Register expense → see impact on monthly budget.

---

## Design: Hub + Drawer

### Navigation Structure

**3 persistent tabs** (always visible in tab bar):
- **Mes** — monthly budget overview with category progress bars
- **Movimientos** — transaction list with filters
- **Reportes** — unified reports with 4 sub-tabs

**Hamburger menu (☰)** opens a drawer with everything else:
- **Gestión:** Cuentas, Categorías, Beneficiarios
- **Herramientas:** Escanear ticket, Importar CSV, Recurrentes, Reglas auto
- **Sistema:** Respaldos, Configuración

**FAB (+)** — floating action button, always visible bottom-right. Opens a modal/bottom-sheet for quick expense registration without leaving the current page.

### Page 1: `/budget/` — Hub + Vista Mes (TAB: Mes)

Replaces: `index.astro`, `month/index.astro`, `month/[year]/[month].astro`, `categories/index.astro`

**Layout:**
- Top summary bar: Ingresos | Gastado | Disponible + overall progress bar with percentage
- Category groups (collapsible): each category shows name, spent/budgeted, progress bar
  - Progress bar colors: green (< 75%), yellow (75-95%), red (> 95%)
- Categories are editable inline (tap budget amount to edit allocation)
- Month navigation: arrows to go prev/next month
- Category management (add/edit/delete) via inline actions, no separate page

**Data:** Fetches from `/api/budget/month` and `/api/budget/categories` endpoints.

### Page 2: `/budget/transactions` — Movimientos (TAB: Movimientos)

Replaces: `transactions.astro`, `transactions/new.astro`, `accounts/[id].astro`, `accounts/[id]/reconcile.astro`

**Layout:**
- Filter bar: account selector, category selector, date range, search by payee/note
- Transaction list grouped by date (existing behavior)
- Selecting an account filter effectively replaces the old account detail page
- Reconciliation: accessible via account filter → reconcile button (opens modal with checkbox list)
- New transactions created via the FAB modal (not a separate page)

**Data:** Fetches from `/api/budget/transactions` with query params for filtering.

### Page 3: `/budget/reports` — Reportes (TAB: Reportes)

Replaces: `reports/spending.astro`, `reports/income-vs-expense.astro`, `reports/net-worth.astro`, `reports/budget-analysis.astro`

**Layout:**
- 4 pill sub-tabs: Gastos | Flujo | Patrimonio | vs Presupuesto
- Shared period selector: 1M / 3M / 6M / 1A + prev/next arrows
- Period selection persists across sub-tab switches
- All sub-tab switching is client-side (no page reload)

**Sub-tab content:**
- **Gastos:** Donut chart + category breakdown + trend bars (replaces spending.astro)
- **Flujo:** Bar chart income vs expenses by month (replaces income-vs-expense.astro)
- **Patrimonio:** Line chart net worth over time (replaces net-worth.astro)
- **vs Presupuesto:** Category-level budget vs actual comparison (replaces budget-analysis.astro)

**Data:** Fetches from `/api/budget/reports` endpoint with report type and period params.

### Page 4: `/budget/scan-receipt` — Scanner (DRAWER)

Stays as-is. Complex workflow with camera/upload that justifies its own page. Also accessible from FAB → "Foto" mode which navigates here.

### Page 5: `/budget/import` — Importar CSV (DRAWER)

Stays as-is. Complex multi-step workflow (upload → configure → preview → import) that justifies its own page.

### Page 6: `/budget/settings` — Config Unificada (DRAWER)

Replaces: `settings.astro`, `settings/rules.astro`, `settings/payees.astro`, `settings/recurring.astro`, `settings/backups.astro`

**Layout:**
- Single page with collapsible sections (accordion):
  - **Cuentas** — list, add, edit accounts (replaces accounts/index + accounts/new)
  - **Beneficiarios** — payee management (replaces settings/payees)
  - **Reglas de categorización** — auto-categorization rules (replaces settings/rules)
  - **Transacciones recurrentes** — recurring transaction management (replaces settings/recurring)
  - **Respaldos** — export/import backup (replaces settings/backups)
- Each section loads its content on expand (lazy loading)

### FAB (+) — Quick Expense Modal

Present on all 3 tab pages. Opens a bottom-sheet/modal overlay.

**Flow (3 steps):**
1. **Entry mode selection + amount:** Quick amount chips ($50, $100, $200, $500) + manual input. Three mode buttons: Manual (keyboard) | Foto (camera) | Scan (file upload).
2. **Complete details:** Payee (with auto-complete), Category (auto-filled by categorization rules when payee matches), Account (defaults to last used), Note (optional).
3. **Confirmation:** Success message + impact on the category (updated progress bar). Buttons: "+ Otro gasto" (resets form) | "Cerrar" (dismisses modal).

**Smart defaults:**
- Auto-categorization: if a categorization rule matches the payee, category is pre-filled with a "regla ✓" indicator
- Last-used account: defaults to the account used in the previous transaction
- Quick amounts: common amounts as tappable chips to avoid typing
- "Foto" mode: navigates to `/budget/scan-receipt`, result flows back to the form

### Drawer Menu

Opens from ☰ hamburger icon in the header. Slides in from the left, dims the main content behind it.

**Sections:**
- **Principal:** Mes, Movimientos, Reportes (mirrors the 3 tabs — for discoverability)
- **Gestión:** Cuentas, Categorías, Beneficiarios (links to /budget/settings with the relevant section expanded)
- **Herramientas:** Escanear ticket (/budget/scan-receipt), Importar CSV (/budget/import), Recurrentes (→ settings), Reglas auto (→ settings)
- **Sistema:** Respaldos (→ settings), Configuración (→ settings)

---

## Pages Eliminated (15)

| Old Page | Destination |
|----------|-------------|
| `index.astro` (hub cards) | Merged into `/budget/` |
| `month/index.astro` (redirect) | Unnecessary — `/budget/` is the month view |
| `month/[year]/[month].astro` | Merged into `/budget/` with month navigation |
| `categories/index.astro` | Inline in month view |
| `accounts/index.astro` | Drawer → settings accounts section |
| `accounts/[id].astro` | Filter in `/budget/transactions` |
| `accounts/[id]/reconcile.astro` | Modal in `/budget/transactions` |
| `accounts/new.astro` | Modal in settings accounts section |
| `transactions/new.astro` | FAB modal |
| `reports/spending.astro` | Sub-tab in `/budget/reports` |
| `reports/income-vs-expense.astro` | Sub-tab in `/budget/reports` |
| `reports/net-worth.astro` | Sub-tab in `/budget/reports` |
| `reports/budget-analysis.astro` | Sub-tab in `/budget/reports` |
| `settings/rules.astro` | Section in `/budget/settings` |
| `settings/payees.astro` | Section in `/budget/settings` |
| `settings/recurring.astro` | Section in `/budget/settings` |
| `settings/backups.astro` | Section in `/budget/settings` |

---

## Impact Metrics

| Metric | Before | After |
|--------|--------|-------|
| Total pages | 21 | 6 |
| Clicks to register expense | ~5 | 2 |
| Clicks to view report | ~3 | 1 |
| Tab bar items | 6 | 3 |
| Settings pages | 5 | 1 |
| Report pages | 4 | 1 (4 sub-tabs) |

---

## Technical Considerations

### Backend
- **No API changes needed.** All existing endpoints remain. The frontend restructuring is purely a presentation layer change.
- Reports page will need to fetch from multiple report endpoints based on the active sub-tab.

### Frontend
- **Astro pages reduced** from 21 to 6. Old page files can be deleted after migration.
- **New components needed:**
  - `BudgetNav.astro` — simplified 3-tab navigation bar
  - `DrawerMenu.astro` — slide-out drawer with grouped links
  - `FABModal.astro` — floating action button + bottom-sheet modal for quick expense entry
  - `ReportSubTabs.astro` — pill tabs for report switching (client-side)
  - `PeriodSelector.astro` — shared period selector for reports
  - `SettingsAccordion.astro` — collapsible sections for unified settings
  - `ReconcileModal.astro` — reconciliation modal for transactions page
  - `CategoryProgressBar.astro` — reusable progress bar with color thresholds
- **Client-side interactivity:** Report sub-tabs and period selection must work without page reloads. Use Astro islands or vanilla JS.
- **Existing components:** Many existing components from the old pages can be reused inside the new consolidated pages (transaction list, category group display, chart components).

### Migration Strategy
- Build new pages alongside old ones (no breaking changes)
- Redirect old URLs to new equivalents for any external links or bookmarks
- Delete old pages after validation

---

## Out of Scope
- Mobile native app (this is responsive web)
- New backend endpoints or data model changes
- Custom report builder (future enhancement)
- Onboarding wizard for new users (future enhancement)
