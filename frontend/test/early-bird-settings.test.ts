import { describe, expect, it } from "vitest";
import { buildPayload, validateRulesForm, centsToPesos, daysFromFamily, daysToPayload, pesosToCents, teenTodayLabel } from "../src/lib/earlyBirdSettings";

const base = { enabled: true, deadline: "11:00", days: [0, 1, 2, 3, 4, 5, 6], bonusPct: 20, streakPesos: 380, cutoff: "20:30", grabEnd: "22:30", alarm1: "15:00", alarm2: "19:00" };

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
        expect(r).toEqual({ ok: true, body: { early_bird_enabled: true, early_bird_deadline: "11:00", early_bird_days: null, early_bird_bonus_pct: 20, early_bird_streak_cents: 38000, chore_cutoff: "20:30", grab_window_end: "22:30", teen_alarm_1: "15:00", teen_alarm_2: "19:00" } });
    });
    it("rejects invalid fields", () => {
        expect(buildPayload({ ...base, deadline: "06:55" })).toMatchObject({ ok: false, field: "deadline" });
        expect(buildPayload({ ...base, deadline: "11:03" })).toMatchObject({ ok: false, field: "deadline" });
        expect(buildPayload({ ...base, deadline: "" })).toMatchObject({ ok: false, field: "deadline" });
        expect(buildPayload({ ...base, days: [] })).toMatchObject({ ok: false, field: "days" });
        expect(buildPayload({ ...base, bonusPct: 101 })).toMatchObject({ ok: false, field: "bonus" });
        expect(buildPayload({ ...base, streakPesos: 10001 })).toMatchObject({ ok: false, field: "streak" });
    });
});

describe("validateRulesForm", () => {
    const v = { deadline: "11:00", cutoff: "20:30", grabEnd: "22:30", alarm1: "15:00", alarm2: "19:00" };
    it("accepts the defaults", () => {
        expect(validateRulesForm(v, "es")).toBeNull();
    });
    it("rejects a cutoff at or before the deadline", () => {
        expect(validateRulesForm({ ...v, deadline: "18:00", cutoff: "18:00" }, "en")).toMatchObject({ field: "cutoff" });
        expect(validateRulesForm({ ...v, deadline: "19:00", cutoff: "17:30", alarm1: "15:00", alarm2: "17:00" }, "es")).toMatchObject({ field: "cutoff" });
    });
    it("rejects a cutoff outside 17:00-23:00 or off the 5-minute step", () => {
        expect(validateRulesForm({ ...v, cutoff: "16:55" }, "en")).toMatchObject({ field: "cutoff" });
        expect(validateRulesForm({ ...v, cutoff: "23:05", grabEnd: "23:30" }, "en")).toMatchObject({ field: "cutoff" });
        expect(validateRulesForm({ ...v, cutoff: "20:32" }, "en")).toMatchObject({ field: "cutoff" });
        expect(validateRulesForm({ ...v, cutoff: "" }, "en")).toMatchObject({ field: "cutoff" });
    });
    it("rejects a grab end at/before the cutoff or after 23:30", () => {
        expect(validateRulesForm({ ...v, grabEnd: "20:30" }, "en")).toMatchObject({ field: "grabEnd" });
        expect(validateRulesForm({ ...v, grabEnd: "23:35" }, "en")).toMatchObject({ field: "grabEnd" });
        expect(validateRulesForm({ ...v, grabEnd: "23:30" }, "en")).toBeNull();
    });
    it("rejects unordered or out-of-range alarms", () => {
        expect(validateRulesForm({ ...v, alarm1: "19:00", alarm2: "15:00" }, "en")).toMatchObject({ field: "alarms" });
        expect(validateRulesForm({ ...v, alarm1: "15:00", alarm2: "15:00" }, "en")).toMatchObject({ field: "alarms" });
        expect(validateRulesForm({ ...v, alarm1: "05:55" }, "en")).toMatchObject({ field: "alarms" });
        expect(validateRulesForm({ ...v, alarm2: "21:00" }, "en")).toMatchObject({ field: "alarms" });
        // At the cutoff is too late: alarms must be strictly before it.
        expect(validateRulesForm({ ...v, alarm2: "20:30" }, "en")).toMatchObject({ field: "alarms" });
        expect(validateRulesForm({ ...v, alarm2: "20:25" }, "en")).toBeNull();
        expect(validateRulesForm({ ...v, alarm2: "19:02" }, "en")).toMatchObject({ field: "alarms" });
    });
    it("the alarm message says before the cutoff, in both languages", () => {
        expect(validateRulesForm({ ...v, alarm2: "20:30" }, "es")?.message).toContain("antes de la hora de corte");
        expect(validateRulesForm({ ...v, alarm2: "20:30" }, "en")?.message).toContain("before the cutoff");
    });
    it("messages exist in both languages and differ", () => {
        const es = validateRulesForm({ ...v, cutoff: "10:00" }, "es")!.message;
        const en = validateRulesForm({ ...v, cutoff: "10:00" }, "en")!.message;
        expect(es).not.toBe(en);
        expect(es.length).toBeGreaterThan(0);
    });
});

describe("teenTodayLabel", () => {
    it("words a teen's day for the parent", () => {
        expect(teenTodayLabel("early", "es")).toBe("Hoy: a tiempo");
        expect(teenTodayLabel("missed", "en")).toBe("Today: missed");
    });
    it("is empty for no state or an unknown one", () => {
        expect(teenTodayLabel(null, "es")).toBe("");
        expect(teenTodayLabel("future", "en")).toBe("");
    });
});
