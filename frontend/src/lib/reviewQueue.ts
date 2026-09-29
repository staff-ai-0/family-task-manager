import { parseUtcInstant } from "./datetime";

/** One pending decision on the parent home (UX-C2): a chore/bonus proof, a
 *  gig-board claim, or a reward redemption — the same three sources
 *  /parent/approvals lists. */
export type ReviewKind = "task" | "gig" | "redemption";

export interface ReviewItem {
    kind: ReviewKind;
    id: string;
    title: string;
    kidName: string;
    when: string | null;
    chip: string;
    proofImageUrl: string | null;
    proofText: string | null;
    /** Partial credit is rejected on collaboration gigs (pot conservation). */
    allowPartial: boolean;
}

const asArray = (v: unknown): any[] => (Array.isArray(v) ? v : []);

const instant = (when: string | null): number => {
    if (!when) return NaN;
    const t = parseUtcInstant(when).getTime();
    return Number.isFinite(t) ? t : NaN;
};

export function buildReviewQueue(
    tasks: unknown,
    claims: unknown,
    redemptions: unknown,
    lang: "es" | "en",
): ReviewItem[] {
    const items: ReviewItem[] = [
        ...asArray(tasks).map((r): ReviewItem => ({
            kind: "task",
            id: String(r.assignment_id),
            title: r.template_title ?? "",
            kidName: r.assigned_to_name ?? "",
            when: r.completed_at ?? null,
            chip: `+${r.points ?? 0} pts`,
            proofImageUrl: r.proof_image_url ?? null,
            proofText: r.proof_text ?? null,
            allowPartial: r.template_gig_mode !== "collaboration",
        })),
        ...asArray(claims).map((c): ReviewItem => ({
            kind: "gig",
            id: String(c.id),
            title: c.gig_title ?? "",
            kidName: c.claimer_name ?? "",
            when: c.completed_at ?? null,
            chip: `gig $${c.gig_points ?? 0}`,
            proofImageUrl: c.proof_image_url ?? null,
            proofText: c.proof_text ?? null,
            allowPartial: false,
        })),
        ...asArray(redemptions).map((r): ReviewItem => ({
            kind: "redemption",
            id: String(r.id),
            title: `${lang === "es" ? "Canjear" : "Redeem"}: ${r.reward_title ?? ""}`,
            kidName: r.user_name ?? "",
            when: r.created_at ?? null,
            chip: `${r.points_cost ?? 0} pts`,
            proofImageUrl: null,
            proofText: null,
            allowPartial: false,
        })),
    ];
    return items
        .map((item, index) => ({ item, index, t: instant(item.when) }))
        .sort((a, b) => {
            const aMissing = Number.isNaN(a.t);
            const bMissing = Number.isNaN(b.t);
            if (aMissing !== bMissing) return aMissing ? 1 : -1;
            if (!aMissing && a.t !== b.t) return a.t - b.t;
            return a.index - b.index;
        })
        .map((x) => x.item);
}

/** Ids of the rendered cards (visible + hidden) and the full pending count,
 *  which can exceed what the page rendered. */
export interface QueueState {
    visible: string[];
    hidden: string[];
    total: number;
}

export function advanceQueue(
    state: QueueState,
    decidedId: string,
): QueueState & { reveal: string | null; empty: boolean; remainingElsewhere: number } {
    const known = state.visible.includes(decidedId) || state.hidden.includes(decidedId);
    if (!known) {
        return { ...state, reveal: null, empty: state.total === 0, remainingElsewhere: 0 };
    }
    const visible = state.visible.filter((id) => id !== decidedId);
    let hidden = state.hidden.filter((id) => id !== decidedId);
    let reveal: string | null = null;
    if (visible.length < state.visible.length && hidden.length > 0) {
        reveal = hidden[0];
        hidden = hidden.slice(1);
        visible.push(reveal);
    }
    const total = Math.max(0, state.total - 1);
    const remainingElsewhere = visible.length === 0 && total > 0 ? total : 0;
    return { visible, hidden, total, reveal, empty: total === 0, remainingElsewhere };
}
