import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");
const card = read("../src/components/home/MysteryBoxCard.astro");
const home = read("../src/components/home/KidHome.astro");
const dash = read("../src/pages/dashboard.astro");

describe("MysteryBoxCard", () => {
    it("has the closed and revealed blocks, toggled with the hidden attribute, from the shared mapping", () => {
        expect(card).toMatch(/data-mystery-closed hidden=\{!u\.showClosed\}/);
        expect(card).toMatch(/data-mystery-revealed hidden=\{!u\.showRevealed\}/);
        expect(card).toMatch(/const u = mysteryDomUpdate\(view, lang, starMode\);/);
        expect(card).not.toMatch(/class="[^"]*(?<![\w-])hidden(?![\w-])/);
    });
    it("hides the whole card while there is nothing to show, and wakes up when the deck empties", () => {
        expect(card).toMatch(/<section data-mystery-card[^>]*hidden=\{!u\.showClosed && !u\.showRevealed\}/);
        expect(card).toContain('"ftm:deck-empty"');
        // Overdue cards keep the deck non-empty, yet the day can be perfect: refetch on every completion too.
        expect(card).toContain('"ftm:deck-completed"');
        expect(card).toMatch(/fetch\("\/api\/progress\/mystery"/);
    });
    it("opens through the proxied route, celebrates once, and keeps busy state", () => {
        expect(card).toMatch(/fetch\(`\/api\/progress\/mystery\/\$\{id\}\/open`/);
        expect(card).toMatch(/method: "POST"/);
        expect(card).toContain("fireConfetti(");
        expect(card).toMatch(/if \(busy\) return;/);
        // A failed open never leaves "Opening…" on screen: the last view is repainted.
        expect(card).toMatch(/let shown: MysteryView/);
        expect(card).toMatch(/finally \{[\s\S]*paint\(shown\)/);
        expect(card).toMatch(/showToast\(/);
        expect(card).toMatch(/r\.status === 409/);
        expect(existsSync(path("../src/pages/api/progress/[...path].ts"))).toBe(true);
    });
    it("uses no native dialog and no emoji in a heading 1", () => {
        expect(card).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(card).not.toMatch(/<h1/);
    });
});

describe("wiring", () => {
    it("the dashboard fetches the boxes and KidHome shows the card between the check-in and the quest", () => {
        expect(dash).toMatch(/apiFetch<any>\("\/api\/progress\/mystery", \{ token \}\)/);
        expect(dash).toMatch(/const mystery = mysteryView\(mysteryResp\);/);
        expect(dash).toMatch(/mystery=\{mystery\}/);
        const checkin = home.indexOf("<CheckinCard");
        const box = home.indexOf("<MysteryBoxCard");
        const quest = home.indexOf("<QuestCard");
        expect(box).toBeGreaterThan(checkin);
        expect(quest).toBeGreaterThan(box);
        expect(home).toMatch(/\{mystery && <MysteryBoxCard view=\{mystery\} lang=\{lang\} starMode=\{starMode\} \/>\}/);
    });
});
