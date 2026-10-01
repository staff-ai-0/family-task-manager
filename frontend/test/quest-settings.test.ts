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
        expect(input).toMatch(/value=\{family\?\.quest_bonus_points \?\? ""\}/);
        expect(input).toMatch(/placeholder="20"/);
    });
    it("says quests are off when the bonus is not above zero (undecided or 0), in both languages", () => {
        const guard = src.search(/\{\s*!\(Number\(family\?\.quest_bonus_points\) > 0\)\s*&&/);
        expect(guard).toBeGreaterThan(-1);
        const line = src.slice(guard).match(/<p class="text-xs font-bold text-brand-ink" data-quest-off>[\s\S]*?<\/p>/)?.[0] ?? "";
        expect(line).not.toBe("");
        expect(line).toContain("Las misiones semanales están apagadas.");
        expect(line).toContain("Weekly quests are off.");
        // Directly under the field's hint, still inside the quest section.
        const hint = src.indexOf("A change applies from the next quest.");
        expect(guard).toBeGreaterThan(hint);
        expect(guard).toBeLessThan(src.indexOf('id="quest-save"'));
    });
    it("explains that zero switches quests off, in both languages", () => {
        expect(src).toContain("0 desactiva las misiones semanales");
        expect(src).toContain("0 turns weekly quests off");
    });
    it("says a change applies from the next quest, in both languages", () => {
        expect(src).toContain("El cambio aplica desde la siguiente misión.");
        expect(src).toContain("A change applies from the next quest.");
    });
    it("saves through the existing family update with the right field", () => {
        expect(src).toMatch(/quest_bonus_points:\s*value/);
        expect(src).toMatch(/id="quest-save"/);
    });
    it("rejects values outside 0–500 before calling the API", () => {
        expect(src).toMatch(/value < 0 \|\| value > 500/);
        expect(src).toMatch(/Number\.isInteger\(value\)/);
    });
    it("treats an empty field as invalid instead of saving zero", () => {
        expect(src).toMatch(/const raw = input\.value\.trim\(\);/);
        const blankCheckIndex = src.search(/raw === ""/);
        expect(blankCheckIndex).toBeGreaterThan(-1);
        const patchIndex = src.indexOf("quest_bonus_points: value");
        expect(blankCheckIndex).toBeLessThan(patchIndex);
    });
});
