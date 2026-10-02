import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const page = readFileSync(fileURLToPath(new URL("../src/pages/privacidad.astro", import.meta.url)), "utf8");

describe("privacy notice — teen check-ins", () => {
    it("is a new version", () => {
        expect(page).toContain('version: "v2 — 1 de octubre de 2026"');
        expect(page).toContain('version: "v2 — October 1, 2026"');
        expect(page).not.toContain("v1 — ");
    });
    it("says what is stored, who sees it and how to turn it off, in both languages", () => {
        expect(page).toContain("Acompañamiento de Jarvis para adolescentes");
        expect(page).toContain("solo si la madre, padre o tutor lo activa");
        expect(page).toContain("hasta 200 caracteres");
        expect(page).toContain("sin nombres");
        expect(page).toContain("Jarvis check-ins for teens");
        expect(page).toContain("only if the parent or guardian turns it on");
        expect(page).toContain("up to 200 characters");
        expect(page).toContain("without names");
    });
});
