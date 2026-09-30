import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = readFileSync(
    fileURLToPath(new URL("../src/components/home/RankUpCelebration.astro", import.meta.url)),
    "utf8",
);
const celebrateSrc = readFileSync(
    fileURLToPath(new URL("../src/lib/celebrate.ts", import.meta.url)),
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
    it("fires confetti INTO the dialog, after showModal (F3 — confetti painted under the top-layer modal)", () => {
        const modalIdx = src.indexOf(".showModal()");
        const confettiIdx = src.search(/fireConfetti\(\s*dlg\b/);
        expect(modalIdx).toBeGreaterThan(-1);
        expect(confettiIdx).toBeGreaterThan(-1);
        expect(confettiIdx).toBeGreaterThan(modalIdx);
    });
});

describe("fireConfetti accepts an optional host (F3)", () => {
    it("signature takes an optional host element and defaults to document.body", () => {
        expect(celebrateSrc).toMatch(/export function fireConfetti\(\s*host\?\s*:\s*HTMLElement\s*\)/);
        expect(celebrateSrc).toMatch(/\(host\s*\?\?\s*document\.body\)\.appendChild\(canvas\)/);
    });
    it("celebrate() still calls the zero-arg form (unchanged TaskDeck behaviour)", () => {
        const celebrateFn = celebrateSrc.slice(celebrateSrc.indexOf("export function celebrate"));
        expect(celebrateFn).toMatch(/fireConfetti\(\)/);
    });
});
