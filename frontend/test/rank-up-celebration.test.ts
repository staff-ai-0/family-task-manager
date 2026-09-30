import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = readFileSync(
    fileURLToPath(new URL("../src/components/home/RankUpCelebration.astro", import.meta.url)),
    "utf8",
);

describe("RankUpCelebration is a real modal (T5-2)", () => {
    it("renders a native <dialog>, not a div with role=\"dialog\"", () => {
        expect(src).toMatch(/<dialog\b/);
        expect(src).not.toMatch(/role="dialog"/);
    });
    it("opens with showModal()", () => {
        expect(src).toMatch(/\.showModal\(\)/);
    });
    it("handles the dialog's cancel event (Escape)", () => {
        expect(src).toMatch(/addEventListener\(\s*["']cancel["']/);
    });
    it("explicitly focuses the confirm button", () => {
        expect(src).toMatch(/\.focus\(\)/);
    });
    it("acks exactly once, guarded by a done flag", () => {
        expect(src).toMatch(/let done = false/);
        const acks = src.match(/\/api\/progress\/me\/ack-rank/g) ?? [];
        expect(acks).toHaveLength(1);
    });
    it("centers the dialog (m-auto, not m-0 — Tailwind v4 preflight zeroes margins)", () => {
        const openTag = src.match(/<dialog id="rank-up"[^>]*>/s)?.[0] ?? "";
        expect(openTag).not.toBe("");
        expect(openTag).toMatch(/(?<![\w-])m-auto(?![\w-])/);
        expect(openTag).not.toMatch(/(?<![\w-])m-0(?![\w-])/);
    });
});
