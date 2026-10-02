import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = readFileSync(fileURLToPath(new URL("../src/pages/parent/settings/family.astro", import.meta.url)), "utf8");
const section = src.match(/<section[^>]*id="smart-reminders-section"[\s\S]*?<\/section>/)?.[0] ?? "";

describe("family settings — smart reminders switch (UX-D4a)", () => {
    it("sits right under the weekly quest section", () => {
        expect(section).not.toBe("");
        const quest = src.indexOf('id="quest-section"');
        const smart = src.indexOf('id="smart-reminders-section"');
        const modules = src.indexOf('id="modules-section"');
        expect(quest).toBeLessThan(smart);
        expect(smart).toBeLessThan(modules);
    });
    it("is a checkbox that is on unless the family switched it off", () => {
        const input = section.match(/<input[^>]*id="smart-reminders"[^>]*>/s)?.[0] ?? "";
        expect(input).toMatch(/type="checkbox"/);
        expect(input).toMatch(/checked=\{family\?\.smart_reminders_enabled !== false\}/);
    });
    it("explains what it does, in both languages", () => {
        expect(section).toContain("Recordatorios inteligentes para los hijos");
        expect(section).toContain("Smart reminders for kids");
        expect(section).toContain("Por la tarde (desde las 6:00 pm) avisamos a tus hijos solo si su racha está en riesgo o les falta un paso para su misión de la semana. Máximo un aviso al día.");
        expect(section).toContain("In the evening (from 6:00 pm) we tell your kids only when their streak is at risk or they are one step from their weekly quest. One reminder a day at most.");
    });
    it("saves at once through the family update, toasts, and reverts on failure", () => {
        expect(src).toMatch(/smart_reminders_enabled: input\.checked/);
        const script = src.slice(src.indexOf('getElementById("smart-reminders")'));
        expect(script).toMatch(/addEventListener\("change"/);
        expect(script).toMatch(/showToast\(/);
        expect(script).toMatch(/input\.checked = !input\.checked/);
        expect(script).toMatch(/input\.disabled = true/);
        expect(script).toMatch(/input\.disabled = false/);
    });
    it("uses no native dialog", () => {
        expect(section).not.toMatch(/\b(alert|confirm|prompt)\(/);
    });
});
