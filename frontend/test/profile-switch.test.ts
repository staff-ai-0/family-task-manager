import { describe, expect, it } from "vitest";
import { errorKey, isSwitchedSession, pinPadAppend, profileCopy } from "../src/lib/profileSwitch";
import { isPublicRoute } from "../src/lib/security/request-guards";

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
