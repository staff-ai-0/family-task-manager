import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");
const hub = read("../src/pages/parent/index.astro");
const settings = read("../src/pages/parent/settings/family.astro");

const ES = "Cuando una tarea se atrasa o la regresas, Jarvis le pregunta a tu adolescente qué pasó y le da una idea para destrabarse. El motivo que elige (y una nota corta si es un problema con la app) nos ayuda a mejorar la app; lo vemos sin nombres.";
const EN = "When a chore is late or you send it back, Jarvis asks your teen what happened and offers a way to get unstuck. The reason they pick (and a short note if it is a problem with the app) helps us improve the app; we see it without names.";

describe("parent hub — teen check-in opt-in card", () => {
    const banner = hub.match(/<div id="checkin-intro-banner"[\s\S]*?<\/div>\s*\)\}/)?.[0] ?? "";
    it("shows only to an undecided family that has a teen", () => {
        expect(hub).toMatch(/const hasTeen = \(oversightRes\.data\?\.members \?\? \[\]\)\.some\(\(k: any\) => String\(k\.role\)\.toLowerCase\(\) === "teen"\);/);
        expect(hub).toMatch(/\{family && family\.teen_checkin_enabled == null && hasTeen && \(/);
        expect(banner).not.toBe("");
    });
    it("explains what is stored and who sees it, in both languages", () => {
        expect(banner).toContain("Nuevo: Jarvis acompaña a tus adolescentes");
        expect(banner).toContain("New: Jarvis checks in with your teens");
        expect(banner).toContain(ES);
        expect(banner).toContain(EN);
    });
    it("has both answers and saves them as true / false", () => {
        expect(banner).toMatch(/id="checkin-intro-on"/);
        expect(banner).toMatch(/id="checkin-intro-off"/);
        expect(hub).toMatch(/JSON\.stringify\(\{ teen_checkin_enabled: on \}\)/);
        expect(hub).toMatch(/getElementById\("checkin-intro-on"\)\?\.addEventListener\("click", \(\) => checkinIntroDecide\(true\)\)/);
        expect(hub).toMatch(/getElementById\("checkin-intro-off"\)\?\.addEventListener\("click", \(\) => checkinIntroDecide\(false\)\)/);
        expect(hub).toMatch(/if \(r\.ok\) document\.getElementById\("checkin-intro-banner"\)\?\.remove\(\);/);
    });
});

describe("family settings — teen check-in checkbox", () => {
    const section = settings.match(/<section[^>]*id="teen-checkin-section"[\s\S]*?<\/section>/)?.[0] ?? "";
    it("sits right under the smart reminders section", () => {
        expect(section).not.toBe("");
        expect(settings.indexOf('id="smart-reminders-section"')).toBeLessThan(settings.indexOf('id="teen-checkin-section"'));
        expect(settings.indexOf('id="teen-checkin-section"')).toBeLessThan(settings.indexOf('id="modules-section"'));
    });
    it("is checked only when the family said yes", () => {
        const input = section.match(/<input[^>]*id="teen-checkin"[^>]*>/s)?.[0] ?? "";
        expect(input).toMatch(/type="checkbox"/);
        expect(input).toMatch(/checked=\{family\?\.teen_checkin_enabled === true\}/);
    });
    it("carries the same explanation as the hub card", () => {
        expect(section).toContain("Jarvis acompaña a tus adolescentes");
        expect(section).toContain("Jarvis checks in with your teens");
        expect(section).toContain(ES);
        expect(section).toContain(EN);
    });
    it("saves at once, toasts, and reverts on failure", () => {
        expect(settings).toMatch(/teen_checkin_enabled: input\.checked/);
        const script = settings.slice(settings.indexOf('getElementById("teen-checkin")'));
        expect(script).toMatch(/addEventListener\("change"/);
        expect(script).toMatch(/showToast\(/);
        expect(script).toMatch(/input\.checked = !input\.checked/);
    });
});
