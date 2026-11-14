import { describe, expect, it } from "vitest";
import {
    BASELINE_MAX,
    baselineCountLabel,
    cleanSuggestions,
    dueSummary,
    errorMessage,
    statusLine,
} from "../src/lib/showAndTell";

const row = (o: Partial<any> = {}) => ({
    template_id: "t1",
    title: "Lavar platos",
    baseline_count: 0,
    last_baseline_at: null,
    due: true,
    ...o,
});

describe("baselineCountLabel", () => {
    it("shows n of max in both languages", () => {
        expect(BASELINE_MAX).toBe(4);
        expect(baselineCountLabel(2, 4, "en")).toBe("2 of 4 photos");
        expect(baselineCountLabel(2, 4, "es")).toBe("2 de 4 fotos");
        expect(baselineCountLabel(1, 4, "en")).toBe("1 of 4 photos");
        expect(baselineCountLabel(0, 4, "es")).toBe("0 de 4 fotos");
    });
});

describe("dueSummary", () => {
    it("is empty when nothing is due", () => {
        expect(dueSummary([], "en")).toBe("");
        expect(dueSummary([row({ due: false })], "es")).toBe("");
    });
    it("counts only due rows, singular and plural", () => {
        expect(dueSummary([row()], "en")).toBe("1 chore needs a fresh show-and-tell");
        expect(dueSummary([row(), row({ template_id: "t2" }), row({ due: false })], "en")).toBe(
            "2 chores need a fresh show-and-tell",
        );
        expect(dueSummary([row()], "es")).toBe("1 tarea necesita un nuevo show and tell");
        expect(dueSummary([row(), row({ template_id: "t2" })], "es")).toBe(
            "2 tareas necesitan un nuevo show and tell",
        );
    });
});

describe("statusLine", () => {
    it("says no photos yet", () => {
        expect(statusLine(row(), "en")).toBe("No reference photos yet");
        expect(statusLine(row(), "es")).toBe("Aún sin fotos de referencia");
    });
    it("says last update date when present", () => {
        const r = row({ baseline_count: 2, last_baseline_at: "2026-09-05T10:00:00Z" });
        expect(statusLine(r, "en")).toContain("2026-09-05");
        expect(statusLine(r, "es")).toContain("2026-09-05");
        expect(statusLine(r, "es")).toContain("2 de 4");
    });
});

describe("errorMessage", () => {
    it("maps each known code/status in both languages", () => {
        for (const k of ["baseline_limit", 415, 413, "ai_consent_required", "upgrade_required", "ai_failed"]) {
            const es = errorMessage(k, "es");
            const en = errorMessage(k, "en");
            expect(es).not.toBe(errorMessage("zzz", "es"));
            expect(en).not.toBe(errorMessage("zzz", "en"));
            expect(es).not.toBe(en);
        }
        expect(errorMessage("baseline_limit", "en")).toContain("4");
    });
    it("falls back to a generic message", () => {
        expect(errorMessage("", "en")).toBe("Something went wrong. Try again.");
        expect(errorMessage(500, "es")).toBe("Algo salió mal. Intenta de nuevo.");
        expect(errorMessage(undefined, "en")).toBe("Something went wrong. Try again.");
    });
    it("treats a numeric-string status like the number", () => {
        expect(errorMessage("415", "en")).toBe(errorMessage(415, "en"));
    });
});

describe("cleanSuggestions", () => {
    it("trims, drops blanks/non-strings/duplicates and limits to 5", () => {
        expect(cleanSuggestions(["  a ", "", "a", 3 as any, null as any, "b"])).toEqual(["a", "b"]);
        expect(cleanSuggestions(["1", "2", "3", "4", "5", "6", "7"])).toHaveLength(5);
    });
    it("caps each tip's length", () => {
        expect(cleanSuggestions(["x".repeat(500)])[0].length).toBeLessThanOrEqual(240);
    });
    it("tolerates non-arrays", () => {
        expect(cleanSuggestions(undefined as any)).toEqual([]);
        expect(cleanSuggestions("nope" as any)).toEqual([]);
    });
});
