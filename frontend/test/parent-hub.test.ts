import { describe, expect, it } from "vitest";

import {
    NUDGE_COOLDOWN_MS,
    budgetGlanceView,
    firstName,
    greetingDate,
    kidRowView,
    monthLabel,
    monthSummaryView,
    nudgeLabel,
} from "../src/lib/parentHub";

const NOW = new Date("2026-09-28T20:00:00Z");
const H = 3600 * 1000;
const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString();
const kid = (over: Record<string, unknown> = {}) => ({
    user_id: "k1", name: "Diego Martinez", role: "teen", points: 340, goal: null,
    required_total_today: 5, required_done_today: 2, required_open_today: 3, overdue_count: 1,
    last_nudged_at: null, ...over,
});

describe("kidRowView nudge state", () => {
    it("is ready while work is open and nobody nudged recently", () => {
        expect(kidRowView(kid(), null, NOW, "es").nudge).toEqual({ kind: "ready" });
    });
    it("cools down for 3 h after a nudge", () => {
        expect(kidRowView(kid({ last_nudged_at: ago(2 * H + 59 * 60 * 1000) }), null, NOW, "es").nudge)
            .toEqual({ kind: "cooldown", hoursAgo: 2 });
        expect(kidRowView(kid({ last_nudged_at: ago(3 * H + 60 * 1000) }), null, NOW, "es").nudge)
            .toEqual({ kind: "ready" });
    });
    it("offers a nudge when only overdue work is left", () => {
        const k = kid({ required_total_today: 0, required_done_today: 0, required_open_today: 0, overdue_count: 2 });
        expect(kidRowView(k, null, NOW, "es").nudge).toEqual({ kind: "ready" });
    });
    it("says done when today's chores are handled (a cancelled one included)", () => {
        const k = kid({ required_total_today: 4, required_done_today: 3, required_open_today: 0, overdue_count: 0 });
        expect(kidRowView(k, null, NOW, "es").nudge).toEqual({ kind: "done" });
    });
    it("shows nothing when the kid has no chores at all", () => {
        const k = kid({ required_total_today: 0, required_done_today: 0, required_open_today: 0, overdue_count: 0 });
        expect(kidRowView(k, null, NOW, "es").nudge).toEqual({ kind: "none" });
    });
    it("ignores a recent nudge once nothing is open", () => {
        const k = kid({ required_total_today: 2, required_done_today: 2, required_open_today: 0, overdue_count: 0, last_nudged_at: ago(H) });
        expect(kidRowView(k, null, NOW, "es").nudge).toEqual({ kind: "done" });
    });
    it("treats a nudge stamped in the future as just sent", () => {
        const future = new Date(NOW.getTime() + 5 * 60 * 1000).toISOString();
        expect(kidRowView(kid({ last_nudged_at: future }), null, NOW, "es").nudge).toEqual({ kind: "cooldown", hoursAgo: 0 });
    });
    it("reads naive backend timestamps as UTC", () => {
        // 2h ago in UTC, written without a zone
        expect(kidRowView(kid({ last_nudged_at: "2026-09-28T18:00:00" }), null, NOW, "es").nudge)
            .toEqual({ kind: "cooldown", hoursAgo: 2 });
    });
    it("pins the cooldown to 3 h", () => {
        expect(NUDGE_COOLDOWN_MS).toBe(3 * H);
    });
});

describe("kidRowView labels", () => {
    it("counts today and the overdue chip", () => {
        const es = kidRowView(kid(), null, NOW, "es");
        expect(es.doneLabel).toBe("2/5 hoy");
        expect(es.overdueChip).toBe("1 atrasada");
        expect(kidRowView(kid({ overdue_count: 3 }), null, NOW, "es").overdueChip).toBe("3 atrasadas");
        const en = kidRowView(kid({ overdue_count: 3 }), null, NOW, "en");
        expect(en.doneLabel).toBe("2/5 today");
        expect(en.overdueChip).toBe("3 overdue");
        expect(kidRowView(kid({ overdue_count: 0 }), null, NOW, "es").overdueChip).toBeNull();
    });
    it("hides the done label when nothing is assigned today", () => {
        const k = kid({ required_total_today: 0, required_done_today: 0, required_open_today: 0 });
        expect(kidRowView(k, null, NOW, "es").doneLabel).toBeNull();
    });
    it("uses the pay meter only in chore mode, a plain bar otherwise", () => {
        const plain = kidRowView(kid(), { mode: "flat", cap_cents: 0 }, NOW, "es");
        expect(plain.meter).toEqual({ show: false });
        expect(plain.progressPct).toBe(40);
        const paid = kidRowView(kid(), { mode: "chore_proportional", cap_cents: 25000, pct: 48, discounted_pct: 8 }, NOW, "es");
        expect(paid.meter).toMatchObject({ show: true, greenPct: 48, redPct: 8 });
    });
    it("goal line", () => {
        const goal = { reward_title: "Audífonos", progress_pct: 60, affordable: false, pts_to_go: 80 };
        expect(kidRowView(kid({ goal }), null, NOW, "es").goalLine).toBe("🎯 Audífonos · 60%");
        expect(kidRowView(kid({ goal: { ...goal, affordable: true } }), null, NOW, "es").goalLine).toBe("🎯 Audífonos · ¡lista!");
        expect(kidRowView(kid({ goal: { ...goal, affordable: true } }), null, NOW, "en").goalLine).toBe("🎯 Audífonos · ready!");
        expect(kidRowView(kid(), null, NOW, "es").goalLine).toBeNull();
    });
    it("identity", () => {
        expect(kidRowView(kid(), null, NOW, "es")).toMatchObject({ id: "k1", name: "Diego Martinez", initial: "D" });
    });
});

describe("nudgeLabel", () => {
    it("labels every state in both languages", () => {
        expect(nudgeLabel({ kind: "ready" }, "es")).toBe("⏰ Recordar");
        expect(nudgeLabel({ kind: "ready" }, "en")).toBe("⏰ Remind");
        expect(nudgeLabel({ kind: "cooldown", hoursAgo: 0 }, "es")).toBe("Enviado · hace menos de 1 h");
        expect(nudgeLabel({ kind: "cooldown", hoursAgo: 2 }, "es")).toBe("Enviado · hace 2 h");
        expect(nudgeLabel({ kind: "cooldown", hoursAgo: 0 }, "en")).toBe("Sent · under 1 h ago");
        expect(nudgeLabel({ kind: "cooldown", hoursAgo: 2 }, "en")).toBe("Sent · 2 h ago");
        expect(nudgeLabel({ kind: "done" }, "es")).toBe("✓ Listo");
        expect(nudgeLabel({ kind: "done" }, "en")).toBe("✓ Done");
        expect(nudgeLabel({ kind: "none" }, "es")).toBeNull();
    });
});

describe("budgetGlanceView", () => {
    const month = (groups: unknown[]) => ({ category_groups: groups });
    it("sums expense groups only and reads activity as spending", () => {
        const view = budgetGlanceView(month([
            { is_income: false, total_budgeted: 1200000, total_activity: -824000 },
            { is_income: true, total_budgeted: 0, total_activity: 3000000 },
        ]), 0, "es");
        expect(view).toEqual({ show: true, spentCents: 824000, budgetedCents: 1200000, pct: 69, over: false, draftsLine: null, draftsCount: 0 });
    });
    it("flags over budget and clamps the bar", () => {
        const view = budgetGlanceView(month([{ is_income: false, total_budgeted: 100, total_activity: -150 }]), 0, "es");
        expect(view).toMatchObject({ show: true, pct: 100, over: true });
    });
    it("has no percent without a budget", () => {
        const view = budgetGlanceView(month([{ is_income: false, total_budgeted: 0, total_activity: -500 }]), 0, "es");
        expect(view).toMatchObject({ show: true, spentCents: 500, pct: 0, over: false });
    });
    it("is hidden when the month is missing or empty", () => {
        expect(budgetGlanceView(null, 3, "es")).toEqual({ show: false });
        expect(budgetGlanceView(month([{ is_income: false, total_budgeted: 0, total_activity: 0 }]), 0, "es")).toEqual({ show: false });
    });
    it("drafts line", () => {
        const m = month([{ is_income: false, total_budgeted: 100, total_activity: -10 }]);
        expect(budgetGlanceView(m, 1, "es")).toMatchObject({ draftsLine: "🧾 1 ticket por revisar", draftsCount: 1 });
        expect(budgetGlanceView(m, 2, "en")).toMatchObject({ draftsLine: "🧾 2 receipts to review", draftsCount: 2 });
    });
});

describe("greetingDate / monthLabel / firstName", () => {
    it("uses the family's day", () => {
        const late = new Date("2026-09-29T03:00:00Z"); // 21:00 on the 28th in Mexico City
        const mx = greetingDate(late, "es", "America/Mexico_City");
        expect(mx.startsWith("Lunes")).toBe(true);
        expect(mx).toContain("28");
        const utc = greetingDate(late, "es", "UTC");
        expect(utc.startsWith("Martes")).toBe(true);
        expect(utc).toContain("29");
    });
    it("english and a bad timezone fall back to UTC", () => {
        const en = greetingDate(NOW, "en", "Not/AZone");
        expect(en.startsWith("Monday")).toBe(true);
        expect(en).toContain("28");
    });
    it("month label", () => {
        expect(monthLabel(2026, 9, "es")).toBe("septiembre");
        expect(monthLabel(2026, 9, "en")).toBe("September");
    });
    it("first name", () => {
        expect(firstName("Juan Carlos Martinez")).toBe("Juan");
        expect(firstName("   ")).toBe("");
        expect(firstName(null)).toBe("");
    });
});

describe("kidRowView progress line (UX-D1)", () => {
    it("shows streak and rank name for the kid's role", () => {
        const v = kidRowView({ user_id: "k1", name: "Sofía", role: "child", streak_days: 5, rank: 4 }, null, new Date(), "es");
        expect(v.progressLine).toBe("🔥 5 · Estrella");
    });
    it("is null without progress fields", () => {
        const v = kidRowView({ user_id: "k1", name: "Sofía", role: "child" }, null, new Date(), "es");
        expect(v.progressLine).toBeNull();
    });
});

describe("monthSummaryView", () => {
    const month = (groups: unknown[]) => ({ category_groups: groups });
    // total_available defaults to budgeted + activity (no carryover), as the backend computes per group.
    const expense = (budgeted: number, activity: number, available = budgeted + activity) => ({ is_income: false, total_budgeted: budgeted, total_activity: activity, total_available: available });
    const income = (activity: number) => ({ is_income: true, total_budgeted: 0, total_activity: activity });

    it("budgeted, spent and left for a normal month", () => {
        const v = monthSummaryView(month([expense(1_000_000, -450_000), expense(200_000, -150_000), income(3_000_000)]), "es");
        expect(v).toMatchObject({ budgetedCents: 1_200_000, spentCents: 600_000, availableCents: 600_000, pct: 50, over: false, tone: "ok", hasBudget: true });
        expect(v.caption).toBe("50 % del presupuesto gastado");
        expect(monthSummaryView(month([expense(1_000, -500)]), "en").caption).toBe("50% of budget spent");
    });
    it("warns from 75 % and goes red over budget", () => {
        expect(monthSummaryView(month([expense(1_000, -750)]), "es").tone).toBe("warn");
        const over = monthSummaryView(month([expense(1_000, -1_010)]), "es");
        expect(over).toMatchObject({ pct: 100, over: true, tone: "over", availableCents: -10 });
    });
    it("spending with nothing budgeted", () => {
        const v = monthSummaryView(month([expense(0, -1_907_800)]), "es");
        expect(v).toMatchObject({ budgetedCents: 0, spentCents: 1_907_800, availableCents: -1_907_800, pct: 0, over: false, hasBudget: false });
        expect(v.caption).toBe("Sin presupuesto asignado este mes");
        expect(monthSummaryView(month([expense(0, -1)]), "en").caption).toBe("Nothing budgeted this month");
    });
    it("missing or malformed month data is all zeros", () => {
        for (const m of [null, undefined, {}, { category_groups: "x" }]) {
            expect(monthSummaryView(m, "es")).toMatchObject({ budgetedCents: 0, spentCents: 0, availableCents: 0, pct: 0, over: false, hasBudget: false });
        }
    });
    it("available matches the category rows when money carries over", () => {
        // $1,000 carried over + $5,000 budgeted − $5,500 spent → the row says +$500 disponible.
        const v = monthSummaryView(month([expense(500_000, -550_000, 50_000)]), "es");
        expect(v).toMatchObject({ budgetedCents: 500_000, spentCents: 550_000, availableCents: 50_000, over: true, tone: "over" });
        // Last month overspent: the row carries the debt, and so does the bar.
        expect(monthSummaryView(month([expense(500_000, -100_000, -20_000)]), "es").availableCents).toBe(-20_000);
    });
    it("a group without total_available counts as zero available", () => {
        expect(monthSummaryView(month([{ is_income: false, total_budgeted: 1_000, total_activity: -200 }]), "es").availableCents).toBe(0);
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
