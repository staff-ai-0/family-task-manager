import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { buttonClass, type ButtonSize, type ButtonVariant } from "../src/lib/buttonClasses";

const VARIANTS: ButtonVariant[] = ["primary", "secondary", "mint", "sun", "ghost"];
const SIZES: ButtonSize[] = ["sm", "md", "lg", "icon"];

describe("buttonClass", () => {
    it("defaults to primary / md", () => {
        expect(buttonClass()).toBe(buttonClass("primary", "md"));
    });

    it.each(VARIANTS)("%s has ink text, ink outline, hard shadow — never white text", (v) => {
        const cls = buttonClass(v);
        expect(cls.split(/\s+/)).toEqual(expect.arrayContaining(["text-brand-ink", "border-2", "border-brand-ink"]));
        expect(cls).toContain("shadow-[var(--shadow-card)]");
        expect(cls).not.toContain("text-white");
    });

    it("maps each fill variant to its brand color and -deep hover", () => {
        expect(buttonClass("primary")).toMatch(/\bbg-brand-coral\b.*hover:bg-brand-coral-deep/);
        expect(buttonClass("secondary")).toMatch(/\bbg-brand-sky\b.*hover:bg-brand-sky-deep/);
        expect(buttonClass("mint")).toMatch(/\bbg-brand-mint\b.*hover:bg-brand-mint-deep/);
        expect(buttonClass("sun")).toMatch(/\bbg-brand-sun\b.*hover:bg-brand-sun-deep/);
    });

    it.each(SIZES)("size %s is applied", (s) => {
        expect(buttonClass("primary", s)).not.toBe(buttonClass("primary", s === "md" ? "sm" : "md"));
    });

    it("unknown variant/size fall back to primary/md", () => {
        expect(buttonClass("violet" as ButtonVariant, "xl" as ButtonSize)).toBe(buttonClass("primary", "md"));
    });

    it("Button.astro renders through buttonClass (single source)", () => {
        const src = readFileSync(fileURLToPath(new URL("../src/components/ui/Button.astro", import.meta.url)), "utf8");
        expect(src).toMatch(/import \{ buttonClass[^}]*\} from "\.\.\/\.\.\/lib\/buttonClasses"/);
        expect(src).not.toMatch(/const variants\s*=/);
    });
});
