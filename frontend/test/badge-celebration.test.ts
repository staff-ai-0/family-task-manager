import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

describe("BadgeCelebration is a real modal (same contract as RankUpCelebration)", () => {
    const src = read("components/home/BadgeCelebration.astro");
    it("renders a native <dialog>, not a div with role=\"dialog\"", () => {
        expect(src).toMatch(/<dialog\b/);
        expect(src).not.toMatch(/role="dialog"/);
    });
    it("opens with showModal() and focuses the confirm button", () => {
        expect(src).toMatch(/\.showModal\(\)/);
        expect(src).toMatch(/\.focus\(\)/);
    });
    it("handles the dialog's cancel event (Escape)", () => {
        expect(src).toMatch(/addEventListener\(\s*["']cancel["']/);
    });
    it("acks exactly once, guarded by a done flag, with the ids it was rendered with", () => {
        expect(src).toMatch(/let done = false/);
        expect(src.match(/\/api\/progress\/badges\/ack/g) ?? []).toHaveLength(1);
        expect(src).toMatch(/data-ids=\{JSON\.stringify\(badges\.unseenIds\)\}/);
        expect(src).toMatch(/JSON\.stringify\(\{\s*ids\s*\}\)/);
    });
    it("centers the dialog (m-auto, not m-0 — Tailwind v4 preflight zeroes margins)", () => {
        const openTag = src.match(/<dialog id="badge-unlock"[^>]*>/s)?.[0] ?? "";
        expect(openTag).not.toBe("");
        expect(openTag).toMatch(/(?<![\w-])m-auto(?![\w-])/);
        expect(openTag).not.toMatch(/(?<![\w-])m-0(?![\w-])/);
    });
    it("fires confetti INTO the dialog, after showModal", () => {
        const modalIdx = src.indexOf(".showModal()");
        const confettiIdx = src.search(/fireConfetti\(\s*dlg\b/);
        expect(modalIdx).toBeGreaterThan(-1);
        expect(confettiIdx).toBeGreaterThan(modalIdx);
    });
    it("caps the tiles and says how many more", () => {
        expect(src).toMatch(/CELEBRATION_MAX_TILES/);
        expect(src).toMatch(/more\s*>\s*0/);
    });
    it("never puts an emoji in a heading element", () => {
        expect(src).not.toMatch(/<h1\b/);
    });
    it("sends the ack with keepalive, so a tap on a nav link right after dismissing does not lose it", () => {
        expect(src).toMatch(/keepalive:\s*true/);
    });
    it("never lays tiles out in three columns, and wraps long badge names", () => {
        expect(src).not.toMatch(/grid-cols-3/);
        expect(src).toMatch(/<p class="[^"]*\bbreak-words\b[^"]*">\{b\.name\}<\/p>/);
    });
    it("hides the stars from screen readers (the tier name is printed right after)", () => {
        const stars = src.match(/<p\b[^>]*>\{b\.stars\}<\/p>/)?.[0] ?? "";
        expect(stars).not.toBe("");
        expect(stars).toMatch(/aria-hidden="true"/);
        expect(stars).not.toMatch(/role="img"|aria-label/);
    });
});

describe("dashboard wiring (one modal per load, tour-gated)", () => {
    const src = read("pages/dashboard.astro");
    it("fetches the badges with the kid home's other calls", () => {
        expect(src).toMatch(/apiFetch<any>\("\/api\/progress\/badges",\s*\{\s*token\s*\}\)/);
        expect(src).toMatch(/const badges = badgesView\(badgesResp,\s*lang\)/);
    });
    it("derives the rank-up decision once and gates the badge modal on it", () => {
        expect(src).toMatch(/const rankCelebrating = shouldCelebrate\(\s*progress\s*,\s*user\.completed_welcome_tour\s*\)/);
        expect(src).toMatch(
            /shouldCelebrateBadges\(\s*badges\s*,\s*rankCelebrating\s*,\s*user\.completed_welcome_tour\s*\)\s*&&\s*\(?\s*<BadgeCelebration/,
        );
    });
    it("renders BadgeCelebration nowhere else", () => {
        expect(src.match(/<BadgeCelebration\b/g) ?? []).toHaveLength(1);
    });
    it("hands the badges view to the progress sheet", () => {
        expect(src).toMatch(/<ProgressSheet[^>]*badges=\{badges\}/);
    });
});
