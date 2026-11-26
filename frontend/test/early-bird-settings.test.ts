import { describe, expect, it } from "vitest";
import { buildPayload, ladderExplainer, validateRulesForm, centsToPesos, daysFromFamily, daysToPayload, pesosToCents, teenTodayLabel } from "../src/lib/earlyBirdSettings";

const base = { enabled: true, deadline: "11:00", days: [0, 1, 2, 3, 4, 5, 6], bonusPct: 20, streakPesos: 380, alarm1: "15:00", alarm2: "19:00" };

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
        expect(r).toEqual({ ok: true, body: { early_bird_enabled: true, early_bird_deadline: "11:00", early_bird_days: null, early_bird_bonus_pct: 20, early_bird_streak_cents: 38000, teen_alarm_1: "15:00", teen_alarm_2: "19:00" } });
        // The evening cutoff and the grab window are no longer settings.
        expect(Object.keys((r as any).body)).not.toEqual(expect.arrayContaining(["chore_cutoff"]));
        expect((r as any).body).not.toHaveProperty("grab_window_end");
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
    const v = { deadline: "11:00", alarm1: "15:00", alarm2: "19:00" };
    it("accepts the defaults", () => {
        expect(validateRulesForm(v, "es")).toBeNull();
    });
    it("rejects a deadline outside 07:00-22:00 or off the 5-minute step", () => {
        expect(validateRulesForm({ ...v, deadline: "06:55" }, "en")).toMatchObject({ field: "deadline" });
        expect(validateRulesForm({ ...v, deadline: "22:05" }, "en")).toMatchObject({ field: "deadline" });
        expect(validateRulesForm({ ...v, deadline: "11:03" }, "en")).toMatchObject({ field: "deadline" });
        // 21:00 was refused while it had to be before the 20:30 cutoff.
        expect(validateRulesForm({ ...v, deadline: "21:00" }, "en")).toBeNull();
    });
    it("rejects unordered or out-of-range alarms", () => {
        expect(validateRulesForm({ ...v, alarm1: "19:00", alarm2: "15:00" }, "en")).toMatchObject({ field: "alarms" });
        expect(validateRulesForm({ ...v, alarm1: "15:00", alarm2: "15:00" }, "en")).toMatchObject({ field: "alarms" });
        expect(validateRulesForm({ ...v, alarm1: "05:55" }, "en")).toMatchObject({ field: "alarms" });
        expect(validateRulesForm({ ...v, alarm2: "23:05" }, "en")).toMatchObject({ field: "alarms" });
        expect(validateRulesForm({ ...v, alarm2: "19:02" }, "en")).toMatchObject({ field: "alarms" });
    });
    it("accepts evening alarms: the day ends at midnight, not at a cutoff", () => {
        expect(validateRulesForm({ ...v, alarm2: "20:30" }, "en")).toBeNull();
        expect(validateRulesForm({ ...v, alarm1: "21:00", alarm2: "23:00" }, "es")).toBeNull();
    });
    it("the alarm message gives the range, in both languages", () => {
        expect(validateRulesForm({ ...v, alarm2: "23:05" }, "es")?.message).toBe(
            "Las alarmas van de 06:00 a 23:00, en pasos de 5 minutos, la primera antes que la segunda.");
        expect(validateRulesForm({ ...v, alarm2: "23:05" }, "en")?.message).toBe(
            "Alarms run from 06:00 to 23:00 in 5-minute steps, the first before the second.");
    });
});

describe("ladderExplainer", () => {
    it("says open chores count as not done after midnight, and nothing about grabs", () => {
        const es = ladderExplainer("11:00", "es").join(" ");
        const en = ladderExplainer("11:00", "en").join(" ");
        expect(es).toContain("Las tareas que sigan abiertas a la medianoche no cuentan como hechas.");
        expect(en).toContain("Chores still open at midnight do not count as done.");
        expect(es + en).not.toMatch(/para tomar|hora de corte|up for grabs|cutoff/i);
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
