import { describe, expect, it } from "vitest";

import { CSP } from "../src/lib/security/csp";

const directive = (name: string) =>
    CSP.split("; ").find((d) => d.startsWith(`${name} `)) ?? "";

describe("CSP", () => {
    it("lets the Cloudflare Web Analytics beacon load", () => {
        expect(directive("script-src")).toContain("https://static.cloudflareinsights.com");
    });
    it("lets the beacon report", () => {
        expect(directive("connect-src")).toContain("https://cloudflareinsights.com");
    });
    it("keeps Google Sign-In working", () => {
        expect(directive("script-src")).toContain("https://accounts.google.com");
        expect(directive("frame-src")).toContain("https://accounts.google.com");
    });
    it("keeps the strict defaults", () => {
        expect(directive("default-src")).toBe("default-src 'self'");
        expect(directive("frame-ancestors")).toBe("frame-ancestors 'none'");
        expect(directive("object-src")).toBe("object-src 'none'");
    });
});
