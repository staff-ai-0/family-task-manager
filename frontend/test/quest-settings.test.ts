import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = readFileSync(fileURLToPath(new URL("../src/pages/parent/settings/family.astro", import.meta.url)), "utf8");

describe("family settings — weekly quest bonus (UX-D3)", () => {
    it("has a bounded number field pre-filled from the family", () => {
        const input = src.match(/<input[^>]*id="quest-bonus"[^>]*>/s)?.[0] ?? "";
        expect(input).not.toBe("");
        expect(input).toMatch(/type="number"/);
        expect(input).toMatch(/min="0"/);
        expect(input).toMatch(/max="500"/);
        expect(input).toMatch(/value=\{family\?\.quest_bonus_points \?\? 20\}/);
    });
    it("explains that zero switches quests off, in both languages", () => {
        expect(src).toContain("0 desactiva las misiones semanales");
        expect(src).toContain("0 turns weekly quests off");
    });
    it("saves through the existing family update with the right field", () => {
        expect(src).toMatch(/quest_bonus_points:\s*value/);
        expect(src).toMatch(/id="quest-save"/);
    });
    it("rejects values outside 0–500 before calling the API", () => {
        expect(src).toMatch(/value < 0 \|\| value > 500/);
        expect(src).toMatch(/Number\.isInteger\(value\)/);
    });
});
