import type { ReviewKind } from "./reviewQueue";

/** One review decision — the request shapes /parent/approvals has always
 *  sent, shared with the parent home (UX-C2). */
export type Decision = {
    kind: ReviewKind;
    id: string;
    approve: boolean;
    grade?: "full" | "partial" | "missed" | null;
    partialPct?: number | null;
    notes?: string | null;
};

export type DecisionResult = { ok: true } | { ok: false; error: string | null };

export function decisionRequest(d: Decision): { url: string; body: Record<string, unknown> } {
    const notes = d.notes ?? null;
    if (d.kind === "gig") {
        return { url: `/api/gigs/claims/${d.id}/approve`, body: { approved: d.approve, notes } };
    }
    if (d.kind === "redemption") {
        return { url: `/api/rewards/redemptions/${d.id}/${d.approve ? "approve" : "reject"}`, body: { notes } };
    }
    return {
        url: "/api/assignments/approve",
        body: {
            assignment_id: d.id,
            approve: d.approve,
            notes,
            grade: d.grade ?? null,
            partial_credit_pct: d.partialPct ?? null,
        },
    };
}

export async function submitDecision(d: Decision, fetchImpl: typeof fetch = fetch): Promise<DecisionResult> {
    const { url, body } = decisionRequest(d);
    try {
        const r = await fetchImpl(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (r.ok) return { ok: true };
        const err = await r.json().catch(() => null);
        const reason = err && (err.detail || err.message);
        return { ok: false, error: typeof reason === "string" ? reason : null };
    } catch {
        return { ok: false, error: null };
    }
}
