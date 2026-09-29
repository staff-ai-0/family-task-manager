/**
 * The swipe deck's cards, built from GET /api/task-assignments/progress
 * (UX-C1). Order: overdue chores (one card per chore, completing the OLDEST
 * instance) → today's required → today's bonus, or one locked card while
 * bonus is gated. Done and awaiting-approval assignments are not cards.
 *
 * A grouped overdue card stays on the table until its LAST instance is done:
 * completing one advances the card to the next-oldest id (afterComplete).
 */
export interface DeckCard {
    /** Assignment id to complete ("locked" for the gated-bonus placeholder). */
    id: string;
    title: string;
    points: number;
    isBonus: boolean;
    requiresProof: boolean;
    overdue: boolean;
    /** Instances behind a grouped overdue card (0 for non-overdue cards). */
    overdueCount: number;
    /** Every instance id behind a grouped overdue card, oldest first
     * (`id === overdueIds[0]`); `[]` for non-overdue cards. */
    overdueIds: string[];
    locked: boolean;
    /** Bonus tasks behind the locked card. */
    lockedCount: number;
}

export interface Deck {
    cards: DeckCard[];
    doneToday: number;
    totalToday: number;
    /** Today's completed assignments waiting for a parent decision. */
    inReview: number;
}

interface Assignment {
    id: string;
    template_id?: string | null;
    template_title?: string | null;
    template_title_es?: string | null;
    template_points?: number | null;
    template_is_bonus?: boolean | null;
    template_requires_proof?: boolean | null;
    status?: string | null;
    approval_status?: string | null;
    due_date?: string | null;
    assigned_date?: string | null;
}

const toCard = (a: Assignment, lang: string, extra: Partial<DeckCard> = {}): DeckCard => ({
    id: String(a.id),
    title: (lang === "es" && a.template_title_es) || a.template_title || "",
    points: a.template_points ?? 0,
    isBonus: Boolean(a.template_is_bonus),
    requiresProof: Boolean(a.template_requires_proof),
    overdue: false,
    overdueCount: 0,
    overdueIds: [],
    locked: false,
    lockedCount: 0,
    ...extra,
});

const when = (a: Assignment) => String(a.due_date ?? a.assigned_date ?? "");

export function buildDeck(progress: unknown, lang: string): Deck {
    const p = (progress ?? {}) as Record<string, any>;
    const assignments: Assignment[] = Array.isArray(p.assignments) ? p.assignments : [];
    const overdue: Assignment[] = Array.isArray(p.overdue_assignments) ? p.overdue_assignments : [];

    const groups = new Map<string, Assignment[]>();
    for (const item of overdue) {
        const key = String(item.template_id ?? item.template_title);
        const list = groups.get(key);
        if (list) list.push(item);
        else groups.set(key, [item]);
    }
    const overdueCards = [...groups.values()]
        .map((items) => [...items].sort((x, y) => when(x).localeCompare(when(y))))
        .sort((x, y) => when(x[0]).localeCompare(when(y[0])))
        .map((sorted) => toCard(sorted[0], lang, {
            overdue: true,
            overdueCount: sorted.length,
            overdueIds: sorted.map((x) => String(x.id)),
        }));

    const isPending = (a: Assignment) => a.status === "pending";
    const required = assignments.filter((a) => !a.template_is_bonus && isPending(a)).map((a) => toCard(a, lang));
    const bonusPending = assignments.filter((a) => a.template_is_bonus && isPending(a));
    const bonus: DeckCard[] = p.bonus_unlocked
        ? bonusPending.map((a) => toCard(a, lang))
        : bonusPending.length > 0
            ? [{
                id: "locked", title: "", points: 0, isBonus: true, requiresProof: false,
                overdue: false, overdueCount: 0, overdueIds: [], locked: true, lockedCount: bonusPending.length,
            }]
            : [];

    return {
        cards: [...overdueCards, ...required, ...bonus],
        doneToday: p.required_completed ?? 0,
        totalToday: p.required_total ?? 0,
        inReview: assignments.filter((a) => a.status === "completed" && a.approval_status === "pending").length,
    };
}

/**
 * What the deck does after `card.id` was completed: a grouped overdue card
 * with instances left advances to the next-oldest one (`remaining` counts the
 * instances still behind the card, incl. `nextId`); anything else leaves.
 */
export function afterComplete(card: { id: string; overdueIds: string[] }): { nextId: string | null; remaining: number } {
    const at = card.overdueIds.indexOf(card.id);
    if (at < 0 || at + 1 >= card.overdueIds.length) return { nextId: null, remaining: 0 };
    return { nextId: card.overdueIds[at + 1], remaining: card.overdueIds.length - at - 1 };
}
