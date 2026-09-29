import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "../src/pages/api/assignments/complete";
import { completeErrorMessage } from "../src/lib/completeMessages";

const cookies = (vals: Record<string, string>) => ({
    get: (k: string) => (k in vals ? { value: vals[k] } : undefined),
});

function req(fields: Record<string, string>, json = true): Request {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);
    return new Request("http://localhost/api/assignments/complete", {
        method: "POST",
        body: fd,
        headers: json ? { accept: "application/json" } : {},
    });
}

const backend = (status: number, body: unknown) =>
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

const call = (request: Request, c = cookies({ access_token: "t", lang: "es" })) =>
    POST({ request, cookies: c, redirect: () => new Response(null) } as any);

afterEach(() => vi.unstubAllGlobals());

describe("POST /api/assignments/complete — JSON mode", () => {
    it("returns ok + a friendly message on success", async () => {
        vi.stubGlobal("fetch", backend(200, { template_title: "Lavar", template_title_es: "Lavar trastes", approval_status: "pending" }));
        const res = await call(req({ assignment_id: "a1" }));
        expect(res.status).toBe(200);
        const body = await res.json();
        expect(body).toMatchObject({ ok: true, approval_status: "pending" });
        expect(body.message).toContain("Lavar trastes");
    });

    it("maps a backend 4xx to the backend status with friendly copy", async () => {
        vi.stubGlobal("fetch", backend(400, { detail: "Complete all mandatory tasks first" }));
        const res = await call(req({ assignment_id: "a1" }));
        expect(res.status).toBe(400);
        const body = await res.json();
        expect(body.ok).toBe(false);
        expect(body.message).toContain("obligatorias");
    });

    it("rejects a missing assignment id with 400", async () => {
        vi.stubGlobal("fetch", backend(200, {}));
        const res = await call(req({}));
        expect(res.status).toBe(400);
        expect((await res.json()).ok).toBe(false);
    });

    it("answers 401 JSON without a session", async () => {
        const res = await call(req({ assignment_id: "a1" }), cookies({}));
        expect(res.status).toBe(401);
        expect((await res.json()).ok).toBe(false);
    });

    it("answers 500 JSON when the backend is unreachable", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED"); }));
        const res = await call(req({ assignment_id: "a1" }));
        expect(res.status).toBe(500);
        expect((await res.json()).ok).toBe(false);
    });
});

describe("POST /api/assignments/complete — form mode (unchanged)", () => {
    it("still redirects with a flash cookie", async () => {
        vi.stubGlobal("fetch", backend(200, { template_title: "Lavar", approval_status: "approved" }));
        const res = await call(req({ assignment_id: "a1", next: "/parent" }, false));
        expect(res.status).toBe(302);
        expect(res.headers.get("location")).toBe("/parent");
        expect(res.headers.get("set-cookie")).toContain("flash=");
    });
});

describe("completeErrorMessage", () => {
    it("picks a side of bilingual backend copy", () => {
        expect(completeErrorMessage(400, "Hola / Hello", true)).toBe("Hola");
        expect(completeErrorMessage(400, "Hola / Hello", false)).toBe("Hello");
    });
});
