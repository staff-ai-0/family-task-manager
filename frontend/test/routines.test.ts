import { describe, expect, it } from "vitest";

import { pickDashboardRoutines, routineName, routineProgress } from "../src/lib/routines";

const r = (over: Record<string, unknown>) => ({
    id: "x", name: "Routine", name_es: "Rutina", icon: "⭐", time_of_day: "custom",
    sort_order: 0, steps_done: 0, total_steps: 3, completed: false, ...over,
});

describe("pickDashboardRoutines", () => {
    it("returns [] for anything that is not an array", () => {
        expect(pickDashboardRoutines(null)).toEqual([]);
        expect(pickDashboardRoutines({ routines: [] })).toEqual([]);
    });
    it("orders morning, evening, then the rest, and caps at two", () => {
        const picked = pickDashboardRoutines([
            r({ id: "c", time_of_day: "custom" }),
            r({ id: "e", time_of_day: "evening" }),
            r({ id: "m", time_of_day: "morning" }),
        ]);
        expect(picked.map((x) => x.id)).toEqual(["m", "e"]);
    });
    it("uses sort_order within the same time of day", () => {
        const picked = pickDashboardRoutines([
            r({ id: "m2", time_of_day: "morning", sort_order: 2 }),
            r({ id: "m1", time_of_day: "morning", sort_order: 1 }),
        ]);
        expect(picked.map((x) => x.id)).toEqual(["m1", "m2"]);
    });
    it("skips routines with no steps", () => {
        expect(pickDashboardRoutines([r({ total_steps: 0 })])).toEqual([]);
    });
});

describe("routineName / routineProgress", () => {
    it("localizes with a fallback to the base name", () => {
        expect(routineName(r({}), "es")).toBe("Rutina");
        expect(routineName(r({ name_es: null }), "es")).toBe("Routine");
        expect(routineName(r({}), "en")).toBe("Routine");
    });
    it("shows a fraction until done, then a check", () => {
        expect(routineProgress(r({ steps_done: 2, total_steps: 5 }))).toBe("2/5");
        expect(routineProgress(r({ steps_done: 5, total_steps: 5, completed: true }))).toBe("✓");
    });
});
