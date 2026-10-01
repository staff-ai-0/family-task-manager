import { describe, expect, it } from "vitest";

import { BADGE_META, badgesView, shouldCelebrateBadges, stars, TIER_NAMES } from "../src/lib/badges";
import { progressLine } from "../src/lib/progress";

const KEYS = ["chores", "streak", "perfect_week", "extra_mile", "gigs", "saver", "rewards", "cup"];

const badge = (key: string, count: number, tier: number, next: number | null) => ({
    badge: key, count, tier, next_target: next, earned_at: tier ? "2026-10-01T12:00:00Z" : null,
});

const resp = (over: Record<string, unknown> = {}) => ({
    applies: true,
    badges: [
        badge("chores", 60, 2, 200), badge("streak", 5, 0, 7), badge("perfect_week", 0, 0, 1),
        badge("extra_mile", 3, 1, 10), badge("gigs", 50, 3, null), badge("saver", 0, 0, 1),
        badge("rewards", 4, 1, 5), badge("cup", 1, 1, 3),
    ],
    unseen: [],
    earned_total: 8,
    ...over,
});

describe("catalog copy", () => {
    it("has the 8 spec families in order, each with an emoji and both names", () => {
        expect(Object.keys(BADGE_META)).toEqual(KEYS);
        for (const k of KEYS) {
            expect(BADGE_META[k].emoji.length).toBeGreaterThan(0);
            expect(BADGE_META[k].es.length).toBeGreaterThan(0);
            expect(BADGE_META[k].en.length).toBeGreaterThan(0);
        }
        expect(BADGE_META.chores).toEqual({ emoji: "🧹", es: "Manos a la obra", en: "Hard Worker" });
        expect(BADGE_META.cup).toEqual({ emoji: "🏆", es: "Copa familiar", en: "Cup Champion" });
    });
    it("names three tiers per language", () => {
        expect(TIER_NAMES.es).toEqual(["Bronce", "Plata", "Oro"]);
        expect(TIER_NAMES.en).toEqual(["Bronze", "Silver", "Gold"]);
    });
    it("draws a tier as three stars", () => {
        expect(stars(0)).toBe("☆☆☆");
        expect(stars(2)).toBe("★★☆");
        expect(stars(3)).toBe("★★★");
        expect(stars(9)).toBe("★★★");
        expect(stars(-1)).toBe("☆☆☆");
    });
});

describe("badgesView", () => {
    it("returns null without a usable response", () => {
        expect(badgesView(null, "es")).toBeNull();
        expect(badgesView(undefined, "es")).toBeNull();
        expect(badgesView({ applies: false, badges: [] }, "es")).toBeNull();
        expect(badgesView({ applies: true }, "es")).toBeNull();
    });

    it("builds one tile per family with name, stars and progress", () => {
        const v = badgesView(resp(), "es")!;
        expect(v.tiles.map((t) => t.key)).toEqual(KEYS);
        const chores = v.tiles[0];
        expect(chores).toMatchObject({
            emoji: "🧹", name: "Manos a la obra", tier: 2, stars: "★★☆",
            tierLabel: "Plata · 2/3", progressLabel: "60/200", barPct: 30, maxed: false,
        });
        expect(v.tiles[1]).toMatchObject({ tier: 0, stars: "☆☆☆", tierLabel: "Aún sin ganar", progressLabel: "5/7", barPct: 71 });
        expect(badgesView(resp(), "en")!.tiles[1].tierLabel).toBe("Not earned yet");
    });

    it("shows a gold family as maxed", () => {
        const gigs = badgesView(resp(), "es")!.tiles[4];
        expect(gigs).toMatchObject({ tier: 3, stars: "★★★", maxed: true, barPct: 100, progressLabel: "Máx" });
        expect(badgesView(resp(), "en")!.tiles[4].progressLabel).toBe("Max");
    });

    it("never draws a bar past 100% when the count is above the target", () => {
        const v = badgesView(resp({ badges: [badge("chores", 45, 2, 10)] }), "es")!;
        expect(v.tiles[0].barPct).toBe(100);
    });

    it("picks the 3 families closest to their next tier", () => {
        // ratios: rewards .8 · streak .71 · cup .33 · chores .3 · extra_mile .3 · others 0
        expect(badgesView(resp(), "es")!.next.map((t) => t.key)).toEqual(["rewards", "streak", "cup"]);
    });

    it("breaks ties in catalog order and skips maxed families", () => {
        const v = badgesView(resp({
            badges: [badge("chores", 5, 0, 10), badge("streak", 50, 3, null), badge("extra_mile", 5, 1, 10), badge("cup", 0, 0, 1)],
        }), "es")!;
        expect(v.next.map((t) => t.key)).toEqual(["chores", "extra_mile", "cup"]);
        expect(v.allMaxed).toBe(false);
    });

    it("reports allMaxed when every family is gold", () => {
        const v = badgesView(resp({ badges: KEYS.map((k) => badge(k, 999, 3, null)) }), "es")!;
        expect(v.next).toEqual([]);
        expect(v.allMaxed).toBe(true);
    });

    it("totals earned tiers over the tiles it shows", () => {
        expect(badgesView(resp(), "es")!.earnedTotal).toBe(8);
        expect(badgesView(resp(), "es")!.totalLabel).toBe("8 de 24 ganadas");
        expect(badgesView(resp(), "en")!.totalLabel).toBe("8 of 24 earned");
    });

    it("drops a badge key it has no name for, and never acks its id", () => {
        const v = badgesView(resp({
            badges: [...resp().badges, badge("dragon", 3, 1, 9)],
            unseen: [{ id: "x1", badge: "dragon", tier: 1 }, { id: "c1", badge: "cup", tier: 1 }],
        }), "es")!;
        expect(v.tiles.map((t) => t.key)).toEqual(KEYS);
        expect(v.unseenIds).toEqual(["c1"]);
        expect(v.unseenTiles.map((t) => t.key)).toEqual(["cup"]);
    });
});

describe("unseen badges (the celebration's content)", () => {
    it("has no headline when nothing is unseen", () => {
        const v = badgesView(resp(), "es")!;
        expect(v.unseenTiles).toEqual([]);
        expect(v.unseenIds).toEqual([]);
        expect(v.headline).toBeNull();
    });

    it("folds several unseen tiers of one family into its highest tile and keeps every id", () => {
        const v = badgesView(resp({
            unseen: [
                { id: "c2", badge: "cup", tier: 1 },
                { id: "a1", badge: "chores", tier: 1 },
                { id: "a2", badge: "chores", tier: 2 },
            ],
        }), "es")!;
        expect(v.unseenTiles).toEqual([
            { key: "chores", emoji: "🧹", name: "Manos a la obra", tier: 2, stars: "★★☆", tierName: "Plata" },
            { key: "cup", emoji: "🏆", name: "Copa familiar", tier: 1, stars: "★☆☆", tierName: "Bronce" },
        ]);
        expect(v.unseenIds.sort()).toEqual(["a1", "a2", "c2"]);
        expect(v.headline).toBe("¡Ganaste 2 insignias!");
        expect(badgesView(resp({ unseen: [{ id: "a1", badge: "chores", tier: 1 }, { id: "c2", badge: "cup", tier: 1 }] }), "en")!.headline)
            .toBe("You earned 2 badges!");
    });

    it("uses the singular headline for one badge", () => {
        const one = { unseen: [{ id: "c2", badge: "cup", tier: 1 }] };
        expect(badgesView(resp(one), "es")!.headline).toBe("¡Nueva insignia!");
        expect(badgesView(resp(one), "en")!.headline).toBe("New badge!");
    });
});

describe("shouldCelebrateBadges", () => {
    const withUnseen = badgesView(resp({ unseen: [{ id: "c2", badge: "cup", tier: 1 }] }), "es");
    it("celebrates when the tour is done or unknown and no rank-up is showing", () => {
        expect(shouldCelebrateBadges(withUnseen, false, true)).toBe(true);
        expect(shouldCelebrateBadges(withUnseen, false, undefined)).toBe(true);
        expect(shouldCelebrateBadges(withUnseen, false, null)).toBe(true);
    });
    it("waits while the welcome tour can still run", () => {
        expect(shouldCelebrateBadges(withUnseen, false, false)).toBe(false);
    });
    it("waits when a rank-up celebration is on this load (never two modals)", () => {
        expect(shouldCelebrateBadges(withUnseen, true, true)).toBe(false);
    });
    it("never celebrates with nothing unseen or no view", () => {
        expect(shouldCelebrateBadges(badgesView(resp(), "es"), false, true)).toBe(false);
        expect(shouldCelebrateBadges(null, false, true)).toBe(false);
    });
});

describe("progressLine with badges (parent hub)", () => {
    it("appends the badge count when the kid has any", () => {
        expect(progressLine({ role: "child", streak_days: 5, rank: 4, badge_count: 5 }, "es")).toBe("🔥 5 · Estrella · 🏅 5");
    });
    it("is unchanged with zero or no badge count", () => {
        expect(progressLine({ role: "child", streak_days: 5, rank: 4, badge_count: 0 }, "es")).toBe("🔥 5 · Estrella");
        expect(progressLine({ role: "teen", streak_days: 0, rank: 4 }, "en")).toBe("🔥 0 · Pro");
    });
});
