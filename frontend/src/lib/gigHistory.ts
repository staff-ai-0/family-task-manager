/**
 * Parent gig history, grouped by job.
 *
 * Reposting a closed gig must create a NEW offering: the claim model allows
 * one approved claim per kid per offering (uq_gig_claim_active), so the old
 * offering can't simply be reopened. Each cycle therefore has its own
 * gig_id, and older reposts also carry a " (copia)" suffix. Grouping by
 * gig_id listed every cycle separately — the "clogged history" report
 * (2026-09-28) — so history groups by the job's title instead, ignoring copy
 * suffixes, case and extra whitespace.
 */

const COPY_SUFFIX = /\s*\((?:copia|copy)\)\s*$/i;

/** Title as a person would read it: copy suffixes and extra spaces removed. */
export function displayGigTitle(title: string | null | undefined): string {
    let t = (title ?? "").replace(/\s+/g, " ").trim();
    while (COPY_SUFFIX.test(t)) t = t.replace(COPY_SUFFIX, "").trim();
    return t;
}

/** Grouping key: the display title, case-insensitive. */
export function gigTitleKey(title: string | null | undefined): string {
    return displayGigTitle(title).toLocaleLowerCase("es");
}

interface HistoryClaim {
    id: string;
    gig_id: string;
    gig_title?: string | null;
    gig_points?: number | null;
    points_awarded?: number | null;
    status: string;
    claimer_name?: string | null;
}

interface Offering {
    id: string;
    title: string;
    is_active: boolean;
    created_at?: string | null;
}

export interface GigHistoryGroup<C extends HistoryClaim, O extends Offering> {
    key: string;
    title: string;
    /** Newest first, in the order the caller supplied. */
    claims: C[];
    latest: C;
    count: number;
    /** Sum of approved pay (points_awarded, else gig_points; 1 pt = $1 MXN). */
    totalPaid: number;
    claimers: string[];
    /** Offering to prefill a repost from; null while the job is posted and active. */
    repostOffering: O | null;
}

/**
 * Group history claims (already sorted newest first) by job.
 * `offerings` may be plain offerings or `{ offering }` wrappers, active and inactive.
 */
export function groupGigHistory<C extends HistoryClaim, O extends Offering>(
    claims: C[],
    offerings: Array<O | { offering: O }>,
): GigHistoryGroup<C, O>[] {
    const allOfferings: O[] = offerings.map((item) =>
        "offering" in item && item.offering ? item.offering : (item as O),
    );
    const offeringById = new Map(allOfferings.map((o) => [o.id, o]));

    const byKey = new Map<string, C[]>();
    for (const c of claims) {
        const key = gigTitleKey(c.gig_title);
        const list = byKey.get(key);
        if (list) list.push(c);
        else byKey.set(key, [c]);
    }

    return [...byKey.entries()].map(([key, groupClaims]) => {
        const latest = groupClaims[0];
        const sameJob = allOfferings.filter((o) => gigTitleKey(o.title) === key);
        const alreadyPosted = sameJob.some((o) => o.is_active);
        const newestInactive = sameJob
            .filter((o) => !o.is_active)
            .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))[0];
        const ownOffering = offeringById.get(latest.gig_id);
        const repostOffering = alreadyPosted
            ? null
            : (ownOffering && !ownOffering.is_active ? ownOffering : newestInactive) ?? null;

        return {
            key,
            title: displayGigTitle(latest.gig_title),
            claims: groupClaims,
            latest,
            count: groupClaims.length,
            totalPaid: groupClaims
                .filter((c) => c.status === "approved")
                .reduce((sum, c) => sum + (c.points_awarded ?? c.gig_points ?? 0), 0),
            claimers: [...new Set(groupClaims.map((c) => c.claimer_name).filter(Boolean))] as string[],
            repostOffering,
        };
    });
}
