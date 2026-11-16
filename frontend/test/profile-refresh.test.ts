import { describe, it, expect, vi, afterEach } from "vitest";
import { shouldAttemptRefresh } from "../src/lib/security/request-guards";
import { refreshAccessToken } from "../src/lib/server/refresh";

describe("profile routes never trigger a transparent refresh", () => {
    for (const p of ["switch", "return", "share", "list"]) {
        it(`/api/auth/profile/${p}`, () => {
            expect(shouldAttemptRefresh(`/api/auth/profile/${p}`, undefined, "r")).toBe(false);
        });
    }
    it("ordinary routes still refresh", () => {
        expect(shouldAttemptRefresh("/api/auth/me", undefined, "r")).toBe(true);
    });
});

describe("refreshAccessToken keeps the switched marker alive", () => {
    afterEach(() => vi.unstubAllGlobals());
    const mock = (body: object) =>
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => body }));
    const find = (cs: string[], n: string) => cs.find((c) => c.startsWith(n + "="));

    it("switched: adds ftm_sw and 2h refresh", async () => {
        mock({ access_token: "a", refresh_token: "r", switched: true });
        const r = await refreshAccessToken("old");
        expect(find(r.setCookies!, "ftm_sw")).toContain("Max-Age=7200");
        expect(find(r.setCookies!, "refresh_token")).toContain("Max-Age=7200");
    });
    it("normal: no marker, 30 days", async () => {
        mock({ access_token: "a", refresh_token: "r", switched: false });
        const r = await refreshAccessToken("old");
        expect(find(r.setCookies!, "ftm_sw")).toBeUndefined();
        expect(find(r.setCookies!, "refresh_token")).toContain("Max-Age=2592000");
    });
});
