import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import type { HeaderTone } from "../src/lib/headerTone";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

/** Pages rendered through PageLayout → PageHeader (spec "Section → color map"). */
const PAGE_LAYOUT_TONES: Record<string, HeaderTone> = {
    "pages/calendar.astro": "sky",
    "pages/calendar/scan.astro": "sky",
    "pages/parent/approvals.astro": "sky",
    "pages/parent/day.astro": "sky",
    "pages/parent/kiosk.astro": "sky",
    "pages/parent/routines.astro": "sky",
    "pages/routines.astro": "sky",
    "pages/parent/tasks.astro": "sky",
    "pages/parent/tasks/[id]/edit.astro": "sky",
    "pages/parent/payouts.astro": "mint",
    "pages/parent/settings/envelopes.astro": "mint",
    "pages/parent/settings/family-bank.astro": "mint",
    "pages/gigs/my-gigs.astro": "sun",
    "pages/parent/gigs.astro": "sun",
    "pages/family-cup.astro": "sun",
    "pages/meals.astro": "coral",
    "pages/parent/consequences.astro": "coral",
    "pages/parent/rewards.astro": "coral",
    "pages/parent/rewards/[id]/edit.astro": "coral",
    "pages/pet.astro": "coral",
    "pages/pet/quests.astro": "coral",
    "pages/pet/shop.astro": "coral",
    "pages/rewards.astro": "coral",
    "pages/shopping.astro": "coral",
    "pages/dm.astro": "cream",
    "pages/notifications.astro": "cream",
    "pages/parent/jarvis-schedules.astro": "cream",
    "pages/parent/settings/family.astro": "cream",
    "pages/parent/settings/index.astro": "cream",
    "pages/parent/settings/mcp-tokens.astro": "cream",
    "pages/parent/settings/referrals.astro": "cream",
    "pages/parent/settings/subscription.astro": "cream",
    "pages/parent/starter-packs.astro": "cream",
    "pages/parent/members.astro": "cream",
    "pages/parent/analytics.astro": "cream",
};

describe("PageLayout pages use their section tone", () => {
    it.each(Object.entries(PAGE_LAYOUT_TONES))("%s → %s", (file, tone) => {
        const src = read(file);
        const tones = [...src.matchAll(/\btone="([a-z]+)"/g)].map((m) => m[1]);
        expect(tones, `${file} tone= props`).toEqual([tone]);
        expect(src).not.toMatch(/\b(headerClass|backClass)=|<PageLayout[^>]*\sdark[\s>=]/);
    });
});

describe("PageHeader renders through headerToneClass", () => {
    it("has no per-page color escape hatches", () => {
        const src = read("components/ui/PageHeader.astro");
        expect(src).toMatch(/headerToneClass\(tone\)/);
        expect(src).not.toMatch(/headerClass|backClass|\bdark\b/);
    });
});
