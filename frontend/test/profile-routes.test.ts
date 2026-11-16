/**
 * Profile switcher (UX-E4) Astro routes, called directly with fake cookies
 * and a mocked backend fetch: which cookies each route sets and clears is the
 * security-relevant part, and none of it had a test before (review I5).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST as logout } from "../src/pages/api/auth/logout";
import { POST as share } from "../src/pages/api/auth/profile/share";
import { GET as list } from "../src/pages/api/auth/profile/list";
import { POST as switchProfile } from "../src/pages/api/auth/profile/switch";

const cookies = (vals: Record<string, string>) => ({
    get: (k: string) => (k in vals ? { value: vals[k] } : undefined),
    has: (k: string) => k in vals,
});

const backend = (status: number, body: unknown) =>
    vi.fn(async (_url: string, _init?: RequestInit) =>
        new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
    );

const post = (path: string, body?: unknown) =>
    new Request(`http://localhost${path}`, {
        method: "POST",
        headers: body !== undefined ? { "content-type": "application/json" } : {},
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });

const setCookies = (res: Response) => res.headers.getSetCookie();
const named = (cs: string[], name: string) => cs.filter((c) => c.startsWith(`${name}=`));
const isClear = (c: string) => /Max-Age=0(;|$)/.test(c);
const sets = (cs: string[], name: string) => named(cs, name).filter((c) => !isClear(c));
const clears = (cs: string[], name: string) => named(cs, name).filter(isClear);

afterEach(() => vi.unstubAllGlobals());

describe("POST /api/auth/logout", () => {
    it("a parent logout (no ftm_sw) clears ftm_home and ftm_shared and goes to /login", async () => {
        vi.stubGlobal("fetch", backend(200, {}));
        const res = await logout({ cookies: cookies({ access_token: "a", refresh_token: "r" }) } as any);
        expect(res.status).toBe(302);
        expect(res.headers.get("Location")).toBe("/login");
        const cs = setCookies(res);
        expect(clears(cs, "ftm_home").length).toBe(2);
        expect(clears(cs, "ftm_home").every((c) => c.includes("Path=/api/auth/profile"))).toBe(true);
        expect(clears(cs, "ftm_shared").length).toBe(2);
        expect(clears(cs, "access_token").length).toBeGreaterThan(0);
        expect(clears(cs, "refresh_token").length).toBeGreaterThan(0);
    });

    it("a switched (kid) logout keeps ftm_home and ftm_shared and goes back to /profiles", async () => {
        vi.stubGlobal("fetch", backend(200, {}));
        const res = await logout({
            cookies: cookies({ access_token: "a", refresh_token: "r", ftm_sw: "1" }),
        } as any);
        expect(res.status).toBe(302);
        expect(res.headers.get("Location")).toBe("/profiles");
        const cs = setCookies(res);
        expect(named(cs, "ftm_home")).toEqual([]);
        expect(named(cs, "ftm_shared")).toEqual([]);
        expect(clears(cs, "access_token").length).toBeGreaterThan(0);
        expect(clears(cs, "refresh_token").length).toBeGreaterThan(0);
        expect(clears(cs, "ftm_sw").length).toBe(2);
    });
});

describe("POST /api/auth/profile/share", () => {
    it("trades the parent's ACCESS token for a home token, sets ftm_home + ftm_shared, clears the session", async () => {
        const fetchMock = backend(200, { home_token: "home-tok" });
        vi.stubGlobal("fetch", fetchMock);
        const res = await share({
            request: post("/api/auth/profile/share"),
            cookies: cookies({
                access_token: "parent-access",
                refresh_token: "parent-refresh",
                ui_role: "parent",
                ftm_sw: "1",
            }),
        } as any);
        expect(res.status).toBe(200);

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(String(url)).toMatch(/\/api\/auth\/profile\/share$/);
        expect(init?.method).toBe("POST");
        expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer parent-access");

        const cs = setCookies(res);
        const home = sets(cs, "ftm_home");
        expect(home.length).toBe(1);
        expect(home[0]).toContain("ftm_home=home-tok");
        expect(home[0]).toContain("HttpOnly");
        expect(home[0]).toContain("Path=/api/auth/profile");
        const hint = sets(cs, "ftm_shared");
        expect(hint.length).toBe(1);
        expect(hint[0]).toContain("ftm_shared=1");
        expect(hint[0]).not.toContain("HttpOnly");
        for (const n of ["access_token", "refresh_token", "ui_role", "ftm_sw"]) {
            expect(clears(cs, n).length, n).toBeGreaterThan(0);
            expect(sets(cs, n), n).toEqual([]);
        }
        // C1: the parent's refresh token is never copied anywhere.
        expect(cs.some((c) => c.includes("parent-refresh"))).toBe(false);
    });

    it("401 without an access cookie, and never calls the backend", async () => {
        const fetchMock = backend(200, { home_token: "home-tok" });
        vi.stubGlobal("fetch", fetchMock);
        const res = await share({
            request: post("/api/auth/profile/share"),
            cookies: cookies({ refresh_token: "parent-refresh" }),
        } as any);
        expect(res.status).toBe(401);
        expect(fetchMock).not.toHaveBeenCalled();
        expect(setCookies(res)).toEqual([]);
    });

    for (const status of [401, 403]) {
        it(`backend ${status} passes through and sets nothing`, async () => {
            vi.stubGlobal("fetch", backend(status, { detail: "nope" }));
            const res = await share({
                request: post("/api/auth/profile/share"),
                cookies: cookies({ access_token: "a", refresh_token: "parent-refresh" }),
            } as any);
            expect(res.status).toBe(status);
            expect(setCookies(res)).toEqual([]);
        });
    }

    it("a 200 without a home token is an error, not a half-shared device", async () => {
        vi.stubGlobal("fetch", backend(200, {}));
        const res = await share({
            request: post("/api/auth/profile/share"),
            cookies: cookies({ access_token: "a" }),
        } as any);
        expect(res.status).toBe(500);
        expect(setCookies(res)).toEqual([]);
    });
});

describe("profile list/switch renew the home cookie from home_token and renew ftm_shared", () => {
    it("list", async () => {
        const fetchMock = backend(200, { profiles: [], home_token: "rotated" });
        vi.stubGlobal("fetch", fetchMock);
        const res = await list({
            request: new Request("http://localhost/api/auth/profile/list"),
            cookies: cookies({ ftm_home: "old-home" }),
        } as any);
        expect(res.status).toBe(200);
        expect((fetchMock.mock.calls[0][1]?.headers as Record<string, string>).Authorization).toBe("Bearer old-home");
        const cs = setCookies(res);
        expect(sets(cs, "ftm_home")[0]).toContain("ftm_home=rotated");
        expect(sets(cs, "ftm_shared").length).toBe(1);
        expect(await res.json()).toEqual({ success: true, profiles: [] });
    });

    it("switch", async () => {
        vi.stubGlobal(
            "fetch",
            backend(200, {
                access_token: "kid-a",
                refresh_token: "kid-r",
                user: { role: "child" },
                switched: true,
                home_token: "rotated",
            }),
        );
        const res = await switchProfile({
            request: post("/api/auth/profile/switch", { user_id: "u1", pin: "1234" }),
            cookies: cookies({ ftm_home: "old-home" }),
        } as any);
        expect(res.status).toBe(200);
        const cs = setCookies(res);
        expect(sets(cs, "ftm_home")[0]).toContain("ftm_home=rotated");
        expect(sets(cs, "ftm_shared").length).toBe(1);
        expect(sets(cs, "ftm_sw").length).toBe(1);
        expect(sets(cs, "refresh_token")[0]).toContain("Max-Age=7200");
    });

    it("a failed list or switch sets no cookies", async () => {
        vi.stubGlobal("fetch", backend(401, { detail: "Home session is no longer valid" }));
        const l = await list({
            request: new Request("http://localhost/api/auth/profile/list"),
            cookies: cookies({ ftm_home: "old-home" }),
        } as any);
        expect(l.status).toBe(401);
        expect(setCookies(l)).toEqual([]);
        const s = await switchProfile({
            request: post("/api/auth/profile/switch", { user_id: "u1", pin: "1234" }),
            cookies: cookies({ ftm_home: "old-home" }),
        } as any);
        expect(s.status).toBe(401);
        expect(setCookies(s)).toEqual([]);
    });
});
