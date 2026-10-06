import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { RECEIPT_COPY, confirmBody, errorDetail, kidChips, pesosToCents, proposalRows, recordRows, rowProblem, type PostResult, type Row } from "../src/lib/payoutReceipts";

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");

const scan = {
    receipts: [
        { filename: "a.png", readable: true, folio: "0011968514", receipt_date: "2026-09-04", concept: "semana 36", amount_cents: 25000, beneficiary: "Ariana Michelle M", user_id: "k1", duplicate_folio: false, weeks_from_concept: true, mismatch: false, allocations: [{ week_of: "2026-08-31", amount_cents: 25000, already_paid: false, projected_cents: 25000 }] },
        { filename: "b.png", readable: true, folio: "0090172139", amount_cents: 50000, user_id: null, duplicate_folio: true, allocations: [] },
        { filename: "c.png", readable: false, error: "x" },
    ],
};

const row = (over: Partial<Row> = {}): Row => ({
    key: "r", filename: "a.png", folio: "0011968514", receiptDate: "2026-09-04", concept: "semana 36", beneficiary: "A",
    amountCents: 25000, userId: "k1", allocations: [{ weekOf: "2026-08-31", amountCents: 25000, alreadyPaid: false, projectedCents: 0 }],
    duplicate: false, mismatch: false, guessedWeeks: false, checked: true, error: null, ...over,
});

describe("proposalRows", () => {
    it("maps readable slips, unticks duplicates and lists unreadable files", () => {
        const { rows, unreadable } = proposalRows(scan);
        expect(rows).toHaveLength(2);
        expect(rows[0]).toMatchObject({ folio: "0011968514", amountCents: 25000, userId: "k1", checked: true, guessedWeeks: false });
        expect(rows[1]).toMatchObject({ userId: null, duplicate: true, checked: false });
        expect(unreadable).toEqual(["c.png"]);
    });
    it("keeps the folio's leading zeros and survives garbage", () => {
        expect(proposalRows(scan).rows[0].folio).toBe("0011968514");
        for (const v of [null, undefined, {}, { receipts: "x" }, { receipts: [null, 1] }]) expect(proposalRows(v).rows).toEqual([]);
    });
});

describe("rowProblem / confirmBody", () => {
    it("needs a kid, a week and amounts that add up", () => {
        expect(rowProblem(row(), "en")).toBeNull();
        expect(rowProblem(row({ userId: null }), "en")).toBe(RECEIPT_COPY.needKid.en);
        expect(rowProblem(row({ allocations: [] }), "es")).toBe(RECEIPT_COPY.needWeek.es);
        expect(rowProblem(row({ amountCents: 30000 }), "en")).toContain("$300.00");
    });
    it("builds the confirm body in centavos", () => {
        expect(confirmBody(row())).toEqual({
            folio: "0011968514", user_id: "k1", receipt_date: "2026-09-04", concept: "semana 36", amount_cents: 25000,
            allocations: [{ week_of: "2026-08-31", amount_cents: 25000 }],
        });
        expect(pesosToCents("250.50")).toBe(25050);
        expect(pesosToCents("")).toBe(0);
    });
});

describe("recordRows", () => {
    it("records ticked rows once, keeps a failure on its row, never re-posts a recorded one", async () => {
        const rows = [row({ key: "a" }), row({ key: "b", folio: "2" }), row({ key: "c", folio: "3", checked: false })];
        const recorded = new Set<string>();
        const calls: string[] = [];
        let failB = true;
        const post = async (body: { folio: string }): Promise<PostResult> => {
            calls.push(body.folio);
            return body.folio === "2" && failB ? { ok: false, detail: "boom" } : { ok: true, detail: null };
        };
        expect(await recordRows(rows, recorded, post, "en")).toBe(1);
        expect(rows[1].error).toBe("boom");
        failB = false;
        expect(await recordRows(rows, recorded, post, "en")).toBe(1);
        expect(calls).toEqual(["0011968514", "2", "2"]);   // A never re-posted, C never posted
        expect(rows[1].error).toBeNull();
    });
    it("does not post a row with a local problem", async () => {
        const bad = row({ userId: null });
        let posted = 0;
        await recordRows([bad], new Set(), async () => { posted++; return { ok: true, detail: null }; }, "en");
        expect(posted).toBe(0);
        expect(bad.error).toBe(RECEIPT_COPY.needKid.en);
    });
});

describe("helpers", () => {
    it("kidChips keeps only active approved children and teens", () => {
        const m = [
            { id: "1", name: "Ari", role: "child", is_active: true, approval_status: "approved" },
            { id: "2", name: "Mom", role: "parent" },
            { id: "3", name: "Gone", role: "teen", is_active: false },
            { id: "4", name: "New", role: "teen", approval_status: "pending" },
        ];
        expect(kidChips(m)).toEqual([{ id: "1", label: "Ari" }]);
    });
    it("errorDetail reads string and validation-list details", () => {
        expect(errorDetail({ detail: "nope" }, "f")).toBe("nope");
        expect(errorDetail({ detail: [{ msg: "bad" }] }, "f")).toBe("bad");
        expect(errorDetail(null, "f")).toBe("f");
    });
});

describe("payouts page", () => {
    it("no longer carries the per-week release / adjust / top-up controls", () => {
        const page = read("../src/pages/parent/payouts.astro");
        for (const gone of ["data-release", "data-adjust", "data-topup", "wireTopUp"]) expect(page).not.toContain(gone);
        expect(page).toContain("/parent/payouts/receipts");
    });
});
