import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");

describe("/parent/setup page", () => {
    const page = read("../src/pages/parent/setup.astro");
    it("is parent-only, sky tone, and seeds the wizard from the family", () => {
        expect(page).toMatch(/if \(user\.role !== "parent"\) return Astro\.redirect\("\/dashboard"\);/);
        expect(page).toMatch(/tone="sky"/);
        expect(page).toMatch(/const kidRows = kidRowsFromMembers\(family\?\.members/);
        expect(page).toMatch(/data-kids=\{JSON\.stringify\(kidRows\)\}/);
        expect(page).toMatch(/data-join-code=/);
        expect(page).toMatch(/data-modules=\{JSON\.stringify\(family\?\.enabled_modules \?\? null\)\}/);
    });
    it("has four steps and copy from the lib only", () => {
        for (const s of ["1", "2", "3", "4"]) expect(page).toContain(`data-step="${s}"`);
        expect(page).toContain("SETUP_COPY");
        expect(page).not.toMatch(/lang === "es" \? "/);  // no inline copy on this page
    });
    it("drafts through the proxied route and creates through the shared loop", () => {
        expect(page).toMatch(/fetch\("\/api\/families\/onboarding\/setup-draft"/);
        expect(page).toMatch(/await createAll\(review, lang, post, \(i, n\) =>/);
        expect(page).toMatch(/registerBody\(/);
        expect(page).toMatch(/fetch\("\/api\/auth\/register"/);
        expect(page).toMatch(/modulesBodyWithoutGigs\(/);
        expect(page).toMatch(/fetch\("\/api\/families\/me", \{\s*method: "PATCH"/);
        expect(page).toMatch(/jarvisPrefill\(/);
        expect(page).toMatch(/\/parent\/jarvis\?q=/);
        expect(page).toMatch(/if \(row\.error\) \{[\s\S]*?err\.textContent = row\.error;/);
        expect(existsSync(path("../src/pages/api/families/onboarding/setup-draft.ts"))).toBe(true);
        expect(existsSync(path("../src/pages/api/auth/register.ts"))).toBe(true);
        expect(existsSync(path("../src/pages/api/gigs/[...path].ts"))).toBe(true);
        expect(existsSync(path("../src/pages/api/rewards/[...path].ts"))).toBe(true);
    });
    it("asks before leaving the review through a sheet, never a native dialog", () => {
        expect(page).toMatch(/confirmSheet\(/);
        expect(page).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(page).not.toMatch(/innerHTML/);
        expect(page).not.toMatch(/<h1[^>]*>[^<]*[\u{1F300}-\u{1FAFF}]/u);
        expect(page).toContain("browsePacks");
        expect(page).toMatch(/href="\/parent\/starter-packs"/);
    });
    it("proxy is POST-only and forwards the cookie token", () => {
        const proxy = read("../src/pages/api/families/onboarding/setup-draft.ts");
        expect(proxy).toMatch(/export const POST: APIRoute/);
        expect(proxy).not.toMatch(/export const (GET|PUT|DELETE|PATCH)/);
        expect(proxy).toMatch(/\/api\/families\/onboarding\/setup-draft`/);
        expect(proxy).toMatch(/Authorization: `Bearer \$\{token\}`/);
    });
});
describe("SetupCard entry", () => {
    const card = read("../src/components/home/SetupCard.astro");
    it("points the main setup link at the wizard, both languages", () => {
        expect(card).toMatch(/href="\/parent\/setup"/);
        expect(card).not.toMatch(/href="\/parent\/starter-packs"/);
        expect(card).toContain("Configura tu familia en 2 minutos");
        expect(card).toContain("Set up your family in 2 minutes");
    });
});
