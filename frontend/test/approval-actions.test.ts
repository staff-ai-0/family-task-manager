import { describe, expect, it, vi } from "vitest";

import { decisionRequest, submitDecision } from "../src/lib/approvalActions";

const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("decisionRequest", () => {
    it("task full approval", () => {
        expect(decisionRequest({ kind: "task", id: "a1", approve: true, grade: "full" })).toEqual({
            url: "/api/assignments/approve",
            body: { assignment_id: "a1", approve: true, notes: null, grade: "full", partial_credit_pct: null },
        });
    });
    it("task partial carries the percent and the note", () => {
        expect(
            decisionRequest({ kind: "task", id: "a1", approve: true, grade: "partial", partialPct: 75, notes: "casi" }).body,
        ).toEqual({ assignment_id: "a1", approve: true, notes: "casi", grade: "partial", partial_credit_pct: 75 });
    });
    it("task missed", () => {
        expect(decisionRequest({ kind: "task", id: "a1", approve: false, grade: "missed" }).body).toMatchObject({
            approve: false, grade: "missed",
        });
    });
    it("task batch approval keeps grade null", () => {
        expect(decisionRequest({ kind: "task", id: "a1", approve: true }).body).toMatchObject({ grade: null, partial_credit_pct: null });
    });
    it("gig claim", () => {
        expect(decisionRequest({ kind: "gig", id: "c1", approve: false, notes: "x" })).toEqual({
            url: "/api/gigs/claims/c1/approve",
            body: { approved: false, notes: "x" },
        });
    });
    it("reward redemption approve and reject", () => {
        expect(decisionRequest({ kind: "redemption", id: "r1", approve: true })).toEqual({
            url: "/api/rewards/redemptions/r1/approve", body: { notes: null },
        });
        expect(decisionRequest({ kind: "redemption", id: "r1", approve: false }).url).toBe("/api/rewards/redemptions/r1/reject");
    });
});

describe("submitDecision", () => {
    it("posts JSON and resolves ok on 2xx", async () => {
        const f = vi.fn(async () => json(200, {}));
        expect(await submitDecision({ kind: "gig", id: "c1", approve: true }, f as unknown as typeof fetch)).toEqual({ ok: true });
        expect(f).toHaveBeenCalledWith("/api/gigs/claims/c1/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: true, notes: null }),
        });
    });
    it("surfaces detail, then message", async () => {
        const detail = vi.fn(async () => json(400, { detail: "Insufficient points. Need 200, have 50" }));
        expect(await submitDecision({ kind: "redemption", id: "r1", approve: true }, detail as unknown as typeof fetch)).toEqual({
            ok: false, error: "Insufficient points. Need 200, have 50",
        });
        const message = vi.fn(async () => json(500, { message: "boom" }));
        expect(await submitDecision({ kind: "gig", id: "c1", approve: true }, message as unknown as typeof fetch)).toEqual({ ok: false, error: "boom" });
    });
    it("drops a non-string detail (validation list)", async () => {
        const f = vi.fn(async () => json(422, { detail: [{ loc: ["body"], msg: "bad" }] }));
        expect(await submitDecision({ kind: "task", id: "a1", approve: true }, f as unknown as typeof fetch)).toEqual({ ok: false, error: null });
    });
    it("a network error is a failure without a reason", async () => {
        const f = vi.fn(async () => { throw new Error("offline"); });
        expect(await submitDecision({ kind: "task", id: "a1", approve: true }, f as unknown as typeof fetch)).toEqual({ ok: false, error: null });
    });
});
