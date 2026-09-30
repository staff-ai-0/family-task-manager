import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { RULE_IDS, scanVisual, type RuleId } from "./support/visual-scan";

const SRC = fileURLToPath(new URL("../src", import.meta.url));

/** Out of B3 scope (spec "Not in B3"). A trailing "/" exempts a directory. */
const EXEMPT: { path: string; why: string }[] = [
    { path: "pages/login.astro", why: "auth page, no app header" },
    { path: "pages/register.astro", why: "auth page, no app header" },
    { path: "pages/forgot-password.astro", why: "auth page, no app header" },
    { path: "pages/reset-password.astro", why: "auth page, no app header" },
    { path: "pages/verify-email.astro", why: "auth page, no app header" },
    { path: "pages/accept-invitation.astro", why: "auth page, no app header" },
    { path: "pages/index.astro", why: "public landing page" },
    { path: "pages/tdah.astro", why: "public landing page" },
    { path: "pages/privacidad.astro", why: "legal page" },
    { path: "pages/terminos.astro", why: "legal page" },
    { path: "pages/404.astro", why: "error page" },
    { path: "pages/500.astro", why: "error page" },
    { path: "pages/kiosk.astro", why: "shared-device full-screen board" },
    { path: "pages/admin/", why: "operator console, own neutral styling" },
    { path: "components/ui/AdminShell.astro", why: "operator console shell" },
    { path: "components/GuideShell.astro", why: "help-guide document styling" },
];

/** These apply everywhere, exemptions included. */
const GLOBAL_RULES: RuleId[] = ["dark-theme", "header-class-prop"];

/**
 * Remaining offenders per rule while B3 lands. The guard asserts EXACT
 * equality: a new offender fails, and so does a fix that forgets to lower
 * its number. Every entry reaches 0; the last task deletes this map.
 */
const ALLOWANCE: Record<RuleId, number> = {
    "header-gradient": 0,
    "light-text-in-header": 0,
    "white-on-brand-fill": 36,
    "deep-text": 0,
    "faint-text": 0,
    "h1-emoji": 0,
    "dark-theme": 0,
    "header-class-prop": 0,
};

function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return walk(path);
        return /\.(astro|ts|css)$/.test(name) ? [path] : [];
    });
}

const isExempt = (file: string) =>
    EXEMPT.some((e) => (e.path.endsWith("/") ? file.startsWith(e.path) : file === e.path));

const hits = walk(SRC).flatMap((abs) => {
    const file = relative(SRC, abs).split(sep).join("/");
    return scanVisual(readFileSync(abs, "utf8"))
        .filter((h) => GLOBAL_RULES.includes(h.rule) || !isExempt(file))
        .map((h) => `${file}:${h.line} ${h.match}`.concat(` [${h.rule}]`));
});

describe("visual consistency guard (UX-B3)", () => {
    it.each([...RULE_IDS])("%s: offenders match the allowance", (rule) => {
        const offenders = hits.filter((h) => h.endsWith(`[${rule}]`));
        expect(offenders.length, `${rule} offenders:\n${offenders.join("\n")}`).toBe(ALLOWANCE[rule]);
    });

    it("every exemption still exists (no stale entries)", () => {
        const files = walk(SRC).map((abs) => relative(SRC, abs).split(sep).join("/"));
        for (const e of EXEMPT) {
            expect(files.some((f) => (e.path.endsWith("/") ? f.startsWith(e.path) : f === e.path)), e.path).toBe(true);
        }
    });
});
