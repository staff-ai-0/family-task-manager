/** Parent settings helpers for Early Bird: chips <-> payload, pesos <-> cents, validation. */

/** All seven days on means "every day", which the API wants as null. */
export function daysToPayload(selected: number[]): number[] | null {
    const days = [...new Set(selected)].filter((d) => Number.isInteger(d) && d >= 0 && d <= 6).sort((a, b) => a - b);
    return days.length === 7 ? null : days;
}

export function daysFromFamily(days: unknown): number[] {
    if (!Array.isArray(days)) return [0, 1, 2, 3, 4, 5, 6];
    return days.filter((d): d is number => Number.isInteger(d) && d >= 0 && d <= 6);
}

export function pesosToCents(pesos: number): number {
    return Math.round(pesos * 100);
}

export function centsToPesos(cents: unknown): number {
    const n = Number(cents);
    return Number.isFinite(n) ? Math.round(n / 100) : 0;
}

export interface EarlyBirdForm {
    enabled: boolean;
    deadline: string;
    days: number[];
    bonusPct: number;
    weekPct: number;
    streakPesos: number;
}

export type EarlyBirdField = "deadline" | "days" | "bonus" | "week" | "streak";

/** Returns the PATCH body, or the first invalid field. */
export function buildPayload(f: EarlyBirdForm): { ok: true; body: Record<string, unknown> } | { ok: false; field: EarlyBirdField } {
    const m = /^(\d{2}):(\d{2})$/.exec(f.deadline);
    if (!m) return { ok: false, field: "deadline" };
    const mins = Number(m[1]) * 60 + Number(m[2]);
    if (mins < 7 * 60 || mins > 22 * 60 || Number(m[2]) % 5 !== 0) return { ok: false, field: "deadline" };
    if (f.days.length === 0) return { ok: false, field: "days" };
    if (!Number.isInteger(f.bonusPct) || f.bonusPct < 0 || f.bonusPct > 100) return { ok: false, field: "bonus" };
    if (!Number.isInteger(f.weekPct) || f.weekPct < 0 || f.weekPct > 50) return { ok: false, field: "week" };
    if (!Number.isInteger(f.streakPesos) || f.streakPesos < 0 || f.streakPesos > 10000) return { ok: false, field: "streak" };
    return {
        ok: true,
        body: {
            early_bird_enabled: f.enabled,
            early_bird_deadline: f.deadline,
            early_bird_days: daysToPayload(f.days),
            early_bird_bonus_pct: f.bonusPct,
            early_bird_week_pct: f.weekPct,
            early_bird_streak_cents: pesosToCents(f.streakPesos),
        },
    };
}
