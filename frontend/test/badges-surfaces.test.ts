import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

describe("ProgressSheet — next badges strip (UX-D2)", () => {
    const src = read("components/home/ProgressSheet.astro");
    it("takes an optional badges view and renders the strip only when it has one", () => {
        expect(src).toMatch(/badges\?\s*:\s*BadgesView\s*\|\s*null/);
        expect(src).toMatch(/\{\s*badges\s*&&\s*\(/);
        expect(src).toMatch(/data-badges-next/);
    });
    it("lists the next tiles with a progress label and links to the full shelf", () => {
        expect(src).toMatch(/badges\.next\.map\(/);
        expect(src).toMatch(/\.progressLabel/);
        expect(src).toMatch(/href="\/profile#badges"/);
    });
    it("has a line for a kid who holds every badge", () => {
        expect(src).toMatch(/badges\.allMaxed/);
    });
    it("scrolls instead of pushing Close off a small phone", () => {
        const panel = src.match(/<div class="rounded-t-\[var\(--radius-tile\)\][^"]*"/)?.[0] ?? "";
        expect(panel).toMatch(/max-h-\[90dvh\]/);
        expect(panel).toMatch(/overflow-y-auto/);
    });
});

describe("profile — badge shelf (UX-D2)", () => {
    const src = read("pages/profile.astro");
    it("fetches the badges with the page's other calls and builds the view", () => {
        expect(src).toMatch(/apiFetch<any>\("\/api\/progress\/badges",\s*\{\s*token\s*\}\)/);
        expect(src).toMatch(/badgesView\(/);
    });
    it("renders the shelf only when there is a view, under the #badges anchor", () => {
        expect(src).toMatch(/\{\s*badges\s*&&\s*\(/);
        expect(src).toMatch(/id="badges"/);
        expect(src).toMatch(/badges\.tiles\.map\(/);
    });
    it("shows stars, progress and an accessible tier label on each tile", () => {
        expect(src).toMatch(/\.stars/);
        expect(src).toMatch(/\.progressLabel/);
        expect(src).toMatch(/aria-label=\{[^}]*tierLabel/);
    });
});
