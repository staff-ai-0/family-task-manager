import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { contrastRatio } from "./support/contrast";

const CSS = readFileSync(fileURLToPath(new URL("../src/styles/global.css", import.meta.url)), "utf8");
const AA = 4.5;
const WHITE = "#FFFFFF";

/** First definition of --color-brand-<name> in global.css (the @theme block). */
function token(name: string): string {
    const m = new RegExp(`--color-brand-${name}:\\s*(#[0-9A-Fa-f]{6})\\s*;`).exec(CSS);
    if (!m) throw new Error(`token --color-brand-${name} not found in global.css`);
    return m[1];
}

describe("contrastRatio", () => {
    it("is 21 for black on white and 1 for a color on itself", () => {
        expect(contrastRatio("#000000", WHITE)).toBeCloseTo(21, 5);
        expect(contrastRatio("#4FB8E6", "#4FB8E6")).toBeCloseTo(1, 5);
    });
    it("is symmetric", () => {
        expect(contrastRatio("#1F2937", "#4FB8E6")).toBeCloseTo(contrastRatio("#4FB8E6", "#1F2937"), 10);
    });
});

describe("brand token contrast (WCAG AA, UX-B3)", () => {
    const ink = () => token("ink");

    it.each(["sky", "mint", "sun", "coral", "cream"])("ink text on the %s header tone", (tone) => {
        expect(contrastRatio(ink(), token(tone))).toBeGreaterThanOrEqual(AA);
    });

    it.each(["sky-deep", "mint-deep", "sun-deep", "coral-deep"])("ink text on the %s hover fill", (fill) => {
        expect(contrastRatio(ink(), token(fill))).toBeGreaterThanOrEqual(AA);
    });

    const surfaces = () => [["white", WHITE], ["cream", token("cream")], ["cream-deep", token("cream-deep")]] as const;
    it.each(["sky-text", "mint-text", "coral-text", "sun-text"])("%s on white, cream and cream-deep", (shade) => {
        for (const [, bg] of surfaces()) {
            expect(contrastRatio(token(shade), bg)).toBeGreaterThanOrEqual(AA);
        }
    });

    it("white text on the ink parent-hub hero", () => {
        expect(contrastRatio(WHITE, ink())).toBeGreaterThanOrEqual(AA);
    });
});
