/**
 * UX-D1 progression view-model: rank names (the ONLY copy — thresholds live in
 * the backend) and the shapes the kid header, progress sheet, rank-up
 * celebration and parent hub render.
 */
export type Skin = "child" | "teen";
export type DayStateName = "none" | "done" | "missed" | "shield" | "today" | "future";

export const RANK_NAMES: Record<Skin, Record<"es" | "en", readonly string[]>> = {
    child: {
        es: ["Novato", "Ayudante", "Explorador", "Estrella", "Súper Ayudante", "Campeón", "Héroe", "Maestro", "Gran Maestro", "Leyenda"],
        en: ["Rookie", "Helper", "Explorer", "Star", "Super Helper", "Champion", "Hero", "Master", "Grand Master", "Legend"],
    },
    teen: {
        es: ["Novato", "Colaborador", "Confiable", "Pro", "Experto", "Especialista", "Capitán", "Élite", "Maestro", "Leyenda"],
        en: ["Rookie", "Contributor", "Reliable", "Pro", "Expert", "Specialist", "Captain", "Elite", "Master", "Legend"],
    },
};

const MAX_RANK = 10;
const clampRank = (r: number) => Math.max(1, Math.min(MAX_RANK, Math.trunc(Number(r) || 1)));

export function rankName(rank: number, skin: Skin, lang: "es" | "en"): string {
    return RANK_NAMES[skin][lang][clampRank(rank) - 1];
}

export interface ProgressView {
    streakLabel: string;
    rankLabel: string;
    barPct: number;
    toNextLabel: string;
    ladder: { rank: number; name: string; state: "done" | "current" | "locked" }[];
    week: { label: string; state: DayStateName }[];
    celebrateRank: number | null;
    celebrateName: string | null;
}

const DAY_LABELS = { es: ["L", "M", "M", "J", "V", "S", "D"], en: ["M", "T", "W", "T", "F", "S", "S"] };

export function progressView(resp: any, skin: Skin, lang: "es" | "en"): ProgressView | null {
    if (!resp || resp.applies !== true) return null;
    const es = lang === "es";
    const rank = clampRank(resp.rank);
    const xp = Number(resp.xp) || 0;
    const floor = Number(resp.rank_floor_xp) || 0;
    const next = resp.next_rank_xp == null ? null : Number(resp.next_rank_xp);
    const days = Number(resp.streak_days) || 0;
    const barPct = next == null ? 100 : Math.max(0, Math.min(100, Math.round(((xp - floor) / Math.max(1, next - floor)) * 100)));
    const toNextLabel = next == null
        ? (es ? "¡Rango máximo!" : "Top rank!")
        : es ? `${Math.max(0, next - xp)} XP para ${rankName(rank + 1, skin, lang)}` : `${Math.max(0, next - xp)} XP to ${rankName(rank + 1, skin, lang)}`;
    const celebrate = resp.celebrate_rank == null ? null : clampRank(resp.celebrate_rank);
    const week = Array.isArray(resp.week) ? resp.week.slice(0, 7) : [];
    return {
        streakLabel: es ? `🔥 ${days} ${days === 1 ? "día" : "días"}` : `🔥 ${days} ${days === 1 ? "day" : "days"}`,
        rankLabel: `${rankName(rank, skin, lang)} · ${rank}/${MAX_RANK}`,
        barPct,
        toNextLabel,
        ladder: Array.from({ length: MAX_RANK }, (_, i) => ({
            rank: i + 1,
            name: rankName(i + 1, skin, lang),
            state: i + 1 < rank ? "done" : i + 1 === rank ? "current" : "locked",
        })),
        week: week.map((d: any, i: number) => ({ label: DAY_LABELS[lang][i], state: String(d?.state ?? "none") as DayStateName })),
        celebrateRank: celebrate,
        celebrateName: celebrate == null ? null : rankName(celebrate, skin, lang),
    };
}

/** F4: the exact DOM values a live refresh (on `ftm:deck-empty`) writes into
 * KidHeader's pills/bar and ProgressSheet's streak heading. Pure mapping —
 * kept separate from the DOM-touching code in KidHeader.astro so it's
 * testable without a DOM. */
export interface ProgressDomUpdate {
    streak: string;
    rank: string;
    barWidthPct: number;
    barAriaLabel: string;
    sheetStreak: string;
}

export function progressDomUpdate(view: ProgressView): ProgressDomUpdate {
    return {
        streak: view.streakLabel,
        rank: view.rankLabel,
        barWidthPct: view.barPct,
        barAriaLabel: view.toNextLabel,
        sheetStreak: view.streakLabel,
    };
}

export function progressLine(kid: any, lang: "es" | "en"): string | null {
    if (kid?.rank == null || kid?.streak_days == null) return null;
    const skin: Skin = kid.role === "teen" ? "teen" : "child";
    return `🔥 ${Number(kid.streak_days) || 0} · ${rankName(kid.rank, skin, lang)}`;
}
