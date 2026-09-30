import { describe, expect, it } from "vitest";

import { progressLine, progressView, rankName, RANK_NAMES } from "../src/lib/progress";

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

describe("progressLine (parent hub)", () => {
    it("streak and rank name by the kid's role", () => {
        expect(progressLine({ role: "child", streak_days: 5, rank: 4 }, "es")).toBe("🔥 5 · Estrella");
        expect(progressLine({ role: "teen", streak_days: 0, rank: 4 }, "en")).toBe("🔥 0 · Pro");
    });
    it("null when the fields are missing", () => {
        expect(progressLine({ role: "child" }, "es")).toBeNull();
    });
});
