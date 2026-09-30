import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { contrastRatio, mix, parseModeOverrides } from "./support/contrast";

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

describe("mix", () => {
    it("composites fg over bg by alpha", () => {
        expect(mix("#000000", "#FFFFFF", 0.5)).toBe("#808080");
        expect(mix("#4FB8E6", "#FFFFFF", 1)).toBe("#4FB8E6");
        expect(mix("#4FB8E6", "#FFFFFF", 0)).toBe("#FFFFFF");
    });
});

describe("parseModeOverrides", () => {
    const THEME = "@theme {\n  --color-brand-sky: #4FB8E6;\n}\n";
    it("reads hex overrides per body[data-ui-mode] block", () => {
        const css = THEME + 'body[data-ui-mode="adult"] {\n  --color-brand-cream: #FAFAFA;\n}\n';
        expect(parseModeOverrides(css)).toEqual({ default: {}, adult: { cream: "#FAFAFA" } });
    });
    it("refuses a brand override it cannot check (oklch / var / short hex)", () => {
        for (const v of ["oklch(0.6 0.2 250)", "var(--color-indigo-500)", "#fff"]) {
            const css = THEME + `body[data-ui-mode="teen"] {\n  --color-brand-coral: ${v};\n}\n`;
            expect(() => parseModeOverrides(css), v).toThrow(/#RRGGBB/);
        }
    });
    it("refuses a brand override outside @theme that no body[data-ui-mode] block covers", () => {
        for (const sel of ['[data-ui-mode="teen"] body', 'body[data-ui-mode="teen"], .x', "body[data-ui-mode='teen']"]) {
            const css = THEME + `${sel} {\n  --color-brand-coral: #5C7CFA;\n}\n`;
            expect(() => parseModeOverrides(css), sel).toThrow(/not in a parsed/);
        }
    });
});

const MODES = parseModeOverrides(CSS);

it("parses the default and adult UI modes", () => {
    expect(Object.keys(MODES)).toEqual(expect.arrayContaining(["default", "adult"]));
});

it("teen mode uses the default palette (decision 2026-09-30: teen = corners only)", () => {
    expect(MODES.teen ?? {}).toEqual({});
});

describe.each(Object.entries(MODES))("brand token contrast in %s mode (WCAG AA)", (_mode, over) => {
    const tok = (name: string) => over[name] ?? token(name);
    const surfaces = () => [WHITE, tok("cream"), tok("cream-deep")];

    it.each(["sky", "mint", "sun", "coral", "cream"])("ink text on the %s header tone", (tone) => {
        expect(contrastRatio(tok("ink"), tok(tone))).toBeGreaterThanOrEqual(AA);
    });

    it.each(["sky-deep", "mint-deep", "sun-deep", "coral-deep"])("ink text on the %s hover fill", (fill) => {
        expect(contrastRatio(tok("ink"), tok(fill))).toBeGreaterThanOrEqual(AA);
    });

    it.each(["sky", "mint", "coral", "sun"])("%s-text on white, cream and cream-deep", (hue) => {
        for (const bg of surfaces()) expect(contrastRatio(tok(`${hue}-text`), bg)).toBeGreaterThanOrEqual(AA);
    });

    it.each(["sky", "mint", "coral", "sun"])("%s-text on its own tint (30 percent) over white, cream and cream-deep", (hue) => {
        for (const bg of surfaces()) {
            expect(contrastRatio(tok(`${hue}-text`), mix(tok(hue), bg, 0.3))).toBeGreaterThanOrEqual(AA);
        }
    });

    it("white text on the ink parent-hub hero", () => {
        expect(contrastRatio(WHITE, tok("ink"))).toBeGreaterThanOrEqual(AA);
    });
});
