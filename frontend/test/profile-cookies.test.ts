import { describe, it, expect } from "vitest";
import {
    authCookies,
    homeCookie,
    clearHomeCookie,
    switchedMarker,
    clearSwitchedMarker,
    uiRoleCookie,
} from "../src/lib/auth-cookies";

/** RFC 6265 5.1.4 path-match. */
function pathMatches(cookiePath: string, requestPath: string): boolean {
    if (cookiePath === requestPath) return true;
    if (requestPath.startsWith(cookiePath)) {
        if (cookiePath.endsWith("/")) return true;
        if (requestPath.charAt(cookiePath.length) === "/") return true;
    }
    return false;
}

function attr(cookie: string, name: string): string | undefined {
    const part = cookie.split("; ").find((p) => p.toLowerCase().startsWith(name.toLowerCase() + "="));
    return part?.split("=")[1];
}

describe("ftm_home cookie", () => {
    it("is httpOnly, Lax, scoped to /api/auth/profile, 30 days", () => {
        const c = homeCookie("tok", true);
        expect(c).toContain("ftm_home=tok");
        expect(c).toContain("HttpOnly");
        expect(c).toContain("Secure");
        expect(c).toContain("SameSite=Lax");
        expect(c).toContain("Path=/api/auth/profile");
        expect(c).not.toContain("Path=/;");
        expect(attr(c, "Max-Age")).toBe(String(60 * 60 * 24 * 30));
    });

    it("path scope matches only profile routes", () => {
        const p = attr(homeCookie("t", false), "Path")!;
        expect(pathMatches(p, "/api/auth/profile/switch")).toBe(true);
        expect(pathMatches(p, "/api/auth/profile/list")).toBe(true);
        expect(pathMatches(p, "/api/auth/profile-switch")).toBe(false);
        expect(pathMatches(p, "/api/auth/me")).toBe(false);
        expect(pathMatches(p, "/api/auth/refresh")).toBe(false);
    });

    it("clear variants keep the same path", () => {
        const cs = clearHomeCookie();
        expect(cs.length).toBe(2);
        for (const c of cs) {
            expect(c).toContain("ftm_home=;");
            expect(c).toContain("Path=/api/auth/profile");
            expect(c).toContain("Max-Age=0");
        }
        expect(cs.some((c) => c.includes("Secure"))).toBe(true);
    });
});

describe("ftm_sw marker", () => {
    it("is a non-httpOnly 2h hint on Path=/", () => {
        const c = switchedMarker(true);
        expect(c).toContain("ftm_sw=1");
        expect(c).not.toContain("HttpOnly");
        expect(c).toContain("Path=/");
        expect(attr(c, "Max-Age")).toBe("7200");
        const cl = clearSwitchedMarker();
        expect(cl.length).toBe(2);
        for (const x of cl) expect(x).toContain("Max-Age=0");
    });
});

describe("uiRoleCookie", () => {
    it("lowercases the role and is empty without one", () => {
        expect(uiRoleCookie("CHILD", true)[0]).toContain("ui_role=child; Path=/");
        expect(uiRoleCookie(undefined, true)).toEqual([]);
    });
});

describe("authCookies switched", () => {
    const maxAge = (cs: string[]) => attr(cs.find((c) => c.startsWith("refresh_token="))!, "Max-Age");
    it("defaults to 30 days", () => {
        expect(maxAge(authCookies("a", "r", true))).toBe("2592000");
    });
    it("switched refresh is 2h", () => {
        expect(maxAge(authCookies("a", "r", true, true))).toBe("7200");
    });
});
