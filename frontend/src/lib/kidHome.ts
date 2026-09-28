/**
 * View models for the kid home (UX-C1): which gigs to show in "Gana extra",
 * which are "Nuevo", and the weekly pay meter. Pure — vitest-covered.
 */
export const NEW_GIG_WINDOW_MS = 48 * 3600 * 1000;

/** When a gig reached the board: approval time for proposals, else creation. */
function publishedAt(offering: any): number | null {
    const raw = offering?.reviewed_at ?? offering?.created_at;
    if (!raw) return null;
    const t = new Date(raw).getTime();
    return Number.isNaN(t) ? null : t;
}

export function isNewGig(offering: any, now: Date = new Date()): boolean {
    const t = publishedAt(offering);
    return t !== null && now.getTime() - t < NEW_GIG_WINDOW_MS;
}

export interface GigChip {
    id: string;
    title: string;
    pesos: number;
    isNew: boolean;
}

/** Active, approved gigs this role may claim right now, newest first. */
export function claimableGigs(items: unknown, role: string, now: Date = new Date(), max = 6): GigChip[] {
    if (!Array.isArray(items)) return [];
    return items
        .filter((item: any) => {
            const o = item?.offering;
            if (!o || !o.is_active || (o.status ?? "approved") !== "approved") return false;
            if (Array.isArray(o.allowed_roles) && o.allowed_roles.length > 0 && !o.allowed_roles.includes(role)) {
                return false;
            }
            if (item.my_claim) return false;
            const takenBy = Array.isArray(item.active_claimers) ? item.active_claimers : [];
            return Boolean(o.allow_multiple) || takenBy.length === 0;
        })
        .sort((x: any, y: any) => (publishedAt(y.offering) ?? 0) - (publishedAt(x.offering) ?? 0))
        .slice(0, max)
        .map((item: any) => ({
            id: String(item.offering.id),
            title: item.offering.title,
            pesos: item.offering.points,
            isNew: isNewGig(item.offering, now),
        }));
}

export type PayMeter =
    | { show: false }
    | { show: true; capCents: number; greenPct: number; redPct: number; released: boolean };

const clampPct = (n: unknown) => {
    const v = Math.round(Number(n));
    return Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : 0;
};

/** Weekly chore-paycheck meter: goal + bar only — never a moving $ figure. */
export function payMeterView(paycheck: any): PayMeter {
    if (paycheck?.mode !== "chore_proportional" || !((paycheck?.cap_cents ?? 0) > 0)) {
        return { show: false };
    }
    const greenPct = clampPct(paycheck.pct);
    const redPct = Math.min(clampPct(paycheck.discounted_pct), 100 - greenPct);
    return {
        show: true,
        capCents: paycheck.cap_cents,
        greenPct,
        redPct,
        released: Boolean(paycheck.already_released),
    };
}
