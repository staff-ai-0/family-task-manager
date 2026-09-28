import { describe, expect, it } from "vitest";

import { buildDeck } from "../src/lib/deck";

const a = (over: Record<string, unknown>) => ({
    id: "a",
    template_id: "t",
    template_title: "Chore",
    template_title_es: "Tarea",
    template_points: 10,
    template_is_bonus: false,
    template_requires_proof: false,
    status: "pending",
    approval_status: "none",
    assigned_date: "2026-09-28",
    due_date: null,
    ...over,
});

const progress = (over: Record<string, unknown>) => ({
    required_total: 0,
    required_completed: 0,
    bonus_unlocked: false,
    assignments: [],
    overdue_assignments: [],
    ...over,
});

describe("buildDeck", () => {
    it("returns an empty deck for a missing payload", () => {
        expect(buildDeck(null, "es")).toEqual({ cards: [], doneToday: 0, totalToday: 0, inReview: 0 });
    });

    it("puts overdue first, grouped per chore, completing the oldest instance", () => {
        const deck = buildDeck(progress({
            overdue_assignments: [
                a({ id: "o2", template_id: "dishes", assigned_date: "2026-09-26" }),
                a({ id: "o3", template_id: "bed", assigned_date: "2026-09-27" }),
                a({ id: "o1", template_id: "dishes", assigned_date: "2026-09-25" }),
            ],
            assignments: [a({ id: "r1", template_id: "trash" })],
        }), "es");
        expect(deck.cards.map((c) => c.id)).toEqual(["o1", "o3", "r1"]);
        expect(deck.cards[0]).toMatchObject({ overdue: true, overdueCount: 2 });
        expect(deck.cards[1]).toMatchObject({ overdue: true, overdueCount: 1 });
        expect(deck.cards[2].overdue).toBe(false);
    });

    it("works when only overdue chores exist", () => {
        const deck = buildDeck(progress({ overdue_assignments: [a({ id: "o1" })] }), "es");
        expect(deck.cards.map((c) => c.id)).toEqual(["o1"]);
    });

    it("keeps only pending required chores and localizes titles", () => {
        const deck = buildDeck(progress({
            assignments: [
                a({ id: "r1" }),
                a({ id: "r2", status: "completed" }),
                a({ id: "r3", template_title_es: null, template_title: "Walk dog" }),
            ],
        }), "es");
        expect(deck.cards.map((c) => [c.id, c.title])).toEqual([["r1", "Tarea"], ["r3", "Walk dog"]]);
        expect(buildDeck(progress({ assignments: [a({ id: "r1" })] }), "en").cards[0].title).toBe("Chore");
    });

    it("shows unlocked bonus tasks after required ones", () => {
        const deck = buildDeck(progress({
            bonus_unlocked: true,
            assignments: [a({ id: "b1", template_is_bonus: true }), a({ id: "r1" })],
        }), "es");
        expect(deck.cards.map((c) => c.id)).toEqual(["r1", "b1"]);
        expect(deck.cards[1]).toMatchObject({ isBonus: true, locked: false });
    });

    it("collapses gated bonus tasks into one locked card", () => {
        const deck = buildDeck(progress({
            bonus_unlocked: false,
            assignments: [
                a({ id: "r1" }),
                a({ id: "b1", template_is_bonus: true }),
                a({ id: "b2", template_is_bonus: true }),
            ],
        }), "es");
        expect(deck.cards).toHaveLength(2);
        expect(deck.cards[1]).toMatchObject({ id: "locked", locked: true, lockedCount: 2 });
    });

    it("carries proof and points onto cards", () => {
        const deck = buildDeck(progress({
            assignments: [a({ id: "r1", template_requires_proof: true, template_points: 25 })],
        }), "es");
        expect(deck.cards[0]).toMatchObject({ requiresProof: true, points: 25 });
    });

    it("counts today's progress and items awaiting approval", () => {
        const deck = buildDeck(progress({
            required_total: 5,
            required_completed: 2,
            assignments: [
                a({ id: "x", status: "completed", approval_status: "pending" }),
                a({ id: "y", status: "completed", approval_status: "approved" }),
            ],
        }), "es");
        expect(deck).toMatchObject({ doneToday: 2, totalToday: 5, inReview: 1 });
    });
});
