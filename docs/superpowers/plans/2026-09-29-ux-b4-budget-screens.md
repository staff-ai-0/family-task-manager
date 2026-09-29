# UX-B4 Budget Screen Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the month screen's summary bar tell the same envelope story as "Ready to assign" (Budgeted / Spent / Left), and give Transactions the same layout as Month and Reports (tabs on top, one compact month card).

**Architecture:** A pure `monthSummaryView` in `lib/parentHub.ts` shares one expense-totals helper with C2's `budgetGlanceView`; `MonthSummaryBar.astro` renders that view. Transactions drops its tall header and renders a compact card in BudgetShell's `after-nav` slot.

**Tech Stack:** Astro 5 SSR, Tailwind v4, vitest (node).

**Spec:** `docs/superpowers/specs/2026-09-29-ux-b4-budget-screens-design.md`

## Execution environment (read once)

- Worktree: `/Users/jc/dev-2026/AgentIA/family-task-manager/.claude/worktrees/ux-b4-budget-screens` (branch `feat/ux-b4-budget-screens`). Never edit the main checkout.
- From the worktree's `frontend/`: run `npm ci` once if `node_modules` is missing; then `npx vitest run test/<file>.test.ts`, `npx vitest run`, `npm run check`, `npm run build`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never run `git stash`.

## Global Constraints

- Frontend only; no backend or budget-math change; the Ready-to-assign formula and the category list are untouched.
- Month bar figures: **Asignado / Budgeted** = Σ `total_budgeted` of non-income groups; **Gastado / Spent** = |Σ `total_activity`| of non-income groups; **Restante / Left** = budgeted − spent.
- Left green when ≥ 0, red when < 0. Bar width = spent / budgeted clamped 0–100; red when over budget, amber at ≥ 75 %, green otherwise.
- Caption: "{N} % del presupuesto gastado" / "{N}% of budget spent"; with nothing budgeted: "Sin presupuesto asignado este mes" / "Nothing budgeted this month" and an empty bar.
- One source of numbers: `budgetGlanceView` and `monthSummaryView` share the same expense-totals helper.
- Transactions: tabs first; one compact card (month switcher + Income · Expenses · Net) styled like the month card (`bg-brand-cream`, `border-2 border-brand-ink`, `rounded-[var(--radius-card)]`, `shadow-[var(--shadow-card)]`); no back arrow; same month URLs; "next" disabled on the current month; document `<title>` unchanged; no scan button added.
- Every new test is mutation-checked.

## Review Focus

1. **Budget 0 but money spent** → Left = −spent (red), bar empty, caption "nothing budgeted" (not "0 % spent"). Pinned in Task 1.
2. **Over budget by a little** (spent 101 % of budgeted) → bar full and red, Left negative. Pinned in Task 1.
3. **Missing / malformed month data** (`null`, no `category_groups`) → zeros, "nothing budgeted", no crash. Pinned in Task 1.
4. **Income groups with activity** never leak into Budgeted/Spent. Pinned in Task 1.
5. **Parent-home card and month bar agree** on spent/budgeted for the same month data. Pinned in Task 1 (same input through both functions).

---

### Task 1: Month summary bar — Budgeted / Spent / Left

**Files:**
- Modify: `frontend/src/lib/parentHub.ts` (shared `expenseTotals`, new `monthSummaryView`)
- Modify: `frontend/src/components/MonthSummaryBar.astro`
- Modify: `frontend/src/pages/budget/index.astro` (the `<MonthSummaryBar … />` call, ~line 129)
- Test: `frontend/test/parent-hub.test.ts`

**Interfaces:**
- Produces:
  - `interface MonthSummary { budgetedCents: number; spentCents: number; leftCents: number; pct: number; over: boolean; tone: "over" | "warn" | "ok"; caption: string; hasBudget: boolean }`
  - `monthSummaryView(month: any, lang: "es" | "en"): MonthSummary`
  - `MonthSummaryBar` props become `{ view: MonthSummary; lang: "en" | "es"; formatCurrency: (amount: number) => string }`

- [ ] **Step 1: Write the failing tests**

In `frontend/test/parent-hub.test.ts`, add `monthSummaryView` to the import list from `../src/lib/parentHub`, then append:

```ts
describe("monthSummaryView", () => {
    const month = (groups: unknown[]) => ({ category_groups: groups });
    const expense = (budgeted: number, activity: number) => ({ is_income: false, total_budgeted: budgeted, total_activity: activity });
    const income = (activity: number) => ({ is_income: true, total_budgeted: 0, total_activity: activity });

    it("budgeted, spent and left for a normal month", () => {
        const v = monthSummaryView(month([expense(1_000_000, -450_000), expense(200_000, -150_000), income(3_000_000)]), "es");
        expect(v).toMatchObject({ budgetedCents: 1_200_000, spentCents: 600_000, leftCents: 600_000, pct: 50, over: false, tone: "ok", hasBudget: true });
        expect(v.caption).toBe("50 % del presupuesto gastado");
        expect(monthSummaryView(month([expense(1_000, -500)]), "en").caption).toBe("50% of budget spent");
    });
    it("warns from 75 % and goes red over budget", () => {
        expect(monthSummaryView(month([expense(1_000, -750)]), "es").tone).toBe("warn");
        const over = monthSummaryView(month([expense(1_000, -1_010)]), "es");
        expect(over).toMatchObject({ pct: 100, over: true, tone: "over", leftCents: -10 });
    });
    it("spending with nothing budgeted", () => {
        const v = monthSummaryView(month([expense(0, -1_907_800)]), "es");
        expect(v).toMatchObject({ budgetedCents: 0, spentCents: 1_907_800, leftCents: -1_907_800, pct: 0, over: false, hasBudget: false });
        expect(v.caption).toBe("Sin presupuesto asignado este mes");
        expect(monthSummaryView(month([expense(0, -1)]), "en").caption).toBe("Nothing budgeted this month");
    });
    it("missing or malformed month data is all zeros", () => {
        for (const m of [null, undefined, {}, { category_groups: "x" }]) {
            expect(monthSummaryView(m, "es")).toMatchObject({ budgetedCents: 0, spentCents: 0, leftCents: 0, pct: 0, over: false, hasBudget: false });
        }
    });
    it("income groups never count", () => {
        expect(monthSummaryView(month([income(5_000_000)]), "es")).toMatchObject({ budgetedCents: 0, spentCents: 0 });
    });
    it("agrees with the parent-home budget card on the same data", () => {
        const m = month([expense(1_200_000, -824_000), income(3_000_000)]);
        const card = budgetGlanceView(m, 0, "es");
        const bar = monthSummaryView(m, "es");
        expect(card.show).toBe(true);
        if (card.show) {
            expect([bar.budgetedCents, bar.spentCents, bar.pct, bar.over]).toEqual([card.budgetedCents, card.spentCents, card.pct, card.over]);
        }
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run (from `frontend/`): `npx vitest run test/parent-hub.test.ts`
Expected: FAIL — `monthSummaryView` is not exported.

- [ ] **Step 3: Implement in `frontend/src/lib/parentHub.ts`**

Replace the body of `budgetGlanceView` so it uses a shared helper, and add `monthSummaryView` right after it. The final code for this part of the file:

```ts
/** Expense-group totals for a budget month (non-income groups only):
 *  budgeted = Σ total_budgeted, spent = |Σ total_activity|. The one
 *  implementation behind the parent-home card and the month summary bar,
 *  and the same math as pages/budget/index.astro. */
function expenseTotals(month: any): { budgetedCents: number; spentCents: number } | null {
    if (!month || !Array.isArray(month.category_groups)) return null;
    const expense = month.category_groups.filter((g: any) => !g?.is_income);
    return {
        budgetedCents: expense.reduce((s: number, g: any) => s + (Number(g?.total_budgeted) || 0), 0),
        spentCents: Math.abs(expense.reduce((s: number, g: any) => s + (Number(g?.total_activity) || 0), 0)),
    };
}

const spentPct = (spentCents: number, budgetedCents: number) =>
    budgetedCents > 0 ? Math.max(0, Math.min(100, Math.round((spentCents / budgetedCents) * 100))) : 0;

/** Same math as the budget dashboard (pages/budget/index.astro): expense
 *  groups only; spent = |Σ activity|, budgeted = Σ total_budgeted. */
export function budgetGlanceView(month: any, draftsCount: number, lang: "es" | "en"): BudgetGlance {
    const totals = expenseTotals(month);
    if (!totals) return { show: false };
    const { budgetedCents, spentCents } = totals;
    if (budgetedCents <= 0 && spentCents <= 0) return { show: false };
    const drafts = n(draftsCount);
    const es = lang === "es";
    return {
        show: true,
        spentCents,
        budgetedCents,
        pct: spentPct(spentCents, budgetedCents),
        over: budgetedCents > 0 && spentCents > budgetedCents,
        draftsLine: drafts > 0
            ? (es ? `🧾 ${drafts} ticket${drafts === 1 ? "" : "s"} por revisar` : `🧾 ${drafts} receipt${drafts === 1 ? "" : "s"} to review`)
            : null,
        draftsCount: drafts,
    };
}

export interface MonthSummary {
    budgetedCents: number;
    spentCents: number;
    leftCents: number;
    pct: number;
    over: boolean;
    tone: "over" | "warn" | "ok";
    caption: string;
    hasBudget: boolean;
}

/** Month screen summary bar (UX-B4): Budgeted / Spent / Left, in the same
 *  envelope terms as Ready-to-assign. Always renders (zeros when data is
 *  missing), unlike the parent-home card which hides. */
export function monthSummaryView(month: any, lang: "es" | "en"): MonthSummary {
    const { budgetedCents, spentCents } = expenseTotals(month) ?? { budgetedCents: 0, spentCents: 0 };
    const hasBudget = budgetedCents > 0;
    const pct = spentPct(spentCents, budgetedCents);
    const over = hasBudget && spentCents > budgetedCents;
    const es = lang === "es";
    return {
        budgetedCents,
        spentCents,
        leftCents: budgetedCents - spentCents,
        pct,
        over,
        tone: over ? "over" : pct >= 75 ? "warn" : "ok",
        caption: hasBudget
            ? (es ? `${pct} % del presupuesto gastado` : `${pct}% of budget spent`)
            : (es ? "Sin presupuesto asignado este mes" : "Nothing budgeted this month"),
        hasBudget,
    };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run test/parent-hub.test.ts`
Expected: PASS (all previous `budgetGlanceView` tests still pass too).

- [ ] **Step 5: Rewrite `frontend/src/components/MonthSummaryBar.astro`**

Replace the whole file with:

```astro
---
/**
 * Month screen summary (UX-B4): Budgeted / Spent / Left — the same envelope
 * story as "Ready to assign" above it. Numbers come from monthSummaryView
 * (lib/parentHub.ts), shared with the parent home's budget card.
 */
import type { MonthSummary } from "../lib/parentHub";

interface Props {
    view: MonthSummary;
    lang: "en" | "es";
    formatCurrency: (amount: number) => string;
}

const { view, lang, formatCurrency } = Astro.props;
const es = lang === "es";
const barColor = view.tone === "over" ? "bg-red-500" : view.tone === "warn" ? "bg-brand-sun-deep" : "bg-brand-mint-deep";
const labels = {
    budgeted: es ? "Asignado" : "Budgeted",
    spent: es ? "Gastado" : "Spent",
    left: es ? "Restante" : "Left",
};
---

<div class="bg-brand-cream rounded-[var(--radius-card)] border-2 border-brand-ink/10 shadow-[var(--shadow-card)] p-4 mx-4 mt-3">
    <div class="flex text-center">
        <div class="flex-1">
            <div class="text-[10px] text-brand-ink-soft uppercase">{labels.budgeted}</div>
            <div class="text-sm font-bold text-brand-ink">{formatCurrency(view.budgetedCents)}</div>
        </div>
        <div class="flex-1">
            <div class="text-[10px] text-brand-ink-soft uppercase">{labels.spent}</div>
            <div class="text-sm font-bold text-red-500">{formatCurrency(view.spentCents)}</div>
        </div>
        <div class="flex-1">
            <div class="text-[10px] text-brand-ink-soft uppercase">{labels.left}</div>
            <div class:list={["text-sm font-bold", view.leftCents >= 0 ? "text-brand-mint-deep" : "text-red-500"]}>
                {formatCurrency(view.leftCents)}
            </div>
        </div>
    </div>
    <div class="w-full bg-brand-cream-deep rounded-full h-2 mt-3">
        <div
            class:list={["h-2 rounded-full transition-all duration-300", barColor]}
            style={`width: ${view.hasBudget ? view.pct : 0}%`}
        ></div>
    </div>
    <div class="text-[10px] text-brand-ink-soft text-right mt-1">{view.caption}</div>
</div>
```

- [ ] **Step 6: Wire `frontend/src/pages/budget/index.astro`**

Add `monthSummaryView` to an import from `@lib/parentHub` (or `../../lib/parentHub`, matching the file's import style), and replace the `<MonthSummaryBar income={totalIncome} spent={totalSpent} budgeted={totalBudgeted} lang={lang} formatCurrency={formatCurrency} />` call with:

```astro
        <MonthSummaryBar
            view={monthSummaryView(budget, lang)}
            lang={lang}
            formatCurrency={formatCurrency}
        />
```

Leave `totalIncome`, `totalBudgeted`, `totalSpent` in the frontmatter if other code in the page still uses them (e.g. the Ready-to-assign fallback); remove only variables that become unused (astro check will flag them as hints).

- [ ] **Step 7: Verify** — from `frontend/`: `npx vitest run && npm run check && npm run build` (0 errors).

- [ ] **Step 8: Mutation-check** — one at a time, confirm the named test fails, then restore: (a) in `expenseTotals` drop the `!g?.is_income` filter → "income groups never count"; (b) in `monthSummaryView` drop `hasBudget &&` from `over` → "spending with nothing budgeted" (over becomes true); (c) return the "% gastado" caption even when `!hasBudget` → "spending with nothing budgeted"; (d) make `budgetGlanceView` compute its own `pct` with `Math.floor` → "agrees with the parent-home budget card".

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/parentHub.ts frontend/src/components/MonthSummaryBar.astro frontend/src/pages/budget/index.astro frontend/test/parent-hub.test.ts
git commit -m "feat(budget): month bar shows Budgeted / Spent / Left

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Transactions — tabs on top, one compact month card

**Files:**
- Modify: `frontend/src/pages/budget/transactions.astro` (the `<!-- Header -->` block, ~lines 174–235)

**Interfaces:**
- Consumes: frontmatter values already in the page: `prevMonthUrl`, `nextMonthUrl`, `monthLabel`, `isCurrentMonth`, `totalIncome`, `totalExpenses`, `netAmount`, `formatCurrency`, `es`.

- [ ] **Step 1: Replace the header**

Delete the whole block from `<!-- Header -->` through its closing `</header>` (the `<header slot="before-nav" class="bg-brand-sky-deep …">` element: back arrow, title, month navigation, summary). In its place, directly above `<!-- Filter Bar -->`, add:

```astro
        <!-- Month card (UX-B4): the tabs come first, like Month and Reports;
             this card replaces the old tall header (no back arrow — the tabs
             and the bottom nav already navigate). -->
        <section slot="after-nav" class="px-4 pt-3" aria-label={es ? "Mes" : "Month"}>
            <div class="bg-brand-cream rounded-[var(--radius-card)] border-2 border-brand-ink shadow-[var(--shadow-card)] p-3">
                <div class="flex items-center justify-between">
                    <a href={prevMonthUrl} class="p-1.5 rounded-full border-2 border-brand-ink text-brand-ink hover:bg-brand-cream-deep transition" aria-label={es ? "Mes anterior" : "Previous month"}>
                        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 19l-7-7 7-7" />
                        </svg>
                    </a>
                    <span class="text-sm font-extrabold text-brand-ink capitalize">{monthLabel}</span>
                    {isCurrentMonth ? (
                        <span class="p-1.5 rounded-full border-2 border-brand-ink/20 text-brand-ink/30" aria-hidden="true">
                            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7" />
                            </svg>
                        </span>
                    ) : (
                        <a href={nextMonthUrl} class="p-1.5 rounded-full border-2 border-brand-ink text-brand-ink hover:bg-brand-cream-deep transition" aria-label={es ? "Mes siguiente" : "Next month"}>
                            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7" />
                            </svg>
                        </a>
                    )}
                </div>
                <div class="grid grid-cols-3 gap-2 text-center mt-3">
                    <div>
                        <p class="text-[10px] font-semibold uppercase tracking-wider text-brand-ink-soft">{es ? "Ingresos" : "Income"}</p>
                        <p class="text-sm font-bold text-brand-mint-deep">{formatCurrency(totalIncome)}</p>
                    </div>
                    <div>
                        <p class="text-[10px] font-semibold uppercase tracking-wider text-brand-ink-soft">{es ? "Gastos" : "Expenses"}</p>
                        <p class="text-sm font-bold text-red-500">{formatCurrency(totalExpenses)}</p>
                    </div>
                    <div>
                        <p class="text-[10px] font-semibold uppercase tracking-wider text-brand-ink-soft">{es ? "Neto" : "Net"}</p>
                        <p class={`text-sm font-bold ${netAmount >= 0 ? "text-brand-ink" : "text-red-500"}`}>{formatCurrency(netAmount)}</p>
                    </div>
                </div>
            </div>
        </section>
```

(Multiple `slot="after-nav"` elements already exist on this page — the filter bar and the saved-filters bar — and render in source order, so this card lands between the tabs and the filter bar.)

- [ ] **Step 2: Clean up** — if removing the header left frontmatter variables unused (check `npm run check` hints for this file), remove only those. Keep the `<title>` prop of `BudgetShell` unchanged.

- [ ] **Step 3: Verify the structure** — from `frontend/`:
  - `npm run check && npm run build` (0 errors)
  - `grep -c 'slot="before-nav"' src/pages/budget/transactions.astro` → `0`
  - `grep -n 'href="/budget"' src/pages/budget/transactions.astro` → no back-arrow link left
  - `grep -nE "data-scan-receipt-open|ftm:scan-receipt" src/pages/budget/transactions.astro` → no new scan trigger (the FAB's is in a component, not this file)
  - `npx vitest run` (guard test `no-native-dialogs` and the rest stay green)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/budget/transactions.astro
git commit -m "feat(budget): transactions puts the tabs first and a compact month card

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Final verification (controller)

- `npx vitest run`, `npm run check`, `npm run build` on the branch head; whole-branch review; one fix wave; scoped re-review.
- Ship: PR → CI → merge → `./scripts/deploy-onprem.sh -y` → read-only prod pass as the demo parent after confirming `family_id == b8312b5a-c9c0-469f-992f-8dbd412db4a7`: phone-width screenshots of `/budget` (Budgeted/Spent/Left; spent/budgeted match the parent home's budget card) and `/budget/transactions` (tabs at the top, one compact card, no back arrow; previous month link works; next is disabled on the current month).
