/**
 * UX-D2 badges view-model: names + emoji (the ONLY copy — thresholds live in
 * the backend's badge_service.py) and the shapes the progress sheet, profile
 * shelf, unlock celebration and parent hub render.
 */
export type Lang = "es" | "en";

// Key order = catalog order. The API decides which families a kid sees and in
// what order; a key missing here is skipped, never rendered half-blank.
export const BADGE_META: Record<string, { emoji: string; es: string; en: string }> = {
    chores: { emoji: "🧹", es: "Manos a la obra", en: "Hard Worker" },
    streak: { emoji: "🔥", es: "Racha imparable", en: "Unstoppable" },
    perfect_week: { emoji: "📅", es: "Semana perfecta", en: "Perfect Week" },
    extra_mile: { emoji: "🚀", es: "Milla extra", en: "Extra Mile" },
    gigs: { emoji: "💼", es: "Espíritu emprendedor", en: "Go-Getter" },
    saver: { emoji: "🐷", es: "Buen ahorro", en: "Smart Saver" },
    rewards: { emoji: "🎁", es: "Bien merecido", en: "Well Earned" },
    cup: { emoji: "🏆", es: "Copa familiar", en: "Cup Champion" },
};

export const TIER_NAMES: Record<Lang, readonly string[]> = {
    es: ["Bronce", "Plata", "Oro"],
    en: ["Bronze", "Silver", "Gold"],
};
export const MAX_TIER = 3;
export const CELEBRATION_MAX_TILES = 6;

const clampTier = (t: unknown) => Math.max(0, Math.min(MAX_TIER, Math.trunc(Number(t) || 0)));

export function stars(tier: number): string {
    const t = clampTier(tier);
    return "★".repeat(t) + "☆".repeat(MAX_TIER - t);
}

export interface BadgeTile {
    key: string;
    emoji: string;
    name: string;
    tier: number;
    stars: string;
    tierLabel: string;
    progressLabel: string;
    barPct: number;
    maxed: boolean;
}

export interface UnseenTile {
    key: string;
    emoji: string;
    name: string;
    tier: number;
    stars: string;
    tierName: string;
}

export interface BadgesView {
    tiles: BadgeTile[];
    /** Up to 3 non-maxed families, closest to their next tier first. */
    next: BadgeTile[];
    allMaxed: boolean;
    /** One tile per family with unseen tiers, at its highest unseen tier. */
    unseenTiles: UnseenTile[];
    /** Every unseen tier id behind unseenTiles (folded lower tiers included). */
    unseenIds: string[];
    headline: string | null;
    earnedTotal: number;
    totalLabel: string;
}

export function badgesView(resp: any, lang: Lang): BadgesView | null {
    if (!resp || resp.applies !== true || !Array.isArray(resp.badges)) return null;
    const es = lang === "es";

    const tiles: BadgeTile[] = [];
    const ratio = new Map<string, number>();
    for (const b of resp.badges) {
        const key = String(b?.badge ?? "");
        const meta = BADGE_META[key];
        if (!meta) continue;
        const tier = clampTier(b.tier);
        const count = Math.max(0, Math.trunc(Number(b.count) || 0));
        const target = b.next_target == null ? null : Math.max(1, Math.trunc(Number(b.next_target) || 1));
        const maxed = target == null;
        ratio.set(key, maxed ? 0 : count / target);
        tiles.push({
            key,
            emoji: meta.emoji,
            name: meta[lang],
            tier,
            stars: stars(tier),
            tierLabel: tier === 0
                ? (es ? "Aún sin ganar" : "Not earned yet")
                : `${TIER_NAMES[lang][tier - 1]} · ${tier}/${MAX_TIER}`,
            progressLabel: maxed ? (es ? "Máx" : "Max") : `${count}/${target}`,
            barPct: maxed ? 100 : Math.max(0, Math.min(100, Math.round((count / target) * 100))),
            maxed,
        });
    }

    const open = tiles.filter((t) => !t.maxed);
    const next = open
        .map((t, i) => ({ t, i }))
        .sort((a, b) => (ratio.get(b.t.key)! - ratio.get(a.t.key)!) || a.i - b.i)
        .slice(0, 3)
        .map((x) => x.t);

    const shown = new Set(tiles.map((t) => t.key));
    const topUnseen = new Map<string, number>();
    const unseenIds: string[] = [];
    for (const u of Array.isArray(resp.unseen) ? resp.unseen : []) {
        const key = String(u?.badge ?? "");
        const tier = clampTier(u?.tier);
        if (!shown.has(key) || tier === 0 || !u?.id) continue;
        unseenIds.push(String(u.id));
        topUnseen.set(key, Math.max(topUnseen.get(key) ?? 0, tier));
    }
    const unseenTiles: UnseenTile[] = tiles
        .filter((t) => topUnseen.has(t.key))
        .map((t) => {
            const tier = topUnseen.get(t.key)!;
            return { key: t.key, emoji: t.emoji, name: t.name, tier, stars: stars(tier), tierName: TIER_NAMES[lang][tier - 1] };
        });

    const n = unseenTiles.length;
    const headline = n === 0
        ? null
        : n === 1
            ? (es ? "¡Nueva insignia!" : "New badge!")
            : es ? `¡Ganaste ${n} insignias!` : `You earned ${n} badges!`;

    const earnedTotal = tiles.reduce((sum, t) => sum + t.tier, 0);
    const possible = tiles.length * MAX_TIER;
    return {
        tiles,
        next,
        allMaxed: tiles.length > 0 && open.length === 0,
        unseenTiles,
        unseenIds,
        headline,
        earnedTotal,
        totalLabel: es ? `${earnedTotal} de ${possible} ganadas` : `${earnedTotal} of ${possible} earned`,
    };
}

/**
 * Whether the batched badge-unlock modal may open on this load. Same welcome
 * tour rule as the rank-up (driver.js + a modal deadlocks touch input), and
 * never together with a rank-up celebration: one modal per page load, the
 * rank goes first and the badges wait for the next visit.
 */
export function shouldCelebrateBadges(
    view: BadgesView | null,
    rankCelebrating: boolean,
    completedWelcomeTour: boolean | null | undefined,
): boolean {
    return !!view && view.unseenTiles.length > 0 && view.unseenIds.length > 0
        && !rankCelebrating && completedWelcomeTour !== false;
}
