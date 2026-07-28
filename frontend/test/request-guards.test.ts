/**
 * The security-load-bearing request rules.
 *
 * Before these tests existed, `middleware.ts` held the CSRF origin check, the
 * public-route list and the admin-surface match with no unit coverage at all —
 * its only test was an e2e spec that does not run in CI. The check could have
 * been inverted, or a protected route quietly made public, and every automated
 * signal in the repo would have stayed green.
 *
 * These are deliberately written to FAIL on an inversion rather than to
 * describe the current implementation back to itself.
 */
import { describe, expect, it } from "vitest";

import {
    PUBLIC_ROUTES,
    isAdminSurface,
    isAllowedOrigin,
    isJwtExpired,
    isPublicRoute,
    moduleForPath,
    moduleRedirectTarget,
    requiresCsrfCheck,
} from "../src/lib/security/request-guards";

describe("CSRF origin check", () => {
    it("accepts a null Origin so our own server-side calls still work", () => {
        // Astro API routes call the backend server-side and send no Origin.
        // This only skips CSRF; the auth checks still run.
        expect(isAllowedOrigin(null, "family.agent-ia.mx", false)).toBe(true);
    });

    it("accepts the canonical production origin", () => {
        expect(
            isAllowedOrigin("https://family.agent-ia.mx", "family.agent-ia.mx", false),
        ).toBe(true);
    });

    it("accepts an origin matching the request Host", () => {
        expect(isAllowedOrigin("https://other.example", "other.example", false)).toBe(true);
    });

    it("REJECTS a foreign origin in production", () => {
        // The inversion guard: if this ever returns true, cross-site requests
        // can drive every state-changing API route.
        expect(
            isAllowedOrigin("https://evil.example", "family.agent-ia.mx", false),
        ).toBe(false);
    });

    it("rejects a lookalike host that merely contains the real one", () => {
        expect(
            isAllowedOrigin("https://family.agent-ia.mx.evil.example", "family.agent-ia.mx", false),
        ).toBe(false);
    });

    it("rejects a foreign origin in dev too", () => {
        expect(isAllowedOrigin("https://evil.example", "localhost:3000", true)).toBe(false);
    });

    it("accepts the usual localhost origins in dev only", () => {
        expect(isAllowedOrigin("http://localhost:3000", "localhost:3000", true)).toBe(true);
        // ...and not in production, where the host must match.
        expect(isAllowedOrigin("http://localhost:3000", "family.agent-ia.mx", false)).toBe(false);
    });
});

describe("which requests are CSRF-checked", () => {
    it("checks state-changing API calls", () => {
        for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
            expect(requiresCsrfCheck(method, "/api/budget/transactions")).toBe(true);
        }
    });

    it("does not check GETs", () => {
        expect(requiresCsrfCheck("GET", "/api/budget/transactions")).toBe(false);
    });

    it("does not check page navigations", () => {
        expect(requiresCsrfCheck("POST", "/dashboard")).toBe(false);
    });
});

describe("public routes", () => {
    it("lets the documented public pages through", () => {
        for (const path of ["/", "/login", "/register", "/help", "/privacidad"]) {
            expect(isPublicRoute(path)).toBe(true);
        }
    });

    it("keeps authenticated surfaces private", () => {
        // The inversion guard for the other direction: a protected route
        // silently becoming public is the quiet version of this bug.
        for (const path of [
            "/dashboard",
            "/parent",
            "/budget",
            "/api/budget/transactions",
            "/api/auth/me",
            "/admin",
        ]) {
            expect(isPublicRoute(path)).toBe(false);
        }
    });

    it("matches exactly, not by prefix", () => {
        // "/login" is public; "/login-secrets" must not inherit that.
        expect(isPublicRoute("/login-secrets")).toBe(false);
        expect(isPublicRoute("/api/auth/login/steal")).toBe(false);
    });

    it("treats the translate API as public wholesale", () => {
        expect(isPublicRoute("/api/translate/anything")).toBe(true);
    });

    it("does not accidentally list an admin route as public", () => {
        for (const route of PUBLIC_ROUTES) {
            expect(isAdminSurface(route)).toBe(false);
        }
    });
});

describe("admin surface", () => {
    it("covers both the pages and the API", () => {
        for (const path of ["/admin", "/admin/families", "/api/admin", "/api/admin/audit"]) {
            expect(isAdminSurface(path)).toBe(true);
        }
    });

    it("does not match a lookalike prefix", () => {
        // /administration must not inherit the operator surface's handling.
        expect(isAdminSurface("/administration")).toBe(false);
        expect(isAdminSurface("/api/administrivia")).toBe(false);
    });
});

describe("module gating", () => {
    it("maps gated prefixes to their module key", () => {
        expect(moduleForPath("/budget/transactions")).toBe("budget");
        expect(moduleForPath("/envelopes")).toBe("budget");
        expect(moduleForPath("/chat")).toBe("chat");
        expect(moduleForPath("/dm/abc")).toBe("chat");
        expect(moduleForPath("/bank")).toBe("gigs");
    });

    it("never gates core surfaces", () => {
        // Switching a module off must not be able to lock a family out of
        // tasks, rewards, settings or the dashboard.
        for (const path of ["/dashboard", "/parent", "/parent/settings", "/rewards", "/admin"]) {
            expect(moduleForPath(path)).toBeNull();
        }
    });

    it("redirects a deep link into a disabled module, by role", () => {
        const kid = { enabled_modules: ["meals"], role: "CHILD" };
        const parent = { enabled_modules: ["meals"], role: "PARENT" };
        expect(moduleRedirectTarget("/budget", kid)).toBe("/dashboard?module_off=1");
        expect(moduleRedirectTarget("/budget", parent)).toBe("/parent?module_off=1");
    });

    it("allows a module the family has enabled", () => {
        expect(moduleRedirectTarget("/budget", { enabled_modules: ["budget"] })).toBeNull();
    });

    it("fails OPEN when the module list is absent or unreadable", () => {
        // NULL enabled_modules means "all on"; an unreadable /auth/me must not
        // lock a family out of a module they actually have. Gating is UX, not
        // a security boundary — the backend APIs stay live regardless.
        expect(moduleRedirectTarget("/budget", null)).toBeNull();
        expect(moduleRedirectTarget("/budget", {})).toBeNull();
        expect(moduleRedirectTarget("/budget", { enabled_modules: "nonsense" })).toBeNull();
    });
});

describe("JWT expiry", () => {
    const encode = (payload: object) =>
        "h." + Buffer.from(JSON.stringify(payload)).toString("base64url") + ".s";

    it("treats a live token as usable", () => {
        const now = 1_800_000_000_000;
        expect(isJwtExpired(encode({ exp: now / 1000 + 3600 }), now)).toBe(false);
    });

    it("treats an expired token as expired", () => {
        const now = 1_800_000_000_000;
        expect(isJwtExpired(encode({ exp: now / 1000 - 1 }), now)).toBe(true);
    });

    it("expires 30s early to avoid a race at the boundary", () => {
        const now = 1_800_000_000_000;
        // 20s of life left — inside the skew window, so treated as expired.
        expect(isJwtExpired(encode({ exp: now / 1000 + 20 }), now)).toBe(true);
        // 40s left — outside it.
        expect(isJwtExpired(encode({ exp: now / 1000 + 40 }), now)).toBe(false);
    });

    it("fails closed on anything unusable", () => {
        // A malformed token must trigger a refresh, never be trusted.
        expect(isJwtExpired(undefined)).toBe(true);
        expect(isJwtExpired("")).toBe(true);
        expect(isJwtExpired("not-a-jwt")).toBe(true);
        expect(isJwtExpired("a.b")).toBe(true);
        expect(isJwtExpired("h.!!!not-base64!!!.s")).toBe(true);
        expect(isJwtExpired(encode({ sub: "no-exp-claim" }))).toBe(true);
    });
});
