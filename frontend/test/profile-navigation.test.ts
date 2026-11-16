/**
 * Profile switcher (UX-E4) navigation guards, read from source (the handlers
 * are inline page scripts with no pure seam):
 * - I4: after share / switch / return the previous person's page must not be
 *   one Back tap away. Each navigation REPLACES the history entry, and Layout
 *   reloads any page restored from the back-forward cache.
 * - I3: the password prompt is never wired to the browser's saved password,
 *   and the field is emptied whenever the sheet closes.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

describe("I4: profile navigations replace history", () => {
    const cases: Array<[string, string]> = [
        ["pages/parent/settings/family.astro", "/profiles"], // share
        ["pages/profiles.astro", "/dashboard"], // switch
        ["components/MoreSheet.astro", "/parent"], // return
    ];
    for (const [file, dest] of cases) {
        it(`${file} goes to ${dest} with location.replace`, () => {
            const s = src(file);
            expect(s).toContain(`location.replace("${dest}")`);
            expect(s).not.toMatch(new RegExp(`location\\.href\\s*=\\s*"${dest}"`));
        });
    }
    it("the picker sends an expired home session to /login (I1)", () => {
        const s = src("pages/profiles.astro");
        expect(s).toContain("switchFailureAction(");
        expect(s).not.toMatch(/location\.href\s*=/);
    });
    it("Layout reloads a page restored from the back-forward cache", () => {
        const s = src("layouts/Layout.astro");
        expect(s).toMatch(/addEventListener\(\s*["']pageshow["']/);
        expect(s).toMatch(/\.persisted\)\s*location\.reload\(\)/);
    });
});

describe("I3: the app dialog's password field", () => {
    const s = src("components/ui/AppDialog.astro");
    it("takes its input attributes from promptInputAttrs, never current-password", () => {
        expect(s).toContain("promptInputAttrs(");
        expect(s).not.toContain("current-password");
    });
    it("empties the field whenever the sheet settles (submit, cancel, Esc, backdrop, close)", () => {
        const finish = s.slice(s.indexOf("const finish ="), s.indexOf("const validate ="));
        expect(finish).toMatch(/input\.value\s*=\s*""/);
    });
});
