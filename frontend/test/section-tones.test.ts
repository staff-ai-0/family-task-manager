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
    "pages/parent/setup.astro": "sky",
    "pages/parent/payouts.astro": "mint",
    "pages/parent/payouts/receipts.astro": "mint",
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

/** Custom hero headers compose headerToneClass directly (spec "Custom hero headers"). */
const HERO_TONES: Record<string, HeaderTone> = {
    "pages/bank.astro": "mint",
    "pages/envelopes.astro": "mint",
    "pages/budget/index.astro": "mint",
    "pages/budget/import.astro": "mint",
    "pages/budget/recycle-bin/index.astro": "mint",
    "pages/gigs/index.astro": "sun",
    "pages/parent/assignments.astro": "sky",
    "pages/calendar/month.astro": "sky",
    "pages/profile.astro": "cream",
    "components/home/KidHeader.astro": "sky",
};

describe("custom hero headers use their section tone", () => {
    it.each(Object.entries(HERO_TONES))("%s → %s", (file, tone) => {
        const src = read(file);
        expect(src).toContain(`headerToneClass("${tone}")`);
        expect(src).not.toMatch(/<header[^>]*bg-gradient-to-/);
    });
});

describe("chat screens use ChatShell tone", () => {
    it.each(["pages/chat.astro", "pages/soporte.astro", "pages/dm/[id].astro", "pages/parent/jarvis.astro"])("%s → cream", (file) => {
        const src = read(file);
        expect(src).toMatch(/<ChatShell[\s\S]*?\btone="cream"/);
        expect(src).not.toMatch(/headerClass=/);
    });
    it("ChatShell renders through headerToneClass with no hardcoded white text", () => {
        const src = read("components/ui/ChatShell.astro");
        expect(src).toMatch(/headerToneClass\(tone\)/);
        expect(src).not.toMatch(/text-white|headerClass/);
    });
});

describe("home heroes", () => {
    it("parent hub hero is flat brand ink with white text", () => {
        expect(read("pages/parent/index.astro")).toMatch(/<header[\s\S]*?class="bg-brand-ink text-white/);
    });
    it("kid hero: teen keeps its dark skin, child uses the sky tone", () => {
        const src = read("components/home/KidHeader.astro");
        expect(src).toContain('"bg-[#1E2230] text-white"');
        expect(src).not.toMatch(/bg-brand-sky-deep/);
    });
});
