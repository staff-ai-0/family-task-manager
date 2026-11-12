import { describe, expect, it } from "vitest";
import { countdownLabel, earlyBirdCopy, earlyBirdView, takeBlockHint, takeErrorMessage, takeErrorReason, paycheckBonusLine } from "../src/lib/earlyBird";

const d = (s: string) => new Date(s);

const me = (over: Record<string, unknown> = {}) => ({
    enabled: true,
    applies: true,
    deadline: "11:00",
    cutoff_at: "2026-11-09T10:00:00-06:00",
    deadline_at: "2026-11-09T11:00:00-06:00",
    today: "open",
    week: [
        { date: "2026-11-09", state: "open" },
        { date: "2026-11-10", state: "future" },
        { date: "2026-11-11", state: "future" },
        { date: "2026-11-12", state: "future" },
        { date: "2026-11-13", state: "future" },
        { date: "2026-11-14", state: "future" },
        { date: "2026-11-15", state: "future" },
    ],
    week_result: "in_progress",
    run_weeks: 1,
    streak_weeks: 1,
    streak_cents: 0,
    week_pct: 5,
    bonus_pct: 20,
    open_today: 1,
    grabs: [],
    take_block: null,
    ...over,
});

describe("countdownLabel", () => {
    it("minutes only under an hour", () => {
        expect(countdownLabel(d("2026-11-09T11:00:00-06:00"), d("2026-11-09T10:15:00-06:00"), "es")).toBe("45 min");
    });
    it("hours and zero-padded minutes", () => {
        expect(countdownLabel(d("2026-11-09T11:00:00-06:00"), d("2026-11-09T09:55:00-06:00"), "en")).toBe("1 h 05 min");
    });
    it("past target reads as zero", () => {
        expect(countdownLabel(d("2026-11-09T11:00:00-06:00"), d("2026-11-09T11:30:00-06:00"), "es")).toBe("0 min");
    });
});

describe("earlyBirdView", () => {
    it("null when it does not apply and nothing to grab", () => {
        expect(earlyBirdView(me({ applies: false }), "es", d("2026-11-09T09:00:00-06:00"))).toBeNull();
        expect(earlyBirdView(null, "es", d("2026-11-09T09:00:00-06:00"))).toBeNull();
    });
    it("on_track before the cutoff", () => {
        const v = earlyBirdView(me(), "es", d("2026-11-09T09:00:00-06:00"))!;
        expect(v.state).toBe("on_track");
        expect(v.runText).toBe("1/3");
        expect(v.dots).toHaveLength(7);
        expect(v.countdown).toBe("1 h 00 min");
    });
    it("before_deadline between cutoff and deadline, counting to the deadline", () => {
        const v = earlyBirdView(me(), "en", d("2026-11-09T10:20:00-06:00"))!;
        expect(v.state).toBe("before_deadline");
        expect(v.countdown).toBe("40 min");
        expect(v.headline).toContain("11:00");
        expect(v.targetAt).toBe(d("2026-11-09T11:00:00-06:00").toISOString());
    });
    it("missed with open chores still counts down to the deadline", () => {
        const v = earlyBirdView(me({ today: "missed", open_today: 1 }), "en", d("2026-11-09T10:20:00-06:00"))!;
        expect(v.state).toBe("before_deadline");
        expect(v.countdown).toBe("40 min");
    });
    it("missed with nothing open is plain missed, no countdown", () => {
        const v = earlyBirdView(me({ today: "missed", open_today: 0 }), "en", d("2026-11-09T10:20:00-06:00"))!;
        expect(v.state).toBe("missed");
        expect(v.countdown).toBe("");
        expect(v.targetAt).toBe("");
    });
    it("late after the deadline", () => {
        const v = earlyBirdView(me(), "en", d("2026-11-09T11:05:00-06:00"))!;
        expect(v.state).toBe("late");
        expect(v.countdown).toBe("");
    });
    it("early when today is early", () => {
        const v = earlyBirdView(me({ today: "early" }), "en", d("2026-11-09T09:00:00-06:00"))!;
        expect(v.state).toBe("early");
    });
    it("grabs only (child) yields a view without a card", () => {
        const v = earlyBirdView(
            me({ applies: false, grabs: [{ assignment_id: "a", title: "Dishes", points: 10, owner_name: "Sam" }] }),
            "es",
            d("2026-11-09T09:00:00-06:00"),
        )!;
        expect(v.applies).toBe(false);
        expect(v.grabs).toHaveLength(1);
    });
    it("run text is progress toward the next payout (run % 3)", () => {
        const t = (r: number) => earlyBirdView(me({ run_weeks: r }), "es", d("2026-11-09T09:00:00-06:00"))!.runText;
        expect(t(2)).toBe("2/3");
        expect(t(3)).toBe("0/3");
        expect(t(4)).toBe("1/3");
        expect(t(5)).toBe("2/3");
    });
});

describe("takeErrorMessage", () => {
    it("known reasons are distinct and non-empty", () => {
        const keys = ["already_taken", "finish_yours_first", "role_not_allowed", "own_chore", "not_grabbable"];
        const msgs = keys.map((k) => takeErrorMessage(k, "es"));
        msgs.forEach((m) => expect(m.length).toBeGreaterThan(0));
        expect(new Set(msgs).size).toBe(keys.length);
    });
    it("unknown reason falls back to a generic message", () => {
        expect(takeErrorMessage("zzz", "en").length).toBeGreaterThan(0);
    });
});

describe("paycheckBonusLine", () => {
    it("null with no bonus", () => {
        expect(paycheckBonusLine(0, 5, "es")).toBeNull();
    });
    it("copy in both languages", () => {
        expect(paycheckBonusLine(500, 5, "es")).toBe("incl. +5% madrugador");
        expect(paycheckBonusLine(500, 5, "en")).toBe("incl. +5% early bird");
    });
});

describe("copy", () => {
    it("has both languages", () => {
        expect(earlyBirdCopy("es").title).not.toBe(earlyBirdCopy("en").title);
    });
});

describe("takeBlockHint", () => {
    it("explains a caller-level block so the Take buttons can be disabled up front", () => {
        expect(takeBlockHint("finish_yours_first", "es")).toBe("Termina primero tus tareas");
        expect(takeBlockHint("finish_yours_first", "en")).toBe("Finish your own chores first");
        expect(takeBlockHint("not_kid", "en")).toBeTruthy();
    });
    it("is null when nothing blocks the caller", () => {
        expect(takeBlockHint(null, "es")).toBeNull();
        expect(takeBlockHint("", "en")).toBeNull();
    });
});

describe("takeErrorReason", () => {
    it("reads the reason key from the API error body", () => {
        expect(takeErrorReason({ error: "conflict", message: "already_taken", status_code: 409 })).toBe("already_taken");
        expect(takeErrorReason({ detail: "kids_only" })).toBe("kids_only");
    });
    it("is empty for anything else", () => {
        expect(takeErrorReason(null)).toBe("");
        expect(takeErrorReason({ detail: [{ msg: "x" }] })).toBe("");
    });
});
