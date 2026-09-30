import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { ICONS } from "../src/lib/icons";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

const EXPECTED = [
    "bell", "pet", "meals", "shopping", "calendar", "chat", "dm", "profile", "members", "rewards",
    "consequences", "assignments", "jarvis", "kiosk", "operator", "settings", "tasks", "payouts",
    "analytics", "help", "support", "routines", "back", "close", "language", "logout", "document",
];

describe("ICONS — the one line-icon set", () => {
    it("has exactly the chrome icons", () => {
        expect(Object.keys(ICONS).sort()).toEqual([...EXPECTED].sort());
    });
    it("every entry is a heroicons-outline path", () => {
        for (const [name, d] of Object.entries(ICONS)) expect(d, name).toMatch(/^M[\d.]/);
    });
});

describe("chrome renders through Icon", () => {
    it("MoreSheet has no private icon map or inline svg", () => {
        const src = read("components/MoreSheet.astro");
        expect(src).toMatch(/import Icon from "\.\/ui\/Icon\.astro"/);
        expect(src).not.toMatch(/const I\s*=\s*\{/);
        expect(src).not.toMatch(/<svg\b/);
    });
    it("calendar header action is a line icon on an on-palette pill (F-6)", () => {
        const src = read("pages/calendar.astro");
        const actions = src.slice(src.indexOf('slot="actions"'), src.indexOf('slot="header-extra"'));
        expect(actions).toMatch(/<Icon name="document"/);
        expect(actions).not.toMatch(/\p{Extended_Pictographic}/u);
        expect(actions).not.toMatch(/fuchsia/);
        expect(actions).toMatch(/bg-white text-brand-ink border-2 border-brand-ink/);
    });
    it("PageHeader back link uses Icon", () => {
        const src = read("components/ui/PageHeader.astro");
        expect(src).toMatch(/<Icon name="back"/);
        expect(src).not.toMatch(/<svg\b/);
    });
});
