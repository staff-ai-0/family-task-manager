import { describe, expect, it } from "vitest";

import { claimableGigs, isNewGig, payMeterView } from "../src/lib/kidHome";

const NOW = new Date("2026-09-28T12:00:00Z");
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3600 * 1000).toISOString();

const item = (over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
    offering: {
        id: "g1", title: "Lavar auto", points: 80, is_active: true, status: "approved",
        allowed_roles: null, allow_multiple: false, created_at: hoursAgo(100), reviewed_at: null,
        ...over,
    },
    my_claim: null,
    active_claimers: [],
    ...extra,
});

describe("isNewGig", () => {
    it("is new within 48h of being posted", () => {
        expect(isNewGig({ created_at: hoursAgo(47) }, NOW)).toBe(true);
        expect(isNewGig({ created_at: hoursAgo(49) }, NOW)).toBe(false);
    });
    it("uses the approval time for approved proposals", () => {
        expect(isNewGig({ created_at: hoursAgo(200), reviewed_at: hoursAgo(2) }, NOW)).toBe(true);
    });
    it("is not new without a usable timestamp", () => {
        expect(isNewGig({}, NOW)).toBe(false);
        expect(isNewGig({ created_at: "garbage" }, NOW)).toBe(false);
        expect(isNewGig(null, NOW)).toBe(false);
    });
});

describe("claimableGigs", () => {
    it("keeps active approved gigs the role may claim, newest first, capped", () => {
        const items = Array.from({ length: 8 }, (_, i) => item({ id: `g${i}`, created_at: hoursAgo(i) }));
        const chips = claimableGigs(items, "teen", NOW, 6);
        expect(chips).toHaveLength(6);
        expect(chips[0]).toEqual({ id: "g0", title: "Lavar auto", pesos: 80, isNew: true });
    });
    it("honors allowed_roles", () => {
        const items = [item({ id: "t", allowed_roles: ["teen"] }), item({ id: "all" })];
        expect(claimableGigs(items, "child", NOW).map((g) => g.id)).toEqual(["all"]);
        expect(claimableGigs(items, "teen", NOW).map((g) => g.id).sort()).toEqual(["all", "t"]);
    });
    it("drops gigs I already claimed and single-slot gigs someone else holds", () => {
        const items = [
            item({ id: "mine" }, { my_claim: { status: "claimed" } }),
            item({ id: "taken" }, { active_claimers: ["Sofia"] }),
            item({ id: "multi", allow_multiple: true }, { active_claimers: ["Sofia"] }),
            item({ id: "inactive", is_active: false }),
            item({ id: "pending", status: "pending" }),
        ];
        expect(claimableGigs(items, "teen", NOW).map((g) => g.id)).toEqual(["multi"]);
    });
    it("returns [] for a non-array payload", () => {
        expect(claimableGigs(null, "teen", NOW)).toEqual([]);
    });
});

describe("payMeterView", () => {
    it("shows only for chore_proportional with a positive goal", () => {
        expect(payMeterView({ mode: "flat", cap_cents: 25000 })).toEqual({ show: false });
        expect(payMeterView({ mode: "chore_proportional", cap_cents: 0 })).toEqual({ show: false });
        expect(payMeterView(null)).toEqual({ show: false });
    });
    it("maps the bar segments and release flag", () => {
        expect(payMeterView({
            mode: "chore_proportional", cap_cents: 25000, pct: 45, discounted_pct: 8, already_released: true,
        })).toEqual({ show: true, capCents: 25000, greenPct: 45, redPct: 8, released: true });
    });
    it("never lets the bar overflow", () => {
        const m = payMeterView({ mode: "chore_proportional", cap_cents: 100, pct: 96, discounted_pct: 7 });
        expect(m.show && m.greenPct + m.redPct).toBe(100);
        const n = payMeterView({ mode: "chore_proportional", cap_cents: 100, pct: 140, discounted_pct: -5 });
        expect(n).toMatchObject({ greenPct: 100, redPct: 0 });
    });
});
