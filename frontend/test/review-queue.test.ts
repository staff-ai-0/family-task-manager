import { describe, expect, it } from "vitest";

import { advanceQueue, buildReviewQueue } from "../src/lib/reviewQueue";

const task = (over: Record<string, unknown> = {}) => ({
    assignment_id: "t1", template_title: "Lavar platos", assigned_to_name: "Diego", points: 10,
    completed_at: "2026-09-27T20:14:00Z", proof_text: "listo", proof_image_url: "/uploads/p.jpg",
    template_gig_mode: "claim", ...over,
});
const claim = (over: Record<string, unknown> = {}) => ({
    id: "c1", gig_title: "Lavar el carro", claimer_name: "Sofia", gig_points: 120,
    completed_at: "2026-09-28T17:02:00Z", proof_text: null, proof_image_url: null, ...over,
});
const redemption = (over: Record<string, unknown> = {}) => ({
    id: "r1", reward_title: "1 h de videojuegos", user_name: "Diego", points_cost: 200,
    created_at: "2026-09-28T18:00:00Z", ...over,
});

describe("buildReviewQueue", () => {
    it("merges the three sources oldest first", () => {
        const q = buildReviewQueue([task()], [claim()], [redemption()], "es");
        expect(q.map((i) => `${i.kind}:${i.id}`)).toEqual(["task:t1", "gig:c1", "redemption:r1"]);
    });
    it("sorts across sources by time, not by source", () => {
        const q = buildReviewQueue(
            [task({ completed_at: "2026-09-28T19:00:00Z" })],
            [claim({ completed_at: "2026-09-28T09:00:00Z" })],
            [],
            "es",
        );
        expect(q.map((i) => i.id)).toEqual(["c1", "t1"]);
    });
    it("puts items without a timestamp last, keeping their order", () => {
        const q = buildReviewQueue(
            [task({ assignment_id: "a", completed_at: null }), task({ assignment_id: "b", completed_at: null })],
            [claim()],
            [],
            "es",
        );
        expect(q.map((i) => i.id)).toEqual(["c1", "a", "b"]);
    });
    it("allows partial credit only on non-collaboration tasks", () => {
        const q = buildReviewQueue(
            [task({ assignment_id: "solo" }), task({ assignment_id: "team", template_gig_mode: "collaboration" })],
            [claim()],
            [redemption()],
            "es",
        );
        const byId = Object.fromEntries(q.map((i) => [i.id, i.allowPartial]));
        expect(byId).toEqual({ solo: true, team: false, c1: false, r1: false });
    });
    it("labels chips and titles per kind", () => {
        const es = buildReviewQueue([task()], [claim()], [redemption()], "es");
        expect(es.map((i) => i.chip)).toEqual(["+10 pts", "gig $120", "200 pts"]);
        expect(es[2].title).toBe("Canjear: 1 h de videojuegos");
        const en = buildReviewQueue([], [], [redemption()], "en");
        expect(en[0].title).toBe("Redeem: 1 h de videojuegos");
    });
    it("maps names, proof and ids", () => {
        const [t] = buildReviewQueue([task()], [], [], "es");
        expect(t).toMatchObject({ kind: "task", id: "t1", kidName: "Diego", proofText: "listo", proofImageUrl: "/uploads/p.jpg" });
    });
    it("tolerates non-array inputs", () => {
        expect(buildReviewQueue(null, undefined, { detail: "x" }, "es")).toEqual([]);
    });
});

describe("advanceQueue", () => {
    it("reveals the next hidden card and decrements the total", () => {
        const next = advanceQueue({ visible: ["a", "b", "c"], hidden: ["d", "e"], total: 5 }, "b");
        expect(next).toEqual({
            visible: ["a", "c", "d"], hidden: ["e"], total: 4,
            reveal: "d", empty: false, remainingElsewhere: 0,
        });
    });
    it("reports what is left elsewhere once the rendered cards run out", () => {
        const next = advanceQueue({ visible: ["a"], hidden: [], total: 10 }, "a");
        expect(next).toMatchObject({ visible: [], total: 9, reveal: null, empty: false, remainingElsewhere: 9 });
    });
    it("is empty when the last item is decided", () => {
        const next = advanceQueue({ visible: ["a"], hidden: [], total: 1 }, "a");
        expect(next).toMatchObject({ total: 0, empty: true, remainingElsewhere: 0 });
    });
    it("ignores an id it does not know", () => {
        const state = { visible: ["a"], hidden: ["b"], total: 2 };
        expect(advanceQueue(state, "zzz")).toEqual({ ...state, reveal: null, empty: false, remainingElsewhere: 0 });
    });
});
