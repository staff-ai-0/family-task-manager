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
        expect(page).toContain("Jarvis check-ins for teens");
        expect(page).toContain("only if the parent or guardian turns it on");
        expect(page).toContain("up to 200 characters");
    });
    it("matches what the code does: linked to the teen, notes read one by one, a floor, and what off means", () => {
        for (const phrase of [
            "ligado al perfil del adolescente",
            "si respondió o eligió «ahora no»",
            "lee las notas una por una, sin el nombre del adolescente ni de la familia",
            "al menos cinco familias",
            "dejamos de preguntar y de usar las respuestas ya guardadas",
            "linked to the teen's profile",
            "whether they answered or chose “not now”",
            "reads the notes one by one, without the teen's or the family's name",
            "at least five families",
            "we stop asking and stop using the answers already stored",
        ]) {
            expect(page).toContain(phrase);
        }
        // The first draft claimed everything was "aggregate"; notes are not.
        expect(page).not.toContain("de forma agregada y sin nombres para mejorar");
        expect(page).not.toContain("in aggregate and without names to improve");
    });
});
