import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { progressDomUpdate, progressLine, progressView, rankName, RANK_NAMES, shouldCelebrate } from "../src/lib/progress";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

const resp = (over: Record<string, unknown> = {}) => ({
    applies: true, xp: 450, rank: 3, rank_floor_xp: 300, next_rank_xp: 600, streak_days: 5,
    shield_used: true, celebrate_rank: null,
    week: [
        { date: "2026-09-28", state: "done" }, { date: "2026-09-29", state: "shield" },
        { date: "2026-09-30", state: "done" }, { date: "2026-10-01", state: "today" },
        { date: "2026-10-02", state: "future" }, { date: "2026-10-03", state: "future" },
        { date: "2026-10-04", state: "future" },
    ],
    ...over,
});

describe("rankName", () => {
    it("has 10 names per skin and language", () => {
        for (const skin of ["child", "teen"] as const) for (const lang of ["es", "en"] as const) {
            expect(RANK_NAMES[skin][lang]).toHaveLength(10);
        }
    });
    it("uses the spec names", () => {
        expect(rankName(4, "child", "es")).toBe("Estrella");
        expect(rankName(4, "teen", "en")).toBe("Pro");
        expect(rankName(10, "child", "en")).toBe("Legend");
        expect(rankName(2, "teen", "es")).toBe("Colaborador");
    });
    it("clamps out-of-range ranks", () => {
        expect(rankName(0, "child", "en")).toBe("Rookie");
        expect(rankName(99, "teen", "es")).toBe("Leyenda");
    });
});

describe("progressView", () => {
    it("is null when progress does not apply or is missing", () => {
        expect(progressView(null, "child", "es")).toBeNull();
        expect(progressView({ applies: false }, "child", "es")).toBeNull();
    });
    it("labels, bar and next rank", () => {
        const v = progressView(resp(), "child", "es")!;
        expect(v.streakLabel).toBe("🔥 5 días");
        expect(v.rankLabel).toBe("Explorador · 3/10");
        expect(v.barPct).toBe(50);
        expect(v.toNextLabel).toBe("150 XP para Estrella");
    });
    it("singular day and English", () => {
        const v = progressView(resp({ streak_days: 1 }), "teen", "en")!;
        expect(v.streakLabel).toBe("🔥 1 day");
        expect(v.rankLabel).toBe("Reliable · 3/10");
    });
    it("top rank has a full bar and no next", () => {
        const v = progressView(resp({ rank: 10, xp: 9000, rank_floor_xp: 8000, next_rank_xp: null }), "child", "en")!;
        expect(v.barPct).toBe(100);
        expect(v.toNextLabel).toBe("Top rank!");
    });
    it("ladder states and week labels", () => {
        const v = progressView(resp(), "child", "en")!;
        expect(v.ladder.map((r) => r.state)).toEqual(["done", "done", "current", ...Array(7).fill("locked")]);
        expect(v.week.map((d) => d.label)).toEqual(["M", "T", "W", "T", "F", "S", "S"]);
        expect(v.week.map((d) => d.state)).toEqual(["done", "shield", "done", "today", "future", "future", "future"]);
    });
    it("celebration name follows the skin", () => {
        const v = progressView(resp({ celebrate_rank: 4 }), "teen", "es")!;
        expect(v.celebrateRank).toBe(4);
        expect(v.celebrateName).toBe("Pro");
    });
    it("never shows a negative XP-to-next", () => {
        const v = progressView(resp({ xp: 650, rank_floor_xp: 300, next_rank_xp: 600 }), "child", "es")!;
        expect(v.toNextLabel).toBe("0 XP para Estrella");
        expect(v.barPct).toBe(100);
    });
});

describe("progressDomUpdate (F4 — live refresh after ftm:deck-empty)", () => {
    it("maps a ProgressView to the exact DOM values KidHeader/ProgressSheet write", () => {
        const v = progressView(resp(), "child", "es")!;
        expect(progressDomUpdate(v)).toEqual({
            streak: "🔥 5 días",
            rank: "Explorador · 3/10",
            barWidthPct: 50,
            barAriaLabel: "150 XP para Estrella",
            sheetStreak: "🔥 5 días",
        });
    });
    it("reflects a same-day rank-up (bar hits 100%) without re-deriving anything", () => {
        const v = progressView(resp({ xp: 650, rank_floor_xp: 300, next_rank_xp: 600 }), "child", "es")!;
        const u = progressDomUpdate(v);
        expect(u.barWidthPct).toBe(100);
        expect(u.barAriaLabel).toBe("0 XP para Estrella");
    });
});

describe("KidHeader live progress refresh (F4)", () => {
    const src = read("components/home/KidHeader.astro");
    it("carries skin/lang on the progress row so the refresh script can call progressView", () => {
        expect(src).toMatch(/data-progress-row[^>]*data-skin=\{skin\}/);
        expect(src).toMatch(/data-progress-row[^>]*data-lang=\{lang\}/);
    });
    it("tags the streak pill, rank pill and XP bar with data hooks", () => {
        expect(src).toMatch(/data-progress-streak/);
        expect(src).toMatch(/data-progress-rank\b/);
        expect(src).toMatch(/data-progress-bar\b/);
    });
    it("the two pills advertise the sheet they open (aria-haspopup, F5)", () => {
        const pills = src.slice(src.indexOf("data-progress-row"), src.indexOf("meter.show &&"));
        const opens = pills.match(/data-progress-open[^>]*>/g) ?? [];
        expect(opens.length).toBeGreaterThanOrEqual(2);
        for (const tag of opens) expect(tag).toMatch(/aria-haspopup="dialog"/);
    });
    it("listens for ftm:deck-empty on window and fetches /api/progress/me", () => {
        expect(src).toMatch(/window\.addEventListener\(\s*["']ftm:deck-empty["']/);
        expect(src).toMatch(/fetch\(\s*["']\/api\/progress\/me["']/);
    });
    it("failures are silent — no unhandled throw path updates nothing", () => {
        const script = src.slice(src.indexOf("<script"));
        expect(script).toMatch(/catch/);
    });
    it("never re-fires the rank-up celebration from the live refresh", () => {
        const script = src.slice(src.indexOf("<script"));
        expect(script).not.toMatch(/ack-rank/);
        expect(script).not.toMatch(/RankUpCelebration/);
    });
});

describe("ProgressSheet backdrop tap closes the sheet (F5)", () => {
    const src = read("components/home/ProgressSheet.astro");
    it("wraps the visible content in an inner panel, dialog itself is backdrop-only", () => {
        const openTag = src.match(/<dialog id="progress-sheet"[^>]*>/s)?.[0] ?? "";
        expect(openTag).toMatch(/bg-transparent/);
        expect(openTag).not.toMatch(/bg-brand-cream/);
        expect(src).toMatch(/bg-brand-cream/); // moved to the panel, not dropped
    });
    it("closes when the click target is the <dialog> itself", () => {
        expect(src).toMatch(/addEventListener\(\s*["']click["'][\s\S]*?e\.target\s*===\s*\w+[\s\S]*?\.close\(\)/);
    });
});

describe("progressLine (parent hub)", () => {
    it("streak and rank name by the kid's role", () => {
        expect(progressLine({ role: "child", streak_days: 5, rank: 4 }, "es")).toBe("🔥 5 · Estrella");
        expect(progressLine({ role: "teen", streak_days: 0, rank: 4 }, "en")).toBe("🔥 0 · Pro");
    });
    it("null when the fields are missing", () => {
        expect(progressLine({ role: "child" }, "es")).toBeNull();
    });
});

describe("shouldCelebrate (welcome tour gate)", () => {
    const view = progressView(resp({ celebrate_rank: 2 }), "teen", "en");
    it("celebrates when the welcome tour is done or unknown", () => {
        expect(shouldCelebrate(view, true)).toBe(true);
        expect(shouldCelebrate(view, undefined)).toBe(true);
    });
    it("waits while the welcome tour can still run (driver.js would block the tap)", () => {
        expect(shouldCelebrate(view, false)).toBe(false);
    });
    it("never celebrates without a rank to celebrate", () => {
        expect(shouldCelebrate(progressView(resp(), "teen", "en"), true)).toBe(false);
        expect(shouldCelebrate(null, true)).toBe(false);
    });
});

describe("dashboard wiring (welcome tour gate)", () => {
    it("renders the rank-up celebration only through shouldCelebrate with the welcome-tour flag", () => {
        const src = readFileSync(fileURLToPath(new URL("../src/pages/dashboard.astro", import.meta.url)), "utf8");
        expect(src).toMatch(/shouldCelebrate\(\s*progress\s*,\s*user\.completed_welcome_tour\s*\)\s*&&\s*\(?\s*<RankUpCelebration/);
    });
});
