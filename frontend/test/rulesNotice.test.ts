import { describe, expect, it } from "vitest";
import {
    acceptErrorMessage,
    acceptLabel,
    announceErrorMessage,
    announceResultMessage,
    pendingNames,
    rulesLines,
    statusSummary,
} from "../src/lib/rulesNotice";

const rules = {
    version: 3,
    deadline: "10:00",
    cutoff: "21:00",
    grab_end: "23:00",
    alarm_1: "09:00",
    alarm_2: "09:45",
    streak_cents: 45000,
    chore_bonus_pct: 25,
    floor_pct: 55,
    bonus_tiers: [
        { early_pct: 70, bonus_pct: 3 },
        { early_pct: 85, bonus_pct: 8 },
    ],
};

describe("rulesLines", () => {
    for (const lang of ["es", "en"] as const) {
        it(`renders every value from the fixture (${lang})`, () => {
            const text = rulesLines(rules, lang).join("\n");
            for (const v of ["10:00", "21:00", "23:00", "09:00", "09:45", "$450", "25", "55", "70", "85", "3", "8"]) {
                expect(text).toContain(v);
            }
            expect(text).not.toContain("11:00");
            expect(text).not.toContain("20:30");
            expect(text).not.toContain("$380");
            expect(text).not.toContain("undefined");
        });
    }
    it("one line per rule, all non-empty", () => {
        const lines = rulesLines(rules, "es");
        expect(lines.length).toBeGreaterThanOrEqual(5);
        lines.forEach((l) => expect(l.trim().length).toBeGreaterThan(0));
    });
});

describe("acceptLabel", () => {
    it("exact strings", () => {
        expect(acceptLabel("es")).toBe(
            "Entiendo las reglas y las acepto; no haré reclamos futuros sobre resultados calculados con ellas.",
        );
        expect(acceptLabel("en")).toBe(
            "I understand the rules and accept them; I won't make future claims about results calculated under them.",
        );
    });
});

const rows = [
    { user_id: "1", name: "Ana", role: "parent", accepted_at: "2026-11-13T10:00:00Z" },
    { user_id: "2", name: "Leo", role: "teen", accepted_at: null },
    { user_id: "3", name: "Mia", role: "child", accepted_at: null },
    { user_id: "4", name: "Sam", role: "child", accepted_at: "2026-11-13T11:00:00Z" },
    { user_id: "5", name: "Zoe", role: "child", accepted_at: "2026-11-13T11:00:00Z" },
];

describe("status", () => {
    it("summary", () => {
        expect(statusSummary(rows, "es")).toBe("3 de 5 aceptaron");
        expect(statusSummary(rows, "en")).toBe("3 of 5 accepted");
        expect(statusSummary([], "es")).toBe("");
        expect(statusSummary([], "en")).toBe("");
    });
    it("pending names", () => {
        expect(pendingNames(rows)).toEqual(["Leo", "Mia"]);
        expect(pendingNames([])).toEqual([]);
    });
});

describe("messages", () => {
    it("accept errors", () => {
        expect(acceptErrorMessage("stale_version", "es")).toBe("Las reglas cambiaron, mira la versión nueva.");
        expect(acceptErrorMessage("stale_version", "en")).toBe("The rules changed, please read the new version.");
        for (const lang of ["es", "en"] as const) {
            expect(acceptErrorMessage("weird", lang).length).toBeGreaterThan(5);
            expect(acceptErrorMessage("", lang)).toBe(acceptErrorMessage("weird", lang));
        }
    });
    it("announce errors", () => {
        expect(announceErrorMessage("early_bird_off", "es")).toBe("Activa Madrugador para enviar las reglas.");
        expect(announceErrorMessage("announce_too_soon", "es")).toBe("Ya las enviaste hace menos de una hora.");
        for (const lang of ["es", "en"] as const) {
            for (const code of ["early_bird_off", "announce_too_soon", "other"]) {
                const m = announceErrorMessage(code, lang);
                expect(m).toBeTruthy();
                expect(m).not.toContain("undefined");
            }
            expect(announceErrorMessage("early_bird_off", lang)).not.toBe(announceErrorMessage("announce_too_soon", lang));
        }
    });
    it("announce result", () => {
        expect(announceResultMessage(4, "es")).toContain("4");
        expect(announceResultMessage(4, "en")).toContain("4");
        expect(announceResultMessage(1, "en")).not.toContain("undefined");
        expect(announceResultMessage(0, "es").length).toBeGreaterThan(0);
    });
});
