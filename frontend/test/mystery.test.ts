import { describe, expect, it } from "vitest";

import { MYSTERY_COPY, mysteryDomUpdate, mysteryView, revealedFrom } from "../src/lib/mystery";

const closed = (id: string, day = "2026-10-03") => ({ id, day, opened: false, kind: null, surprise_title: null, surprise_emoji: null, points: 0 });
const surprise = { id: "b2", day: "2026-10-03", opened: true, kind: "surprise", surprise_title: "Pick dessert tonight", surprise_emoji: "🍨", points: 0 };
const points = { id: "b3", day: "2026-10-03", opened: true, kind: "points", surprise_title: null, surprise_emoji: null, points: 12 };

describe("mysteryView", () => {
    it("is null unless the family's boxes are on for a kid", () => {
        for (const v of [null, undefined, {}, { applies: false }, { applies: true, enabled: false }, "x"]) {
            expect(mysteryView(v)).toBeNull();
        }
    });
    it("counts the closed boxes and keeps the oldest one's id", () => {
        const v = mysteryView({ applies: true, enabled: true, unopened: [closed("b1", "2026-10-02"), closed("b9")], opened_today: null });
        expect(v).toEqual({ closedCount: 2, closedId: "b1", revealed: null });
    });
    it("keeps today's reveal even while more boxes wait", () => {
        const v = mysteryView({ applies: true, enabled: true, unopened: [closed("b9")], opened_today: surprise });
        expect(v).toEqual({ closedCount: 1, closedId: "b9", revealed: { kind: "surprise", title: "Pick dessert tonight", emoji: "🍨", points: 0 } });
    });
    it("carries today's reveal when nothing is closed", () => {
        expect(mysteryView({ applies: true, enabled: true, unopened: [], opened_today: surprise })).toEqual({
            closedCount: 0, closedId: null, revealed: { kind: "surprise", title: "Pick dessert tonight", emoji: "🍨", points: 0 },
        });
        expect(mysteryView({ applies: true, enabled: true, unopened: [], opened_today: points })?.revealed).toEqual({ kind: "points", title: "", emoji: "", points: 12 });
    });
    it("an empty but enabled family still gets a view (so the card can wake up later)", () => {
        expect(mysteryView({ applies: true, enabled: true, unopened: [], opened_today: null })).toEqual({ closedCount: 0, closedId: null, revealed: null });
    });
});

describe("revealedFrom", () => {
    it("reads an opened box and rejects a closed one", () => {
        expect(revealedFrom(points)).toEqual({ kind: "points", title: "", emoji: "", points: 12 });
        expect(revealedFrom(closed("b1"))).toBeNull();
        expect(revealedFrom(null)).toBeNull();
    });
});

describe("mysteryDomUpdate", () => {
    it("shows the reveal AND the next closed box together", () => {
        const both = mysteryDomUpdate({ closedCount: 1, closedId: "b9", revealed: { kind: "points", title: "", emoji: "", points: 7 } }, "en", false);
        expect(both).toMatchObject({ showClosed: true, showRevealed: true, revealedText: "+7 points", closedLabel: "🎁 A mystery box! Tap to open" });
    });
    it("closed: one box, or several with a count", () => {
        const one = mysteryDomUpdate({ closedCount: 1, closedId: "b1", revealed: null }, "en", false);
        expect(one).toMatchObject({ showClosed: true, showRevealed: false, closedLabel: "🎁 A mystery box! Tap to open" });
        const two = mysteryDomUpdate({ closedCount: 2, closedId: "b1", revealed: null }, "es", false);
        expect(two.closedLabel).toBe("🎁 ¡Una caja sorpresa! Toca para abrir ×2");
    });
    it("revealed surprise and points, with stars in star mode", () => {
        const s = mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: { kind: "surprise", title: "Pick dessert tonight", emoji: "🍨", points: 0 } }, "en", false);
        expect(s).toMatchObject({ showClosed: false, showRevealed: true, revealedText: "You got: Pick dessert tonight 🍨 — ask your parents!" });
        const es = mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: { kind: "surprise", title: "Postre", emoji: "", points: 0 } }, "es", false);
        expect(es.revealedText).toBe("Te tocó: Postre — ¡pídesela a tus papás!");
        const p = mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: { kind: "points", title: "", emoji: "", points: 12 } }, "en", false);
        expect(p.revealedText).toBe("+12 points");
        expect(mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: { kind: "points", title: "", emoji: "", points: 12 } }, "es", true).revealedText).toBe("+12 ⭐");
    });
    it("nothing to show hides both blocks", () => {
        expect(mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: null }, "en", false)).toMatchObject({ showClosed: false, showRevealed: false });
    });
    it("copy exists in both languages", () => {
        for (const key of ["closed", "opening", "off", "failed"] as const) {
            expect(MYSTERY_COPY[key].es.length).toBeGreaterThan(3);
            expect(MYSTERY_COPY[key].en.length).toBeGreaterThan(3);
        }
    });
});
