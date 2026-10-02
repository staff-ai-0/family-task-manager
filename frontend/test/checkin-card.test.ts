import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");
const card = read("../src/components/home/CheckinCard.astro");
const home = read("../src/components/home/KidHome.astro");
const dash = read("../src/pages/dashboard.astro");

describe("CheckinCard", () => {
    it("has the three states, toggled with the hidden attribute", () => {
        for (const state of ["data-checkin-offer", "data-checkin-reasons", "data-checkin-help"]) {
            expect(card).toContain(state);
        }
        expect(card).toMatch(/data-checkin-reasons hidden/);
        expect(card).toMatch(/data-checkin-help hidden/);
        expect(card).not.toMatch(/class="[^"]*(?<![\w-])hidden(?![\w-])/);
    });
    it("asks in the teen's language and offers a way out (copy from the shared list)", () => {
        expect(card).toMatch(/const c = CHECKIN_COPY;/);
        for (const key of ["question", "yes", "notNow", "pick", "send", "chat"]) {
            expect(card).toContain(`{c.${key}[lang]}`);
        }
        expect(card).toMatch(/data-checkin-yes/);
        expect(card).toMatch(/data-checkin-no\b/);
    });
    it("renders one chip per reason from the shared list", () => {
        expect(card).toMatch(/REASONS\.map\(/);
        expect(card).toMatch(/data-checkin-reason=\{r\}/);
    });
    it("tells the teen where a note goes, and caps it", () => {
        expect(card).toContain("{c.noteHint[lang]}");
        expect(card).toMatch(/maxlength=\{NOTE_MAX\}/);
    });
    it("never promises that parents cannot see the answer", () => {
        expect(card).not.toMatch(/tus pap[aá]s no|your parents (won't|will not|can't|cannot)/i);
    });
    it("saves through the proxied Jarvis route, with a toast on failure", () => {
        expect(card).toMatch(/fetch\("\/api\/jarvis\/checkin"/);
        expect(card).toMatch(/method: "POST"/);
        expect(card).toMatch(/showToast\(/);
        expect(existsSync(path("../src/pages/api/jarvis/[...path].ts"))).toBe(true);
    });
    it("shows the chat button only when the plan has it", () => {
        expect(card).toMatch(/data-checkin-chat/);
        expect(card).toMatch(/hidden=\{!checkin\.canChat\}|canChat/);
        expect(card).toMatch(/chatHref\(/);
    });
    it("uses no native dialog and no emoji in a heading 1", () => {
        expect(card).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(card).not.toMatch(/<h1/);
    });
});

describe("wiring", () => {
    it("the dashboard asks for an offer for teens only", () => {
        expect(dash).toMatch(/user\.role === "teen" \? apiFetch<any>\("\/api\/jarvis\/checkin", \{ token \}\) : none/);
        expect(dash).toMatch(/checkinView\(/);
        expect(dash).toMatch(/checkin=\{checkin\}/);
    });
    it("KidHome shows the card under the task deck, above the quest", () => {
        const deck = home.indexOf("<TaskDeck");
        const cardAt = home.indexOf("<CheckinCard");
        const quest = home.indexOf("<QuestCard");
        expect(deck).toBeGreaterThan(-1);
        expect(cardAt).toBeGreaterThan(deck);
        expect(quest).toBeGreaterThan(cardAt);
        expect(home).toMatch(/\{checkin && <CheckinCard checkin=\{checkin\} lang=\{lang\} \/>\}/);
    });
});
