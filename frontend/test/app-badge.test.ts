import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import { applyAppBadge, badgeAction, refreshAppBadge } from "../src/lib/appBadge";

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");
const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const fakeNav = () => ({
    setAppBadge: vi.fn(async (_n?: number) => {}),
    clearAppBadge: vi.fn(async () => {}),
});

describe("badgeAction", () => {
    it("sets a positive whole number", () => {
        expect(badgeAction(3)).toEqual({ op: "set", n: 3 });
        expect(badgeAction(1)).toEqual({ op: "set", n: 1 });
    });
    it("clears on zero, negatives, fractions and non-numbers", () => {
        for (const v of [0, -2, 1.5, NaN, null, undefined, "3", {}]) {
            expect(badgeAction(v)).toEqual({ op: "clear" });
        }
    });
});

describe("applyAppBadge", () => {
    it("sets or clears through the Badging API", async () => {
        const nav = fakeNav();
        await applyAppBadge(4, nav);
        expect(nav.setAppBadge).toHaveBeenCalledWith(4);
        await applyAppBadge(0, nav);
        expect(nav.clearAppBadge).toHaveBeenCalledTimes(1);
    });
    it("does nothing on a browser without the API, and swallows a rejection", async () => {
        await expect(applyAppBadge(4, {})).resolves.toBeUndefined();
        const nav = { setAppBadge: vi.fn(async () => { throw new Error("denied"); }) };
        await expect(applyAppBadge(4, nav)).resolves.toBeUndefined();
    });
});

describe("refreshAppBadge", () => {
    it("asks the API and applies the count", async () => {
        const nav = fakeNav();
        const fetchImpl = vi.fn(async () => json(200, { count: 5 }));
        await refreshAppBadge(fetchImpl as unknown as typeof fetch, nav);
        expect(fetchImpl).toHaveBeenCalledWith("/api/notifications/waiting-count", { credentials: "same-origin" });
        expect(nav.setAppBadge).toHaveBeenCalledWith(5);
    });
    it("clears when the session is gone", async () => {
        const nav = fakeNav();
        await refreshAppBadge((async () => json(401, {})) as unknown as typeof fetch, nav);
        expect(nav.clearAppBadge).toHaveBeenCalledTimes(1);
    });
    it("leaves the number alone on a server or network error", async () => {
        const nav = fakeNav();
        await refreshAppBadge((async () => json(502, {})) as unknown as typeof fetch, nav);
        await refreshAppBadge((async () => { throw new Error("offline"); }) as unknown as typeof fetch, nav);
        expect(nav.setAppBadge).not.toHaveBeenCalled();
        expect(nav.clearAppBadge).not.toHaveBeenCalled();
    });
});

describe("wiring", () => {
    const nav = read("../src/components/BottomNav.astro");
    const layout = read("../src/layouts/Layout.astro");
    const sw = read("../public/sw.js");

    it("BottomNav renders the server count and reads one endpoint for it", () => {
        expect(nav).toMatch(/apiFetch<\{ count: number \}>\("\/api\/notifications\/waiting-count", \{ token \}\)/);
        expect(nav).toMatch(/data-waiting-count=\{waitingCount\}/);
        expect(nav).not.toContain("/api/task-assignments/pending-approvals");
        expect(nav).not.toContain("/api/gigs/claims/pending-approvals");
        expect(nav).toMatch(/badge: waitingCount \?\? 0/);
    });
    it("BottomNav leaves the icon alone when the count is unknown", () => {
        // null → Astro omits the attribute → the script finds no nav to apply.
        expect(nav).toMatch(/let waitingCount: number \| null = null;/);
        expect(nav).toMatch(/waitingCount = waiting\.data\?\.count \?\? null;/);
        expect(nav).toMatch(/querySelector<HTMLElement>\("nav\[data-waiting-count\]"\)/);
    });
    it("BottomNav applies the count on load and refreshes on the app's own events", () => {
        expect(nav).toMatch(/import \{ applyAppBadge, refreshAppBadge \} from "\.\.\/lib\/appBadge"/);
        expect(nav).toMatch(/applyAppBadge\(Number\(nav\.dataset\.waitingCount\)\)/);
        for (const ev of ["ftm:deck-completed", "ftm:deck-empty", "ftm:waiting-changed"]) {
            expect(nav).toContain(`"${ev}"`);
        }
        expect(nav).toMatch(/visibilitychange/);
    });
    it("Layout clears the number on a logged-out page", () => {
        expect(layout).toMatch(/const hasSession = Astro\.cookies\.has\("access_token"\) \|\| Astro\.cookies\.has\("refresh_token"\)/);
        const block = layout.match(/\{!hasSession && \([\s\S]*?<\/script>\s*\)\}/)?.[0] ?? "";
        expect(block).toContain("clearAppBadge");
        expect(block).toContain("is:inline");
    });
    it("the service worker sets the number from the push payload before showing it", () => {
        const handler = sw.slice(sw.indexOf("addEventListener('push'"), sw.indexOf("addEventListener('notificationclick'"));
        expect(handler).toMatch(/typeof payload\.badge === 'number'/);
        expect(handler).toContain("navigator.setAppBadge");
        expect(handler).toContain("navigator.clearAppBadge");
        expect(handler).toMatch(/Promise\.all\(work\)/);
        expect(handler).toMatch(/\.catch\(/);
    });
});
