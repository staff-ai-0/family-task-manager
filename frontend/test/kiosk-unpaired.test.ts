import { describe, expect, it } from "vitest";

import {
    kioskFailureReason,
    kioskUnpairedStatus,
    renderKioskUnpaired,
} from "../src/lib/kiosk-unpaired";

describe("kioskFailureReason", () => {
    it("treats auth-ish statuses as an invalid link", () => {
        expect(kioskFailureReason(401)).toBe("invalid");
        expect(kioskFailureReason(403)).toBe("invalid");
        expect(kioskFailureReason(404)).toBe("invalid");
    });
    it("treats a down backend as unavailable, not an expired link", () => {
        expect(kioskFailureReason(0)).toBe("unavailable");
        expect(kioskFailureReason(undefined)).toBe("unavailable");
        expect(kioskFailureReason(502)).toBe("unavailable");
    });
});

describe("kioskUnpairedStatus", () => {
    it("maps reasons to HTTP statuses", () => {
        expect(kioskUnpairedStatus("missing")).toBe(400);
        expect(kioskUnpairedStatus("invalid", 404)).toBe(404);
        expect(kioskUnpairedStatus("invalid", undefined)).toBe(401);
        expect(kioskUnpairedStatus("unavailable", 502)).toBe(503);
    });
});

describe("renderKioskUnpaired", () => {
    it("defaults to Spanish and sends a signed-in parent to pairing", () => {
        const html = renderKioskUnpaired({ lang: "es", reason: "missing", signedIn: true });
        expect(html.startsWith("<!doctype html>")).toBe(true);
        expect(html).toContain('lang="es"');
        expect(html).toContain("Esta pantalla no está vinculada");
        expect(html).toContain('href="/parent/kiosk"');
        expect(html).not.toContain("Missing token");
    });
    it("sends a signed-out visitor to login", () => {
        const html = renderKioskUnpaired({ lang: "es", reason: "invalid", signedIn: false });
        expect(html).toContain('href="/login"');
        expect(html).toContain("expiró");
    });
    it("renders English", () => {
        const html = renderKioskUnpaired({ lang: "en", reason: "missing", signedIn: false });
        expect(html).toContain('lang="en"');
        expect(html).toContain("This screen isn't paired");
    });
    it("offers a retry, not pairing, when the backend is down", () => {
        const html = renderKioskUnpaired({ lang: "es", reason: "unavailable", signedIn: true });
        expect(html).toContain("location.reload()");
        expect(html).not.toContain("/parent/kiosk");
    });
    it("falls back to Spanish for unknown languages", () => {
        expect(renderKioskUnpaired({ lang: "fr", reason: "missing", signedIn: false })).toContain('lang="es"');
    });
});
