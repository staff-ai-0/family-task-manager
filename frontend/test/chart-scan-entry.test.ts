import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const page = readFileSync(fileURLToPath(new URL("../src/pages/parent/tasks.astro", import.meta.url)), "utf8");

describe("parent chores page — scan a chart entry", () => {
    it("has a header action beside the + that opens the review page", () => {
        // Both controls sit in one actions group so the header keeps its layout.
        expect(page).toMatch(/<div slot="actions" class="flex items-center gap-2">\s*<a\s+href="\/parent\/tasks\/scan"[\s\S]*?aria-label=\{lang === "es" \? "Escanear tablero" : "Scan a chart"\}/);
        expect(page.indexOf('href="/parent/tasks/scan"')).toBeLessThan(page.indexOf('id="tcm-trigger"'));
    });
    it("offers the scan in the empty state too", () => {
        const empty = page.slice(page.indexOf("<EmptyState"), page.indexOf("/>", page.indexOf("<EmptyState")));
        expect(empty).toContain('ctaId="tcm-trigger"');
        expect(page).toMatch(/templateList\.length === 0 && \([\s\S]*?href="\/parent\/tasks\/scan"[\s\S]*?Escanear tablero/);
    });
});
