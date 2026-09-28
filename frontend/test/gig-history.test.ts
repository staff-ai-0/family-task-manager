/**
 * Gig history grouping (parent /parent/gigs "Historial").
 *
 * Reposting a closed gig creates a NEW offering (the claim model allows one
 * approved claim per kid per offering, so the old one can't be reopened), and
 * the old repost path appended " (copia)" to the title. History listed every
 * cycle as its own card with its own Repost button — the "clogged history"
 * report (2026-09-28). Grouping is by job: title with copy suffixes and extra
 * whitespace ignored.
 */
import { describe, expect, it } from "vitest";

import { displayGigTitle, gigTitleKey, groupGigHistory } from "../src/lib/gigHistory";

const claim = (over: Record<string, unknown>) => ({
    id: "c",
    gig_id: "g1",
    gig_title: "Bañar a coco",
    gig_points: 30,
    points_awarded: null,
    status: "approved",
    claimer_name: "Diego",
    completed_at: "2026-09-20T18:00:00Z",
    approved_at: "2026-09-20T19:00:00Z",
    ...over,
});
const offering = (over: Record<string, unknown>) => ({
    id: "g1",
    title: "Bañar a coco",
    is_active: false,
    created_at: "2026-07-21T00:00:00Z",
    ...over,
});

describe("gigTitleKey / displayGigTitle", () => {
    it.each([
        ["Bañar a coco", "bañar a coco"],
        ["Bañar a coco (copia)", "bañar a coco"],
        ["Bañar a molly  (copia)", "bañar a molly"],
        ["Bañar a molly (copia) (copia)", "bañar a molly"],
        ["  Wash car (copy) ", "wash car"],
        ["BAÑAR A COCO", "bañar a coco"],
    ])("key(%j) = %j", (title, key) => {
        expect(gigTitleKey(title)).toBe(key);
    });

    it("keeps a parenthetical that is not a copy suffix", () => {
        expect(gigTitleKey("Lavar carro (por dentro)")).toBe("lavar carro (por dentro)");
    });

    it("display title strips copy suffixes but keeps casing", () => {
        expect(displayGigTitle("Bañar a molly  (copia)")).toBe("Bañar a molly");
        expect(displayGigTitle(null)).toBe("");
    });
});

describe("groupGigHistory", () => {
    it("groups every cycle of the same job into one entry, newest first", () => {
        const claims = [
            claim({ id: "c3", gig_id: "g3", gig_title: "Bañar a coco", completed_at: "2026-09-27T18:00:00Z" }),
            claim({ id: "x1", gig_id: "gx", gig_title: "Lavar carro", gig_points: 80 }),
            claim({ id: "c2", gig_id: "g2", gig_title: "Bañar a coco (copia)", completed_at: "2026-08-09T18:00:00Z" }),
            claim({ id: "c1", gig_id: "g1", gig_title: "Bañar a coco", completed_at: "2026-07-21T18:00:00Z" }),
        ];
        const groups = groupGigHistory(claims, []);
        expect(groups.map((g) => g.title)).toEqual(["Bañar a coco", "Lavar carro"]);
        expect(groups[0].claims.map((c) => c.id)).toEqual(["c3", "c2", "c1"]);
        expect(groups[0].latest.id).toBe("c3");
        expect(groups[0].count).toBe(3);
    });

    it("totals only approved pay, preferring points_awarded over gig_points", () => {
        const groups = groupGigHistory([
            claim({ id: "a", points_awarded: 15 }),
            claim({ id: "b", points_awarded: null, gig_points: 30 }),
            claim({ id: "c", status: "rejected", gig_points: 30 }),
            claim({ id: "d", status: "completed", gig_points: 30 }),
        ], []);
        expect(groups[0].totalPaid).toBe(45);
    });

    it("lists each kid once in claimers", () => {
        const groups = groupGigHistory([
            claim({ id: "a", claimer_name: "Diego" }),
            claim({ id: "b", claimer_name: "Sofia" }),
            claim({ id: "c", claimer_name: "Diego" }),
        ], []);
        expect(groups[0].claimers).toEqual(["Diego", "Sofia"]);
    });

    it("offers a repost of the latest cycle's offering when the job is not posted", () => {
        const groups = groupGigHistory(
            [claim({ id: "c2", gig_id: "g2" }), claim({ id: "c1", gig_id: "g1" })],
            [offering({ id: "g1" }), offering({ id: "g2", title: "Bañar a coco (copia)" })],
        );
        expect(groups[0].repostOffering?.id).toBe("g2");
    });

    it("hides the repost when the same job is already posted and active", () => {
        const groups = groupGigHistory(
            [claim({ id: "c1", gig_id: "g1" })],
            [offering({ id: "g1" }), offering({ id: "g9", title: "Bañar a coco (copia)", is_active: true })],
        );
        expect(groups[0].repostOffering).toBeNull();
    });

    it("falls back to the newest inactive offering when the claim's own offering is missing", () => {
        const groups = groupGigHistory(
            [claim({ id: "c1", gig_id: "gone" })],
            [
                offering({ id: "old", created_at: "2026-07-01T00:00:00Z" }),
                offering({ id: "new", created_at: "2026-09-01T00:00:00Z" }),
            ],
        );
        expect(groups[0].repostOffering?.id).toBe("new");
    });

    it("unwraps {offering} list items the API may return", () => {
        const groups = groupGigHistory(
            [claim({ id: "c1", gig_id: "g1" })],
            [{ offering: offering({ id: "g1" }) }],
        );
        expect(groups[0].repostOffering?.id).toBe("g1");
    });
});
