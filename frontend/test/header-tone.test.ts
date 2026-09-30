import { describe, expect, it } from "vitest";

import { HEADER_TONES, headerToneClass, type HeaderTone } from "../src/lib/headerTone";

describe("headerToneClass", () => {
    it("lists exactly the five section tones", () => {
        expect([...HEADER_TONES]).toEqual(["sky", "mint", "sun", "coral", "cream"]);
    });

    it.each(["sky", "mint", "sun", "coral", "cream"] as HeaderTone[])("%s → flat brand fill, ink outline, ink text", (tone) => {
        const cls = headerToneClass(tone).split(/\s+/);
        expect(cls).toContain(`bg-brand-${tone}`);
        expect(cls).toContain("border-b-4");
        expect(cls).toContain("border-brand-ink");
        expect(cls).toContain("text-brand-ink");
    });

    it("never produces white text or a gradient", () => {
        for (const tone of HEADER_TONES) {
            expect(headerToneClass(tone)).not.toMatch(/text-white|bg-gradient/);
        }
    });

    it("unknown tone falls back to cream", () => {
        expect(headerToneClass("violet" as HeaderTone)).toBe(headerToneClass("cream"));
    });
});
