/**
 * View models for the parent hub (UX-C2): per-kid row (counts, overdue chip,
 * pay meter, goal, nudge button state), budget glance numbers, and the
 * greeting date. Pure — vitest-covered.
 */
import { parseUtcInstant } from "./datetime";
import { payMeterView, type PayMeter } from "./kidHome";
import { progressLine } from "./progress";

/** Mirror of the backend's NUDGE_COOLDOWN (display only — the server decides). */
export const NUDGE_COOLDOWN_MS = 3 * 3600 * 1000;

export type NudgeState =
    | { kind: "ready" }
    | { kind: "cooldown"; hoursAgo: number }
    | { kind: "done" }
    | { kind: "none" };

export interface KidRowView {
    id: string;
    name: string;
    initial: string;
    doneLabel: string | null;
    overdueChip: string | null;
    meter: PayMeter;
    progressPct: number;
    goalLine: string | null;
    nudge: NudgeState;
    progressLine: string | null;
}

const n = (v: unknown) => {
    const x = Math.round(Number(v));
    return Number.isFinite(x) && x > 0 ? x : 0;
};

function nudgeState(kid: any, now: Date): NudgeState {
    const total = n(kid?.required_total_today);
    const open = n(kid?.required_open_today) + n(kid?.overdue_count);
    if (open === 0) return total > 0 ? { kind: "done" } : { kind: "none" };
    if (kid?.last_nudged_at) {
        const last = parseUtcInstant(String(kid.last_nudged_at)).getTime();
        if (Number.isFinite(last)) {
            const elapsed = now.getTime() - last;
            if (elapsed < NUDGE_COOLDOWN_MS) {
                return { kind: "cooldown", hoursAgo: Math.max(0, Math.floor(elapsed / 3600000)) };
            }
        }
    }
    return { kind: "ready" };
}

export function kidRowView(kid: any, paycheck: any, now: Date, lang: "es" | "en"): KidRowView {
    const es = lang === "es";
    const name = String(kid?.name ?? "");
    const total = n(kid?.required_total_today);
    const done = n(kid?.required_done_today);
    const overdue = n(kid?.overdue_count);
    const goal = kid?.goal;
    return {
        id: String(kid?.user_id ?? ""),
        name,
        initial: (name.trim().charAt(0) || "?").toUpperCase(),
        doneLabel: total > 0 ? `${done}/${total} ${es ? "hoy" : "today"}` : null,
        overdueChip: overdue > 0 ? (es ? `${overdue} atrasada${overdue === 1 ? "" : "s"}` : `${overdue} overdue`) : null,
        meter: payMeterView(paycheck),
        progressPct: total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0,
        goalLine: goal
            ? `🎯 ${goal.reward_title} · ${goal.affordable ? (es ? "¡lista!" : "ready!") : `${n(goal.progress_pct)}%`}`
            : null,
        nudge: nudgeState(kid, now),
        progressLine: progressLine(kid, lang),
    };
}

export function nudgeLabel(state: NudgeState, lang: "es" | "en"): string | null {
    const es = lang === "es";
    switch (state.kind) {
        case "ready":
            return es ? "⏰ Recordar" : "⏰ Remind";
        case "cooldown":
            if (state.hoursAgo < 1) return es ? "Enviado · hace menos de 1 h" : "Sent · under 1 h ago";
            return es ? `Enviado · hace ${state.hoursAgo} h` : `Sent · ${state.hoursAgo} h ago`;
        case "done":
            return es ? "✓ Listo" : "✓ Done";
        default:
            return null;
    }
}

export type BudgetGlance =
    | { show: false }
    | {
          show: true;
          spentCents: number;
          budgetedCents: number;
          pct: number;
          over: boolean;
          draftsLine: string | null;
          draftsCount: number;
      };

/** Expense-group totals for a budget month (non-income groups only):
 *  budgeted = Σ total_budgeted, spent = |Σ total_activity|, available =
 *  Σ total_available (the per-row "disponible", carryover included). The one
 *  implementation behind the parent-home card and the month summary bar. */
function expenseTotals(month: any): { budgetedCents: number; spentCents: number; availableCents: number } | null {
    if (!month || !Array.isArray(month.category_groups)) return null;
    const expense = month.category_groups.filter((g: any) => !g?.is_income);
    return {
        budgetedCents: expense.reduce((s: number, g: any) => s + (Number(g?.total_budgeted) || 0), 0),
        spentCents: Math.abs(expense.reduce((s: number, g: any) => s + (Number(g?.total_activity) || 0), 0)),
        availableCents: expense.reduce((s: number, g: any) => s + (Number(g?.total_available) || 0), 0),
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
    /** Σ of the category rows' "disponible" — so the bar and the rows agree. */
    availableCents: number;
    pct: number;
    over: boolean;
    tone: "over" | "warn" | "ok";
    caption: string;
    hasBudget: boolean;
}

/** Month screen summary bar (UX-B4): Budgeted / Spent / Available, in the
 *  same envelope terms as Ready-to-assign and the category rows (Available
 *  includes carryover, like each row). Always renders (zeros when data is
 *  missing), unlike the parent-home card which hides. */
export function monthSummaryView(month: any, lang: "es" | "en"): MonthSummary {
    const { budgetedCents, spentCents, availableCents } =
        expenseTotals(month) ?? { budgetedCents: 0, spentCents: 0, availableCents: 0 };
    const hasBudget = budgetedCents > 0;
    const pct = spentPct(spentCents, budgetedCents);
    const over = hasBudget && spentCents > budgetedCents;
    const es = lang === "es";
    return {
        budgetedCents,
        spentCents,
        availableCents,
        pct,
        over,
        tone: over ? "over" : pct >= 75 ? "warn" : "ok",
        caption: hasBudget
            ? (es ? `${pct} % del presupuesto gastado` : `${pct}% of budget spent`)
            : (es ? "Sin presupuesto asignado este mes" : "Nothing budgeted this month"),
        hasBudget,
    };
}

/** "Lunes 28 sep" / "Monday, Sep 28" in the family's timezone (UTC fallback). */
export function greetingDate(now: Date, lang: "es" | "en", tz: string | null | undefined): string {
    const locale = lang === "es" ? "es-MX" : "en-US";
    const make = (zone: string) =>
        new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "short", timeZone: zone });
    let fmt: Intl.DateTimeFormat;
    try {
        fmt = make(tz || "UTC");
    } catch {
        fmt = make("UTC");
    }
    const parts = fmt.formatToParts(now);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
    const weekday = get("weekday");
    const w = weekday.charAt(0).toUpperCase() + weekday.slice(1);
    const month = get("month").replace(/\.$/, "");
    return lang === "es" ? `${w} ${get("day")} ${month}` : `${w}, ${month} ${get("day")}`;
}

/** Month name for the budget glance header ("septiembre" / "September"). */
export function monthLabel(year: number, month: number, lang: "es" | "en"): string {
    return new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "en-US", { month: "long", timeZone: "UTC" }).format(
        new Date(Date.UTC(year, month - 1, 15)),
    );
}

export function firstName(name: unknown): string {
    if (typeof name !== "string") return "";
    return name.trim().split(/\s+/)[0] ?? "";
}
