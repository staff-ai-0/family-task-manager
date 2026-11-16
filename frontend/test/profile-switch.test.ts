import { describe, expect, it } from "vitest";
import {
    errorKey,
    isSwitchedSession,
    pinPadAppend,
    profileCopy,
    switchFailureAction,
} from "../src/lib/profileSwitch";
import { isPublicRoute, sharedDeviceRedirect } from "../src/lib/security/request-guards";

describe("sharedDeviceRedirect (I1: a shared device falls back to the picker, not /login)", () => {
    it("does nothing without the ftm_shared hint", () => {
        expect(sharedDeviceRedirect("/", false, false)).toBeNull();
        expect(sharedDeviceRedirect("/dashboard", false, false)).toBeNull();
    });
    it("does nothing while a session is live", () => {
        expect(sharedDeviceRedirect("/", true, true)).toBeNull();
        expect(sharedDeviceRedirect("/dashboard", true, true)).toBeNull();
    });
    it("sends the landing page and protected pages to /profiles", () => {
        for (const p of ["/", "/dashboard", "/dashboard/", "/parent", "/parent/settings/family", "/pet"]) {
            expect(sharedDeviceRedirect(p, false, true)).toBe("/profiles");
        }
    });
    it("leaves public pages other than / reachable (login, legal, marketing, the picker itself)", () => {
        for (const p of ["/login", "/login/", "/register", "/privacidad", "/terminos", "/tdah", "/help", "/kiosk", "/profiles"]) {
            expect(sharedDeviceRedirect(p, false, true)).toBeNull();
        }
    });
    it("never redirects API routes (they keep their JSON 401)", () => {
        for (const p of ["/api/tasks", "/api/auth/me", "/api/auth/profile/list", "/api/auth/profile/share"]) {
            expect(sharedDeviceRedirect(p, false, true)).toBeNull();
        }
    });
});

describe("switchFailureAction (picker)", () => {
    it("a 401 means ftm_home is gone: go to /login", () => {
        expect(switchFailureAction(401)).toEqual({ redirect: "/login" });
    });
    it("other failures show a message and stay on the pad", () => {
        expect(switchFailureAction(403)).toEqual({ message: "wrongPin" });
        expect(switchFailureAction(429)).toEqual({ message: "locked" });
        expect(switchFailureAction(500)).toEqual({ message: "error" });
    });
});

describe("share copy warns about the parent's saved credentials (I3)", () => {
    it("ES and EN tell the parent not to save the password and to sign out of Google", () => {
        const es = profileCopy("es").shareBody;
        const en = profileCopy("en").shareBody;
        expect(es).toMatch(/no guardes tu contraseña/i);
        expect(es).toMatch(/Google/);
        expect(en).toMatch(/don't save your password/i);
        expect(en).toMatch(/Google/);
    });
});

describe("profileSwitch helpers", () => {
    it("errorKey maps statuses", () => {
        expect(errorKey(403)).toBe("wrongPin");
        expect(errorKey(429)).toBe("locked");
        expect(errorKey(500)).toBe("error");
        expect(errorKey(401)).toBe("error");
    });
    it("pinPadAppend caps at 4 digits and ignores non-digits", () => {
        expect(pinPadAppend("", "1")).toBe("1");
        expect(pinPadAppend("123", "4")).toBe("1234");
        expect(pinPadAppend("1234", "5")).toBe("1234");
        expect(pinPadAppend("12", "a")).toBe("12");
        expect(pinPadAppend("12", "")).toBe("12");
        expect(pinPadAppend("12", "34")).toBe("12");
    });
    it("isSwitchedSession reads ftm_sw exactly", () => {
        expect(isSwitchedSession("a=b; ftm_sw=1; c=d")).toBe(true);
        expect(isSwitchedSession("ftm_sw=1")).toBe(true);
        expect(isSwitchedSession("a=b")).toBe(false);
        expect(isSwitchedSession("")).toBe(false);
        expect(isSwitchedSession("xftm_sw=1")).toBe(false);
        expect(isSwitchedSession("ftm_sw_other=1")).toBe(false);
    });
    it("both languages define every copy key", () => {
        const es = profileCopy("es");
        const en = profileCopy("en");
        expect(Object.keys(es).sort()).toEqual(Object.keys(en).sort());
        expect(Object.keys(es)).toEqual(
            expect.arrayContaining([
                "title", "pickPrompt", "pinTitle", "wrongPin", "locked", "noPin", "backToParent",
                "passwordPrompt", "wrongPassword", "shareTitle", "shareBody", "shareCta",
            ]),
        );
        for (const v of [...Object.values(es), ...Object.values(en)]) expect(v.length).toBeGreaterThan(0);
        expect(es.title).not.toBe(en.title);
    });
});

describe("profile routes and the public list", () => {
    it("picker page and home-cookie routes are public; share is not", () => {
        for (const p of ["/profiles", "/api/auth/profile/list", "/api/auth/profile/switch", "/api/auth/profile/return"]) {
            expect(isPublicRoute(p)).toBe(true);
        }
        expect(isPublicRoute("/api/auth/profile/share")).toBe(false);
    });
});
