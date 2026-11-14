import { describe, expect, it } from "vitest";
import {
    acceptErrorMessage,
    acceptLabel,
    announceErrorMessage,
    announceResultMessage,
    pendingNames,
    rulesLines,
    shouldSkipRulesSheet,
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
    it("pins every rule line (ES)", () => {
        const l = rulesLines(rules, "es");
        expect(l).toContain("Hora madrugadora: termina tus tareas antes de las 10:00.");
        expect(l).toContain("Hora de corte: a las 21:00 tus tareas abiertas quedan para tomar y no cuentan como hechas.");
        expect(l).toContain("Para tomar: hasta las 23:00, cualquier miembro de la familia puede tomar una tarea que quedó abierta.");
        expect(l).toContain("Pago semanal: con menos de 55 % de las tareas de la semana, sin pago base; de 55 a 99 %, cada tarea completada paga.");
        expect(l).toContain("Bono semanal: con 100 % terminado, el bono depende de cuántas se hicieron antes de las 10:00. 70 % o más temprano: +3 %. 85 % o más temprano: +8 %.");
        expect(l).toContain("Bono por tarea: +25 % de puntos extra en una tarea completada antes de las 10:00.");
        expect(l).toContain("Recordatorios: los adolescentes reciben un aviso a las 09:00 y otro a las 09:45.");
        expect(l).toContain("Premio de racha: $450 MXN por cada 3.ª semana madrugadora seguida.");
        expect(l).toHaveLength(8);
    });
    it("pins every rule line (EN)", () => {
        const l = rulesLines(rules, "en");
        expect(l).toContain("Early deadline: finish your chores before 10:00.");
        expect(l).toContain("Evening cutoff: at 21:00 your open chores go up for grabs and do not count as done.");
        expect(l).toContain("Up for grabs: until 23:00, any family member can take a chore that was left open.");
        expect(l).toContain("Weekly pay: under 55% of the week's chores done, no base pay; from 55% to 99%, each completed chore pays.");
        expect(l).toContain("Weekly bonus: at 100% done, the bonus depends on the share finished before 10:00. 70% or more early: +3%. 85% or more early: +8%.");
        expect(l).toContain("Per-chore bonus: +25% extra points on a chore completed before 10:00.");
        expect(l).toContain("Reminders: teens get a nudge at 09:00 and again at 09:45.");
        expect(l).toContain("Streak prize: $450 MXN for every 3rd consecutive early week.");
        expect(l).toHaveLength(8);
    });
    it("no default leakage", () => {
        for (const lang of ["es", "en"] as const) {
            const text = rulesLines(rules, lang).join("\n");
            for (const bad of ["11:00", "20:30", "$380", "undefined", "NaN"]) expect(text).not.toContain(bad);
        }
    });
    it("empty or missing tiers drops the bonus line cleanly", () => {
        for (const bt of [[], undefined as any]) {
            for (const lang of ["es", "en"] as const) {
                const l = rulesLines({ ...rules, bonus_tiers: bt }, lang);
                expect(l).toHaveLength(7);
                expect(l.join("\n")).not.toMatch(/\.\s*\./);
                expect(l.join("\n")).not.toMatch(/Weekly bonus|Bono semanal/);
            }
        }
    });
    it("pesos: integer division, floor", () => {
        const at = (c: number) => rulesLines({ ...rules, streak_cents: c }, "es").at(-1);
        expect(at(38000)).toContain("$380 MXN");
        expect(at(50000)).toContain("$500 MXN");
        expect(at(38050)).toContain("$380 MXN"); // 38050 cents floors to $380, never $380.5
        expect(at(38050)).not.toContain("380.5");
    });
});

describe("shouldSkipRulesSheet", () => {
    it("skips public, kiosk and root", () => {
        for (const p of ["/", "/login", "/register", "/accept-invitation", "/forgot-password", "/reset-password", "/verify-email", "/privacidad", "/terminos", "/kiosk", "/kiosk/abc"]) {
            expect(shouldSkipRulesSheet(p), p).toBe(true);
        }
    });
    it("does not skip app pages", () => {
        for (const p of ["/dashboard", "/parent", "/parent/settings/family", "/budget", "/loginx-not", "/kioskette"]) {
            expect(shouldSkipRulesSheet(p), p).toBe(false);
        }
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
