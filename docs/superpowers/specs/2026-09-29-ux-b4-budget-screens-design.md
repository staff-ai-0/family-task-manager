# UX-B4 — Budget Screen Fixes — Design

**Date:** 2026-09-29
**Status:** design approved in chat (2026-09-29), pending written-spec review
**Program:** UX/GUI/engagement program, sub-project **B4** of B (design-system consolidation). A, C1, C2, B1 shipped.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` F13; prod screenshots 2026-09-29 (demo family, phone width) of `/budget` (month), `/budget/transactions`, `/budget/reports`.

## What is wrong today

1. **Two different "available" numbers on the month screen.** The month card shows **Ready to assign $29,500** (envelope logic: money in on-budget accounts minus what is assigned, `AllocationService.compute_ready_to_assign`). Right under it, `MonthSummaryBar` shows **Income $0 · Spent $19,078 · Available −$19,078**, where "Available" is this month's income minus spending — a cash-flow number. Each category row also has its own "Available" column (envelope leftovers). Families whose money arrived as account opening balances see $0 income and a large negative "Available" next to a large positive "Ready to assign".
2. **Transactions is the odd page out.** Month and Reports put the Month / Transactions / Reports tabs at the top. Transactions puts a tall blue header (back arrow, title, month switcher, Income/Expenses/Net) above the tabs, so the tabs drop to the middle of the screen, and three things navigate (back arrow, tabs, bottom nav).

**Goal:** one budgeting story per screen, and the three budget tabs laid out the same way.

**Decisions from the brainstorm:**
- Month summary bar → **Budgeted / Spent / Left**, bar = % of budget spent.
- Transactions → **tabs on top**, then **one compact card** (month switcher + Income · Expenses · Net); no back arrow, no tall header.

**Not in B4:** dark mode (B2), visual consistency / tokens / UI kit (B3), any backend or budget-math change, the Ready-to-assign formula, the category list, Reports.

## Month screen summary bar

`frontend/src/components/MonthSummaryBar.astro` (rendered only by `frontend/src/pages/budget/index.astro`):

- Figures, left to right: **Asignado / Budgeted** (Σ `total_budgeted` of non-income groups), **Gastado / Spent** (|Σ `total_activity`| of non-income groups), **Restante / Left** (budgeted − spent).
- **Left** is green when ≥ 0 and red when < 0 (spent more than assigned).
- **Bar:** width = spent / budgeted, clamped 0–100 %; red when over budget, amber at ≥ 75 %, green otherwise (today's thresholds, now against the budget instead of income).
- **Caption:** "{N} % del presupuesto gastado" / "{N}% of budget spent". When nothing is budgeted: "Sin presupuesto asignado este mes" / "Nothing budgeted this month", and the bar is empty.
- **Income leaves this bar.** It stays visible in the category list's Income group and on Transactions.
- **One source of numbers:** the figures come from `budgetGlanceView` in `frontend/src/lib/parentHub.ts` (introduced in C2 for the parent home's budget card, same math as the budget dashboard). The page passes its month data to the bar; the bar does not re-derive sums. A month with no budget and no spending still renders the bar (zeros + the "nothing budgeted" caption) — it does not disappear the way the parent-home card does.

## Transactions page top

`frontend/src/pages/budget/transactions.astro`:

- **Remove** the `slot="before-nav"` blue `<header>`: the back arrow, the big "Transacciones" title, and its month switcher + Income/Expenses/Net box.
- **The tabs come first**, exactly like Month and Reports (BudgetShell already renders `BudgetNavNew` first when nothing is slotted before it).
- **Add one compact card** right under the tabs (in the `after-nav` slot, above the filter bar), styled like the month card on `/budget` (`bg-brand-cream`, `border-2 border-brand-ink`, `rounded-[var(--radius-card)]`, `shadow-[var(--shadow-card)]`):
  - Row 1: ‹ previous month · "{Mes} {año}" (capitalized, same `monthLabel` as today) · next month ›. Same URLs as today (`prevMonthUrl` / `nextMonthUrl`); "next" stays disabled on the current month. Buttons keep their `aria-label`s ("Mes anterior" / "Previous month", "Mes siguiente" / "Next month").
  - Row 2: three figures — **Ingresos / Income** (green), **Gastos / Expenses** (red), **Neto / Net** (ink when ≥ 0, red when < 0) — same values as today (`totalIncome`, `totalExpenses`, `netAmount`).
- The filter bar stays directly under the card. Everything else on the page (list, FAB, edit sheet, scripts) is unchanged.
- The document `<title>` stays "Transacciones - Presupuesto"; the active tab names the page.
- No scan button is added (the two-scan-triggers rule in CLAUDE.md stands).

## Units and files

| File | Change |
|------|--------|
| `frontend/src/components/MonthSummaryBar.astro` | new props + Budgeted/Spent/Left rendering |
| `frontend/src/lib/parentHub.ts` | add a small `monthSummaryView(month, lang)` that returns `{ budgetedCents, spentCents, leftCents, pct, over, caption }` built on `budgetGlanceView`'s math (kept in the same file so both views share one implementation) |
| `frontend/src/pages/budget/index.astro` | pass the month data / view to `MonthSummaryBar` |
| `frontend/src/pages/budget/transactions.astro` | header removed; compact card under the tabs |
| `frontend/test/parent-hub.test.ts` | `monthSummaryView` tests |

## Error handling

- Missing month data → the bar renders zeros with the "nothing budgeted" caption (never crashes the page).
- Budgeted 0 but spending > 0 → Left is negative (red), bar empty, caption "nothing budgeted".

## Testing

- **vitest** (`frontend/test/parent-hub.test.ts`, every test mutation-checked): `monthSummaryView` — normal month (figures, pct, left, caption), over budget (left < 0, over true, pct 100), nothing budgeted with spending (left = −spent, pct 0, caption "nothing budgeted"), missing month (zeros), income groups ignored, Spanish/English captions.
- `astro check` + `astro build`.
- **Manual on prod (demo family, read-only, verify `family_id == b8312b5a…`):** phone-width screenshots of `/budget` (bar says Budgeted/Spent/Left and matches the parent home's budget card) and `/budget/transactions` (tabs at the top, one compact card, no back arrow, month switcher works both ways).

## Rollout

One PR → CI → merge → `deploy-onprem.sh` (frontend only) → the manual checks above. No writes.
