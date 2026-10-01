import { describe, expect, it } from "vitest";

import { QUEST_META, questChip, questDomUpdate, questView } from "../src/lib/quest";

const quest = (over: Record<string, unknown> = {}) => ({
    id: "q1", quest: "on_time", target: 5, progress: 3, bonus_points: 20,
    week_start: "2026-09-28", days_left: 4, completed: false, ...over,
});
const resp = (over: Record<string, unknown> = {}) => ({
    applies: true, gig_term: "gig", quest: quest(), celebrate: null, ...over,
});

describe("quest copy", () => {
    it("has the four spec quests", () => {
        expect(Object.keys(QUEST_META)).toEqual(["on_time", "extra_mile", "perfect_days", "go_getter"]);
        expect(Object.values(QUEST_META).map((m) => m.emoji)).toEqual(["⏰", "🚀", "✨", "💼"]);
    });
});

describe("questView", () => {
    it("returns null without a usable response", () => {
        expect(questView(null, "es")).toBeNull();
        expect(questView(undefined, "es")).toBeNull();
        expect(questView({ applies: false }, "es")).toBeNull();
        expect(questView({ applies: true, quest: null, celebrate: null }, "es")).toBeNull();
    });

    it("builds the in-progress card", () => {
        expect(questView(resp(), "es")!.card).toEqual({
            emoji: "⏰", title: "Termina 5 tareas a tiempo", progressLabel: "3/5", barPct: 60,
            daysLeftLabel: "Quedan 4 días", bonusLabel: "+20 puntos", done: false,
        });
        expect(questView(resp(), "en")!.card).toMatchObject({
            title: "Finish 5 chores on time", daysLeftLabel: "4 days left", bonusLabel: "+20 points",
        });
        expect(questView(resp(), "es")!.celebrate).toBeNull();
    });

    it("uses singular forms at one", () => {
        const one = (key: string) => questView(resp({ quest: quest({ quest: key, target: 1, progress: 0 }) }), "es")!.card!.title;
        expect(one("on_time")).toBe("Termina 1 tarea a tiempo");
        expect(one("perfect_days")).toBe("Logra 1 día perfecto");
        expect(one("extra_mile")).toBe("Haz 1 tarea extra");
        expect(one("go_getter")).toBe("Logra 1 gig aprobada");
        const en = (key: string) => questView(resp({ quest: quest({ quest: key, target: 1, progress: 0 }) }), "en")!.card!.title;
        expect(en("on_time")).toBe("Finish 1 chore on time");
        expect(en("perfect_days")).toBe("Have 1 perfect day");
        expect(en("extra_mile")).toBe("Do 1 bonus task");
        expect(en("go_getter")).toBe("Get 1 gig approved");
    });

    it("uses plural forms and the family's word for a gig", () => {
        const t = (key: string, term = "gig", lang: "es" | "en" = "es") =>
            questView(resp({ gig_term: term, quest: quest({ quest: key, target: 2, progress: 0 }) }), lang)!.card!.title;
        expect(t("perfect_days")).toBe("Logra 2 días perfectos");
        expect(t("extra_mile")).toBe("Haz 2 tareas extra");
        expect(t("go_getter")).toBe("Logra 2 gigs aprobadas");
        expect(t("go_getter", "chamba")).toBe("Logra 2 chambas aprobadas");
        expect(t("go_getter", "gig", "en")).toBe("Get 2 gigs approved");
        expect(t("perfect_days", "gig", "en")).toBe("Have 2 perfect days");
        expect(t("extra_mile", "gig", "en")).toBe("Do 2 bonus tasks");
    });

    it("labels the last day and a one-point bonus", () => {
        const v = questView(resp({ quest: quest({ days_left: 1, bonus_points: 1 }) }), "es")!.card!;
        expect(v.daysLeftLabel).toBe("Último día");
        expect(v.bonusLabel).toBe("+1 punto");
        const en = questView(resp({ quest: quest({ days_left: 1, bonus_points: 1 }) }), "en")!.card!;
        expect(en.daysLeftLabel).toBe("Last day");
        expect(en.bonusLabel).toBe("+1 point");
    });

    it("shows stars instead of points for a star-mode kid", () => {
        expect(questView(resp(), "es", true)!.card!.bonusLabel).toBe("+20 ⭐");
    });

    it("never draws the bar past 100% and marks a paid quest done", () => {
        expect(questView(resp({ quest: quest({ progress: 9 }) }), "es")!.card!.barPct).toBe(100);
        const done = questView(resp({ quest: quest({ progress: 5, completed: true }) }), "es")!.card!;
        expect(done.done).toBe(true);
        expect(done.barPct).toBe(100);
    });

    it("drops a quest key it has no copy for", () => {
        expect(questView(resp({ quest: quest({ quest: "dragon" }) }), "es")).toBeNull();
        const v = questView(resp({
            quest: quest({ quest: "dragon" }),
            celebrate: { id: "q0", quest: "on_time", target: 3, bonus_points: 20, last_week: true },
        }), "es")!;
        expect(v.card).toBeNull();
        expect(v.celebrate).not.toBeNull();
    });

    it("builds the celebrate view, last week's or this week's", () => {
        const last = questView(resp({ celebrate: { id: "q0", quest: "on_time", target: 3, bonus_points: 20, last_week: true } }), "es")!;
        expect(last.celebrate).toEqual({
            id: "q0", emoji: "⏰", heading: "La misión de la semana pasada: ¡lograda!", bonusLabel: "+20 puntos",
        });
        const now = questView(resp({ celebrate: { id: "q1", quest: "on_time", target: 5, bonus_points: 20, last_week: false } }), "en")!;
        expect(now.celebrate).toMatchObject({ id: "q1", heading: "Quest done!", bonusLabel: "+20 points" });
        expect(questView(resp({ celebrate: { id: "q0", quest: "on_time", target: 3, bonus_points: 20, last_week: true } }), "en")!
            .celebrate!.heading).toBe("Last week's quest: done!");
    });

    it("still has a view when only last week's result is left to show", () => {
        const v = questView({ applies: true, gig_term: "gig", quest: null,
            celebrate: { id: "q0", quest: "extra_mile", target: 2, bonus_points: 20, last_week: true } }, "es")!;
        expect(v.card).toBeNull();
        expect(v.celebrate!.emoji).toBe("🚀");
    });
});

describe("questDomUpdate (what the card renders and what a live refresh writes)", () => {
    it("shows the progress block for a quest in progress", () => {
        expect(questDomUpdate(questView(resp(), "es")!, "es")).toEqual({
            showDone: false, emoji: "⏰", title: "Termina 5 tareas a tiempo", progressLabel: "3/5", barWidthPct: 60,
            daysLeftLabel: "Quedan 4 días", bonusLabel: "+20 puntos", doneHeading: "¡Misión lograda!", doneBonusLabel: "+20 puntos",
        });
    });
    it("shows the done block for a paid quest", () => {
        const u = questDomUpdate(questView(resp({ quest: quest({ progress: 5, completed: true }) }), "en")!, "en");
        expect(u.showDone).toBe(true);
        expect(u.doneHeading).toBe("Quest done!");
        expect(u.doneBonusLabel).toBe("+20 points");
    });
    it("shows last week's result first, over this week's quest in progress", () => {
        const u = questDomUpdate(questView(resp({
            celebrate: { id: "q0", quest: "extra_mile", target: 2, bonus_points: 30, last_week: true },
        }), "es")!, "es");
        expect(u.showDone).toBe(true);
        expect(u.doneHeading).toBe("La misión de la semana pasada: ¡lograda!");
        expect(u.doneBonusLabel).toBe("+30 puntos");
        expect(u.title).toBe("Termina 5 tareas a tiempo");       // this week's quest is ready underneath
    });
    it("copes with a celebrate-only view", () => {
        const u = questDomUpdate(questView({ applies: true, gig_term: "gig", quest: null,
            celebrate: { id: "q0", quest: "on_time", target: 2, bonus_points: 20, last_week: true } }, "en")!, "en");
        expect(u).toMatchObject({ showDone: true, title: "", progressLabel: "", barWidthPct: 0, doneHeading: "Last week's quest: done!" });
    });
});

describe("questChip (parent hub)", () => {
    it("shows progress, or a check when done", () => {
        expect(questChip({ quest_progress: 3, quest_target: 5, quest_done: false })).toBe("🏁 3/5");
        expect(questChip({ quest_progress: 5, quest_target: 5, quest_done: true })).toBe("🏁 ✓");
        expect(questChip({ quest_progress: 0, quest_target: 2, quest_done: false })).toBe("🏁 0/2");
    });
    it("is null when the kid has no quest", () => {
        expect(questChip({ quest_progress: null, quest_target: null, quest_done: false })).toBeNull();
        expect(questChip({})).toBeNull();
        expect(questChip(null)).toBeNull();
    });
});
