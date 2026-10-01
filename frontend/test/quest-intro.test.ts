import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = readFileSync(fileURLToPath(new URL("../src/pages/parent/index.astro", import.meta.url)), "utf8");

// The card's markup: from its render guard to the <ParentHub that follows it.
const cardStart = src.search(/\{\s*family\s*&&\s*family\.quest_bonus_points\s*==\s*null\s*&&/);
const card = cardStart === -1 ? "" : src.slice(cardStart, src.indexOf("<ParentHub", cardStart));

// The card's own <script> block (the one that defines questIntroDecide).
const script = src.match(/<script>(?:(?!<\/script>)[\s\S])*?questIntroDecide[\s\S]*?<\/script>/)?.[0] ?? "";

describe("parent hub — one-time weekly quest opt-in card (UX-D3)", () => {
    it("is rendered only while the family has not decided (bonus is null)", () => {
        expect(cardStart).toBeGreaterThan(-1);
        expect(card).toMatch(/id="quest-intro-banner"/);
    });
    it("sits after the AI-consent banner and before the hub", () => {
        const aiIdx = src.indexOf('id="ai-consent-banner"');
        const hubIdx = src.indexOf("<ParentHub");
        expect(aiIdx).toBeGreaterThan(-1);
        expect(cardStart).toBeGreaterThan(aiIdx);
        expect(cardStart).toBeLessThan(hubIdx);
    });
    it("has a heading and body in both languages, with no emoji in the heading", () => {
        const heading = card.match(/<h2[\s\S]*?<\/h2>/)?.[0] ?? "";
        expect(heading).toContain("Nuevo: misiones semanales");
        expect(heading).toContain("New: weekly quests");
        expect(heading).not.toMatch(/\p{Extended_Pictographic}/u);
        expect(card).toContain("Cada niño recibe una meta personal por semana y gana un bono de puntos al lograrla.");
        expect(card).toContain("Each kid gets one personal goal per week and earns a points bonus for reaching it.");
    });
    it("links to the quest section of family settings to choose another bonus", () => {
        const link = card.match(/<a\b[^>]*href="\/parent\/settings\/family#quest-section"[^>]*>[\s\S]*?<\/a>/)?.[0] ?? "";
        expect(link).not.toBe("");
        expect(link).toContain("Elegir otro bono");
        expect(link).toContain("Choose another bonus");
    });
    it("has both buttons, in both languages", () => {
        const on = card.match(/<button[^>]*id="quest-intro-on"[\s\S]*?<\/button>/)?.[0] ?? "";
        const off = card.match(/<button[^>]*id="quest-intro-off"[\s\S]*?<\/button>/)?.[0] ?? "";
        expect(on).toMatch(/buttonClass\("secondary", "sm"\)/);
        expect(on).toContain("Activar (+20 puntos)");
        expect(on).toContain("Turn on (+20 points)");
        expect(off).toContain("Ahora no");
        expect(off).toContain("Not now");
    });
    it("PATCHes the family's quest bonus: 20 to turn on, 0 for not now", () => {
        expect(script).not.toBe("");
        expect(script).toMatch(/fetch\(\s*"\/api\/families\/me"/);
        expect(script).toMatch(/method:\s*"PATCH"/);
        expect(script).toMatch(/JSON\.stringify\(\{\s*quest_bonus_points:\s*points\s*\}\)/);
        expect(script).toMatch(/getElementById\("quest-intro-on"\)\?\.addEventListener\("click",\s*\(\)\s*=>\s*questIntroDecide\(20\)\)/);
        expect(script).toMatch(/getElementById\("quest-intro-off"\)\?\.addEventListener\("click",\s*\(\)\s*=>\s*questIntroDecide\(0\)\)/);
    });
    it("removes the card only when the save succeeded", () => {
        expect(script).toMatch(/if \(r\.ok\) document\.getElementById\("quest-intro-banner"\)\?\.remove\(\);/);
        expect(script.match(/quest-intro-banner/g) ?? []).toHaveLength(1);
    });
});
