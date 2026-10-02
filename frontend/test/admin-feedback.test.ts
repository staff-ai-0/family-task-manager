import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");
const page = read("../src/pages/admin/feedback.astro");
const shell = read("../src/components/ui/AdminShell.astro");

describe("operator console — teen check-ins", () => {
    it("is in the console navigation", () => {
        expect(shell).toMatch(/\{ key: "feedback", href: "\/admin\/feedback", label: "Teen check-ins" \}/);
        expect(shell).toMatch(/"audit" \| "feedback"/);
        expect(page).toMatch(/<AdminShell title="Teen check-ins" active="feedback">/);
    });
    it("reads the summary on the server with the operator's token", () => {
        expect(page).toMatch(/apiFetch<any>\(`\/api\/admin\/teen-checkins\?\$\{params\}`, \{ token \}\)/);
        expect(page).toMatch(/if \(!token\) return Astro\.redirect\("\/login"\);/);
        expect(page).not.toMatch(/<script/);
    });
    it("offers the two windows and keeps the choice when paging notes", () => {
        expect(page).toMatch(/const days = Astro\.url\.searchParams\.get\("days"\) === "90" \? 90 : 30;/);
        expect(page).toContain("/admin/feedback?days=30");
        expect(page).toContain("/admin/feedback?days=90");
        expect(page).toMatch(/new URLSearchParams\(Astro\.url\.searchParams\)/);
    });
    it("shows every count the summary has", () => {
        for (const field of ["answered", "dismissed", "families", "teens", "done_afterwards", "by_reason", "by_kind", "by_trigger", "notes"]) {
            expect(page).toContain(field);
        }
    });
    it("tells a failed load apart from an empty one", () => {
        expect(page).toMatch(/\{!result && \(/);
        expect(page).toContain("Could not load");
        expect(page).toContain("No notes in this window.");
    });
    it("says so when notes are withheld for lack of families", () => {
        expect(page).toMatch(/\{result\.notes\.withheld && \(/);
        expect(page).toContain("Notes are shown once at least");
        expect(page).toContain("result.min_families_for_notes");
        expect(page).toMatch(/\{!result\.notes\.withheld && result\.notes\.items\.length === 0 && \(/);
    });
    it("never reaches for an identity", () => {
        expect(page).not.toMatch(/family_id|user_id|assignment_id|\.name\b|\.email\b|\/admin\/families\//);
    });
});
