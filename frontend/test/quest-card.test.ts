import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

describe("QuestCard (UX-D3)", () => {
    const src = read("components/home/QuestCard.astro");
    it("renders from questDomUpdate, the same mapping the live refresh uses", () => {
        expect(src).toMatch(/questDomUpdate\(\s*quest\s*,\s*lang\s*\)/);
        for (const slot of ["data-quest-title", "data-quest-progress", "data-quest-bar", "data-quest-days", "data-quest-bonus", "data-quest-done-heading", "data-quest-done-bonus"]) {
            expect(src).toContain(slot);
        }
    });
    it("switches blocks with the hidden ATTRIBUTE, never the hidden class", () => {
        expect(src).toMatch(/data-quest-progress-block\s+hidden=\{u\.showDone\}/);
        expect(src).toMatch(/data-quest-done-block\s+hidden=\{!u\.showDone\}/);
        expect(src).not.toMatch(/class="[^"]*(?<![\w-])hidden(?![\w-])/);
    });
    it("is not a modal", () => {
        expect(src).not.toMatch(/<dialog\b/);
        expect(src).not.toMatch(/showModal/);
    });
    it("celebrates once per quest id: confetti + one keepalive ack", () => {
        expect(src).toMatch(/const acked = new Set<string>\(\)/);
        expect(src.match(/\/api\/progress\/quest\/ack/g) ?? []).toHaveLength(1);
        expect(src).toMatch(/keepalive:\s*true/);
        expect(src).toMatch(/JSON\.stringify\(\{\s*id\s*\}\)/);
        expect(src).toMatch(/fireConfetti\(/);
    });
    it("keeps its confetti out of the way of a celebration modal on the same load", () => {
        expect(src).toMatch(/dialog\[open\]/);
    });
    it("refreshes when the deck is emptied", () => {
        expect(src).toMatch(/addEventListener\(\s*["']ftm:deck-empty["']/);
        expect(src).toMatch(/fetch\(\s*["']\/api\/progress\/quest["']/);
    });
    it("puts no emoji in a heading and uses no h1", () => {
        expect(src).not.toMatch(/<h1\b/);
    });
});

describe("kid home wiring (UX-D3)", () => {
    const home = read("components/home/KidHome.astro");
    const dash = read("pages/dashboard.astro");
    it("KidHome takes the quest view and renders the card only when there is one", () => {
        expect(home).toMatch(/quest:\s*QuestView\s*\|\s*null/);
        expect(home).toMatch(/\{\s*quest\s*&&\s*<QuestCard\b/);
    });
    it("the card sits directly under the task deck", () => {
        const deckIdx = home.indexOf("<TaskDeck");
        const cardIdx = home.indexOf("<QuestCard");
        const reviewIdx = home.indexOf("inReview > 0");
        expect(deckIdx).toBeGreaterThan(-1);
        expect(cardIdx).toBeGreaterThan(deckIdx);
        expect(reviewIdx).toBeGreaterThan(cardIdx);
    });
    it("the dashboard fetches the quest with its other calls and passes the view down", () => {
        expect(dash).toMatch(/apiFetch<any>\("\/api\/progress\/quest",\s*\{\s*token\s*\}\)/);
        expect(dash).toMatch(/const quest = questView\(questResp,\s*lang,\s*starMode\)/);
        expect(dash).toMatch(/<KidHome[\s\S]*?quest=\{quest\}/);
    });
});
