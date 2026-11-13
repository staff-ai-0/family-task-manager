import { describe, expect, it } from "vitest";
import { countdownLabel, earlyBirdCopy, earlyBirdView, grabItems, ladderMessage, payoutWeekNotes, runProgress, takeBlockHint, takeErrorMessage, takeErrorReason, paycheckBonusLine } from "../src/lib/earlyBird";

const d = (s: string) => new Date(s);

const me = (over: Record<string, unknown> = {}) => ({
    enabled: true,
    applies: true,
    deadline: "11:00",
    cutoff_at: "2026-11-09T20:30:00-06:00",
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
    streak_weeks: 3,
    streak_cents: 0,
    week_ladder: { completed_pct: 0, early_pct: 0, tier: "neutral", bonus_pct: 0, final: false },
    bonus_pct: 20,
    open_today: 1,
    grabs: [],
    take_block: null,
    ...over,
});

describe("countdownLabel", () => {
    it("minutes only under an hour", () => {
        expect(countdownLabel(d("2026-11-09T11:00:00-06:00"), d("2026-11-09T10:15:00-06:00"))).toBe("45 min");
    });
    it("hours and zero-padded minutes", () => {
        expect(countdownLabel(d("2026-11-09T11:00:00-06:00"), d("2026-11-09T09:55:00-06:00"))).toBe("1 h 05 min");
    });
    it("past target reads as zero", () => {
        expect(countdownLabel(d("2026-11-09T11:00:00-06:00"), d("2026-11-09T11:30:00-06:00"))).toBe("0 min");
    });
});

describe("earlyBirdView", () => {
    it("null when it does not apply and nothing to grab", () => {
        expect(earlyBirdView(me({ applies: false }), "es", d("2026-11-09T09:00:00-06:00"))).toBeNull();
        expect(earlyBirdView(null, "es", d("2026-11-09T09:00:00-06:00"))).toBeNull();
    });
    it("on_track before the 11:00 deadline, counting to the deadline", () => {
        const v = earlyBirdView(me(), "es", d("2026-11-09T09:00:00-06:00"))!;
        expect(v.state).toBe("on_track");
        expect(v.runText).toBe("1/3");
        expect(v.dots).toHaveLength(7);
        expect(v.countdown).toBe("2 h 00 min");
        expect(v.targetAt).toBe(d("2026-11-09T11:00:00-06:00").toISOString());
    });
    it("before_cutoff between the deadline and the evening cutoff, counting to the cutoff", () => {
        const v = earlyBirdView(me(), "en", d("2026-11-09T19:30:00-06:00"))!;
        expect(v.state).toBe("before_cutoff");
        expect(v.countdown).toBe("1 h 00 min");
        expect(v.headline).toContain("cutoff");
        expect(v.targetAt).toBe(d("2026-11-09T20:30:00-06:00").toISOString());
    });
    it("missed with open chores still counts down to the cutoff", () => {
        const v = earlyBirdView(me({ today: "missed", open_today: 1 }), "en", d("2026-11-09T19:30:00-06:00"))!;
        expect(v.state).toBe("before_cutoff");
        expect(v.countdown).toBe("1 h 00 min");
    });
    it("missed with nothing open is plain missed, no countdown", () => {
        const v = earlyBirdView(me({ today: "missed", open_today: 0 }), "en", d("2026-11-09T19:30:00-06:00"))!;
        expect(v.state).toBe("missed");
        expect(v.countdown).toBe("");
        expect(v.targetAt).toBe("");
    });
    it("late after the cutoff: chores are open to the family", () => {
        const v = earlyBirdView(me(), "en", d("2026-11-09T21:00:00-06:00"))!;
        expect(v.state).toBe("late");
        expect(v.countdown).toBe("");
        expect(v.headline.toLowerCase()).toContain("family");
    });
    it("carries the weekly ladder message", () => {
        const v = earlyBirdView(me({ week_ladder: { completed_pct: 52, early_pct: 0, tier: "no_pay", bonus_pct: 0, final: false } }), "es", d("2026-11-09T09:00:00-06:00"))!;
        expect(v.ladderText).toBe("Llevas 52 %: necesitas 60 % para cobrar");
        expect(v.paycheckBonusPct).toBe(0);
    });
    it("exposes the earned paycheck bonus pct from the ladder", () => {
        const v = earlyBirdView(me({ week_ladder: { completed_pct: 100, early_pct: 92, tier: "bonus", bonus_pct: 10, final: false } }), "es", d("2026-11-09T09:00:00-06:00"))!;
        expect(v.paycheckBonusPct).toBe(10);
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
    it("run target comes from the API, not a frontend copy", () => {
        const v = earlyBirdView(me({ run_weeks: 5, streak_weeks: 4 }), "es", d("2026-11-09T09:00:00-06:00"))!;
        expect(v.runText).toBe("1/4");
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
    const keys = ["grab_window_closed", "not_eligible", "own_chore", "already_taken"];
    it("every new reason key has distinct non-empty copy in ES and EN", () => {
        for (const lang of ["es", "en"] as const) {
            const msgs = keys.map((k) => takeErrorMessage(k, lang));
            expect(new Set(msgs).size).toBe(keys.length);
            const generic = takeErrorMessage("zzz", lang);
            msgs.forEach((m) => { expect(m.length).toBeGreaterThan(0); expect(m).not.toBe(generic); });
        }
    });
    it("dead reasons fall back to the generic message", () => {
        for (const k of ["not_kid", "finish_yours_first"]) expect(takeErrorMessage(k, "en")).toBe(takeErrorMessage("zzz", "en"));
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
        expect(takeBlockHint("not_eligible", "es")).toBeTruthy();
        expect(takeBlockHint("not_eligible", "en")).toBe(takeErrorMessage("not_eligible", "en"));
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

describe("runProgress", () => {
    it("is the run toward the next payout, sized by the API", () => {
        expect(runProgress({ run_weeks: 4, streak_weeks: 3 })).toEqual({ done: 1, target: 3 });
        expect(runProgress({ run_weeks: 0, streak_weeks: 3 })).toEqual({ done: 0, target: 3 });
    });
    it("has no target when the API sends none", () => {
        expect(runProgress({ run_weeks: 2 })).toEqual({ done: 0, target: 0 });
    });
});

describe("payoutWeekNotes", () => {
    it("explains a no_pay week", () => {
        expect(payoutWeekNotes({ ladder_tier: "no_pay", ladder_final: true, is_current_week: false }, "es")).toEqual(["Menos de 60 % completado — sin pago base"]);
        expect(payoutWeekNotes({ ladder_tier: "no_pay", ladder_final: true }, "en")).toEqual(["Under 60% completed — no base pay"]);
    });
    it("flags a past week that is not final as provisional", () => {
        expect(payoutWeekNotes({ ladder_tier: "per_task", ladder_final: false, is_current_week: false }, "es")).toEqual(["Pendiente de revisión — semana provisional"]);
    });
    it("says nothing for the current week, final weeks, bonus weeks or old payloads", () => {
        expect(payoutWeekNotes({ ladder_tier: "bonus", ladder_final: false, is_current_week: true }, "es")).toEqual([]);
        expect(payoutWeekNotes({ ladder_tier: "bonus", ladder_final: true, is_current_week: false }, "es")).toEqual([]);
        expect(payoutWeekNotes({}, "es")).toEqual([]);
    });
});

describe("grabItems", () => {
    it("maps API rows, preferring the Spanish title in es and honouring can_take", () => {
        const rows = [
            { assignment_id: "a", title: "Dishes", title_es: "Trastes", points: 10, owner_name: "Sam", can_take: true },
            { assignment_id: "b", title: "Trash", title_es: null, points: 5, owner_name: "Lu", can_take: false },
        ];
        const es = grabItems(rows, "es");
        expect(es.map((g) => g.title)).toEqual(["Trastes", "Trash"]);
        expect(es.map((g) => g.canTake)).toEqual([true, false]);
        expect(grabItems(rows, "en")[0].title).toBe("Dishes");
    });
    it("is empty for a non-list", () => {
        expect(grabItems(null, "es")).toEqual([]);
    });
});

const L = (completed_pct: number, early_pct: number, tier: string, bonus_pct: number, final = false) => ({ completed_pct, early_pct, tier, bonus_pct, final });

describe("ladderMessage deadline", () => {
    it("names the family's early deadline, never a fixed 11:00", () => {
        for (const lang of ["es", "en"] as const) {
            const m = ladderMessage(L(100, 85, "bonus", 5), lang, "10:00");
            expect(m).toContain("10:00");
            expect(m).not.toContain("11:00");
            expect(ladderMessage(L(100, 85, "bonus", 5), lang, "11:00")).toContain("11:00");
        }
    });
    it("without a deadline the hint stays generic", () => {
        expect(ladderMessage(L(100, 85, "bonus", 5), "en")).not.toMatch(/\d\d:\d\d/);
    });
});

describe("ladderMessage", () => {
    it("under 60 %: how far from being paid", () => {
        expect(ladderMessage(L(52, 0, "no_pay", 0), "es")).toBe("Llevas 52 %: necesitas 60 % para cobrar");
        expect(ladderMessage(L(52, 0, "no_pay", 0), "en")).toBe("You're at 52%: you need 60% to get paid");
    });
    it("60-99 %: each task pays, and 100 % unlocks the early bonus", () => {
        const es = ladderMessage(L(80, 40, "per_task", 0), "es");
        expect(es).toContain("80 %");
        expect(es).toContain("100 %");
        expect(ladderMessage(L(80, 40, "per_task", 0), "en")).toContain("every task you finish pays");
    });
    it("100 % with early share: earned tier and the next one", () => {
        expect(ladderMessage(L(100, 85, "bonus", 5), "es")).toContain("+5 %");
        expect(ladderMessage(L(100, 85, "bonus", 5), "es")).toContain("+10 %");
        expect(ladderMessage(L(100, 85, "bonus", 5), "en")).toContain("90%");
        expect(ladderMessage(L(100, 10, "bonus", 0), "es")).toContain("+5 %");
        expect(ladderMessage(L(100, 100, "bonus", 15), "es")).toContain("+15 %");
        expect(ladderMessage(L(100, 100, "bonus", 15), "es")).not.toContain("si todo");
    });
    it("final weeks read as closed results", () => {
        expect(ladderMessage(L(100, 100, "bonus", 15, true), "es")).toBe("Semana cerrada: 100 % — +15 % de madrugador");
        expect(ladderMessage(L(100, 100, "bonus", 15, true), "en")).toBe("Week closed: 100% — +15% early bird");
        expect(ladderMessage(L(100, 50, "bonus", 0, true), "en")).toBe("Week closed: 100% — no early bird bonus");
        expect(ladderMessage(L(55, 0, "no_pay", 0, true), "es")).toBe("Semana cerrada: 55 % — sin pago base");
        expect(ladderMessage(L(80, 0, "per_task", 0, true), "en")).toBe("Week closed: 80% — each task paid");
    });
    it("empty for a week with no chores or no data", () => {
        expect(ladderMessage(L(0, 0, "neutral", 0), "es")).toBe("");
        expect(ladderMessage(undefined, "es")).toBe("");
    });
});
