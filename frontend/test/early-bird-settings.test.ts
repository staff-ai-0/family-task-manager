import { describe, expect, it } from "vitest";
import { buildPayload, centsToPesos, daysFromFamily, daysToPayload, pesosToCents } from "../src/lib/earlyBirdSettings";

const base = { enabled: true, deadline: "11:00", days: [0, 1, 2, 3, 4, 5, 6], bonusPct: 20, weekPct: 5, streakPesos: 500 };

describe("early bird settings", () => {
    it("all seven days sends null, a subset sends the sorted list", () => {
        expect(daysToPayload([6, 5, 4, 3, 2, 1, 0])).toBeNull();
        expect(daysToPayload([4, 0, 2])).toEqual([0, 2, 4]);
        expect(daysFromFamily(null)).toEqual([0, 1, 2, 3, 4, 5, 6]);
        expect(daysFromFamily([1, 3])).toEqual([1, 3]);
    });
    it("converts pesos and cents", () => {
        expect(pesosToCents(500)).toBe(50000);
        expect(centsToPesos(50000)).toBe(500);
        expect(centsToPesos(undefined)).toBe(0);
    });
    it("builds the payload", () => {
        const r = buildPayload(base);
        expect(r).toEqual({ ok: true, body: { early_bird_enabled: true, early_bird_deadline: "11:00", early_bird_days: null, early_bird_bonus_pct: 20, early_bird_week_pct: 5, early_bird_streak_cents: 50000 } });
    });
    it("rejects invalid fields", () => {
        expect(buildPayload({ ...base, deadline: "06:55" })).toEqual({ ok: false, field: "deadline" });
        expect(buildPayload({ ...base, deadline: "11:03" })).toEqual({ ok: false, field: "deadline" });
        expect(buildPayload({ ...base, deadline: "" })).toEqual({ ok: false, field: "deadline" });
        expect(buildPayload({ ...base, days: [] })).toEqual({ ok: false, field: "days" });
        expect(buildPayload({ ...base, bonusPct: 101 })).toEqual({ ok: false, field: "bonus" });
        expect(buildPayload({ ...base, weekPct: 51 })).toEqual({ ok: false, field: "week" });
        expect(buildPayload({ ...base, streakPesos: 10001 })).toEqual({ ok: false, field: "streak" });
    });
});
