import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { CHART_COPY, DAY_LABELS, isUnreadable, proposalRows, templateBody } from "../src/lib/chartScan";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");

const resp = {
    doc_type: "chore_chart", confidence: 0.9, chores: [
        { title: "Feed the dog", points: 15, is_bonus: false, days_of_week: [0, 2], assignee_names: ["Diego"], assigned_user_ids: ["d1"], unmatched_names: [], duplicate_of: null, description: "evenings" },
        { title: "Take out trash", points: 5, is_bonus: true, days_of_week: [], assignee_names: ["Pepe"], assigned_user_ids: [], unmatched_names: ["Pepe"], duplicate_of: "t9", description: null },
    ],
};

describe("proposalRows", () => {
    it("maps proposals, unticking duplicates", () => {
        const rows = proposalRows(resp);
        expect(rows).toHaveLength(2);
        expect(rows[0]).toMatchObject({ key: "r0", title: "Feed the dog", points: 15, isBonus: false, days: [0, 2], kidIds: ["d1"], unmatched: [], duplicate: false, description: "evenings", checked: true });
        expect(rows[1]).toMatchObject({ title: "Take out trash", isBonus: true, days: [], kidIds: [], unmatched: ["Pepe"], duplicate: true, description: null, checked: false });
    });
    it("is empty for garbage", () => {
        for (const v of [null, undefined, {}, { chores: "x" }, { chores: [null, 1] }]) expect(proposalRows(v)).toEqual([]);
    });
});

describe("isUnreadable", () => {
    it("low confidence or no rows", () => {
        expect(isUnreadable({ confidence: 0.2, chores: [{ title: "x" }] })).toBe(true);
        expect(isUnreadable({ confidence: 0.9, chores: [] })).toBe(true);
        expect(isUnreadable(resp)).toBe(false);
        expect(isUnreadable(null)).toBe(true);
    });
});

describe("templateBody", () => {
    const row = proposalRows(resp)[0];
    it("FIXED with the kids when any are selected, days as given", () => {
        expect(templateBody(row)).toEqual({
            title: "Feed the dog", points: 15, is_bonus: false, days_of_week: [0, 2], interval_days: 1,
            assignment_type: "fixed", assigned_user_ids: ["d1"], description: "evenings",
        });
    });
    it("AUTO with no kids, null days when every day, no description when empty", () => {
        expect(templateBody({ ...row, kidIds: [], days: [], description: null, title: "  Sweep  " })).toEqual({
            title: "Sweep", points: 15, is_bonus: false, days_of_week: null, interval_days: 1, assignment_type: "auto", assigned_user_ids: null, description: null,
        });
    });
    it("points are whole numbers inside the app's range", () => {
        expect(templateBody({ ...row, points: 1500 }).points).toBe(1000);
        expect(templateBody({ ...row, points: -3 }).points).toBe(0);
        expect(templateBody({ ...row, points: 7.6 }).points).toBe(8);
    });
});

describe("copy", () => {
    it("has both languages and seven day labels", () => {
        expect(DAY_LABELS.es).toHaveLength(7);
        expect(DAY_LABELS.en).toHaveLength(7);
        for (const key of ["title", "pick", "scanning", "found", "anyone", "exists", "unmatched", "create", "done", "unreadable", "failed"] as const) {
            expect(CHART_COPY[key].es.length).toBeGreaterThan(2);
            expect(CHART_COPY[key].en.length).toBeGreaterThan(2);
        }
    });
});

describe("page", () => {
    const page = read("../src/pages/parent/tasks/scan.astro");
    it("is parent-only, paid-gated with the upgrade prompt, sky tone", () => {
        expect(page).toMatch(/if \(user\.role !== "parent"\) return Astro\.redirect\("\/dashboard"\);/);
        expect(page).toMatch(/const aiLocked = await isFreePlan\(token\);/);
        expect(page).toContain("<UpgradePrompt");
        expect(page).toMatch(/tone="sky"/);
    });
    it("scans through the proxied route and creates each ticked row through the ordinary chore API", () => {
        expect(page).toMatch(/fetch\("\/api\/task-templates\/scan-chart"/);
        expect(page).toMatch(/fetch\("\/api\/task-templates\/", \{\s*method: "POST"/);
        expect(page).toMatch(/templateBody\(/);
        expect(page).toMatch(/proposalRows\(/);
        expect(page).toMatch(/isUnreadable\(/);
        expect(existsSync(path("../src/pages/api/task-templates/[...path].ts"))).toBe(true);
    });
    it("a failed row stays with its message and a created row cannot be re-posted", () => {
        expect(page).toMatch(/data-row-error/);
        expect(page).toMatch(/created\.add\(row\.key\)/);
        expect(page).toMatch(/if \(created\.has\(row\.key\)\) continue;/);
    });
    it("uses no native dialog, no emoji in a heading 1, and a hidden attribute for states", () => {
        expect(page).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(page).not.toMatch(/<h1[^>]*>[^<]*[\u{1F300}-\u{1FAFF}]/u);
        expect(page).toMatch(/id="scanning" hidden/);
        expect(page).toMatch(/id="results" hidden/);
    });
});
