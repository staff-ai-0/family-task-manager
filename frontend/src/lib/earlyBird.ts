/**
 * Early Bird (early chore deadline) kid/teen view-model. The ONLY place the
 * kid-facing copy lives; all numbers and states come from the backend
 * (`GET /api/early-bird/me`, early_bird_service.py).
 */
export type Lang = "es" | "en";

export type DayState = "early" | "pending" | "open" | "missed" | "neutral" | "future";
/** on_track = before the early deadline; before_cutoff = past it, the chores
 * are still the kid's to report until the day ends (midnight). There is no
 * "late": a chore is never released to the family. */
export type CardState = "early" | "on_track" | "before_cutoff" | "missed" | "idle";

export type LadderTier = "neutral" | "no_pay" | "per_task" | "bonus";
export interface WeekLadder {
    completed_pct: number;
    early_pct: number;
    tier: LadderTier | string;
    bonus_pct: number;
    final: boolean;
}

export interface DotView {
    date: string;
    state: DayState;
    glyph: string;
    label: string;
}

export interface EarlyBirdView {
    applies: boolean;
    state: CardState;
    headline: string;
    countdown: string;
    countdownText: string;
    deadlineLabel: string;
    dots: DotView[];
    runText: string;
    runLabel: string;
    bonusLabel: string;
    /** Weekly ladder sentence (see ladderMessage); "" when the week has no chores. */
    ladderText: string;
    /** Paycheck bonus % already earned this week (0 / 5 / 10 / 15). */
    paycheckBonusPct: number;
    /** ISO instant the countdown runs to (deadline, then the end of the day); "" when none. */
    targetAt: string;
}

const COPY = {
    es: {
        title: "Madrugador",
        headlineOnTrack: (d: string) => `Termina antes de las ${d} y gana extra`,
        headlineBeforeCutoff: "Tus tareas de hoy siguen abiertas hasta la medianoche",
        headlineEarly: "¡Hoy fuiste madrugador!",
        headlineMissed: "Hoy no se pudo madrugar",
        headlineIdle: "Sin tareas madrugadoras hoy",
        left: (c: string) => `Faltan ${c}`,
        run: "Racha de madrugador",
        bonus: (cents: string) => `${cents} de bono`,
        dayGlyph: { early: "✓", pending: "…", open: "○", missed: "✗", neutral: "–", future: "·" },
        dayLabel: { early: "Madrugaste", pending: "En revisión", open: "Hoy", missed: "Sin madrugar", neutral: "Sin tareas", future: "Pendiente" },
        paycheck: (pct: number) => `incl. +${pct}% madrugador`,
    },
    en: {
        title: "Early bird",
        headlineOnTrack: (d: string) => `Finish before ${d} and earn extra`,
        headlineBeforeCutoff: "Today's chores stay open until midnight",
        headlineEarly: "You were an early bird today!",
        headlineMissed: "No early bird today",
        headlineIdle: "No early chores today",
        left: (c: string) => `${c} left`,
        run: "Early bird run",
        bonus: (cents: string) => `${cents} bonus`,
        dayGlyph: { early: "✓", pending: "…", open: "○", missed: "✗", neutral: "–", future: "·" },
        dayLabel: { early: "Early", pending: "In review", open: "Today", missed: "Missed", neutral: "No chores", future: "Upcoming" },
        paycheck: (pct: number) => `incl. +${pct}% early bird`,
    },
} as const;

export function earlyBirdCopy(lang: Lang) {
    return COPY[lang === "en" ? "en" : "es"];
}

/** "45 min" / "1 h 05 min"; never negative. */
export function countdownLabel(target: Date, now: Date): string {
    const mins = Math.max(0, Math.floor((target.getTime() - now.getTime()) / 60000));
    if (mins < 60) return `${mins} min`;
    const h = Math.floor(mins / 60);
    return `${h} h ${String(mins % 60).padStart(2, "0")} min`;
}

/** Progress toward the next streak payout: run_weeks modulo the API's
 * streak_weeks (the backend STREAK_WEEKS — never a copy here). Works on the
 * kid's /me payload and on a /family teen row alike. */
export function runProgress(src: any): { done: number; target: number } {
    const target = Math.max(0, Math.trunc(Number(src?.streak_weeks) || 0));
    if (!target) return { done: 0, target: 0 };
    return { done: Math.max(0, Math.trunc(Number(src?.run_weeks) || 0)) % target, target };
}

/** "incl. +5% early bird" when the projected paycheck carries a bonus. */
export function paycheckBonusLine(bonusCents: unknown, pct: unknown, lang: Lang): string | null {
    const cents = Number(bonusCents) || 0;
    const p = Math.round(Number(pct) || 0);
    if (cents <= 0 || p <= 0) return null;
    return earlyBirdCopy(lang).paycheck(p);
}

/** Reason lines under an outstanding-week row on /parent/payouts, from the
 * week dict's ladder fields. Only what the dict carries. */
export function payoutWeekNotes(w: any, lang: Lang): string[] {
    const es = lang !== "en";
    const notes: string[] = [];
    if (w?.ladder_tier === "no_pay") {
        notes.push(es ? "Menos de 60 % completado — sin pago base" : "Under 60% completed — no base pay");
    }
    // A neutral week (Early Bird off, or a kid the ladder does not cover) is
    // never final by construction, but nothing about it is pending either.
    if (w?.ladder_final === false && w?.is_current_week === false && w?.ladder_tier !== "neutral") {
        notes.push(es ? "Pendiente de revisión — semana provisional" : "Pending review — provisional week");
    }
    return notes;
}

const LADDER = {
    es: {
        noPay: (p: number) => `Llevas ${p} %: necesitas 60 % para cobrar`,
        perTask: (p: number) => `Llevas ${p} %: cada tarea que termines paga. Con 100 % te ganas el bono madrugador`,
        bonus: (earned: number, next: number | null, nextAt: number, dl: string) =>
            (earned > 0 ? `Vas con +${earned} % de madrugador` : "Semana completa al 100 %") +
            (next ? `. +${next} % si ${nextAt} % antes de ${dl ? `las ${dl}` : "la hora madrugadora"}` : ""),
        closed: (p: number, tail: string) => `Semana cerrada: ${p} % — ${tail}`,
        closedNoPay: "sin pago base",
        closedPerTask: "cada tarea pagó",
        closedBonus: (b: number) => (b > 0 ? `+${b} % de madrugador` : "sin bono madrugador"),
    },
    en: {
        noPay: (p: number) => `You're at ${p}%: you need 60% to get paid`,
        perTask: (p: number) => `You're at ${p}%: every task you finish pays. Hit 100% to unlock the early bird bonus`,
        bonus: (earned: number, next: number | null, nextAt: number, dl: string) =>
            (earned > 0 ? `You're on +${earned}% early bird` : "Week complete at 100%") +
            (next ? `. +${next}% if ${nextAt}% before ${dl || "the early deadline"}` : ""),
        closed: (p: number, tail: string) => `Week closed: ${p}% — ${tail}`,
        closedNoPay: "no base pay",
        closedPerTask: "each task paid",
        closedBonus: (b: number) => (b > 0 ? `+${b}% early bird` : "no early bird bonus"),
    },
} as const;

/** The kid's weekly paycheck status in one sentence, from `week_ladder`. */
export function ladderMessage(ladder: Partial<WeekLadder> | null | undefined, lang: Lang, deadline = ""): string {
    if (!ladder || ladder.tier === "neutral" || !ladder.tier) return "";
    const t = LADDER[lang === "en" ? "en" : "es"];
    const pct = Math.max(0, Math.min(100, Math.trunc(Number(ladder.completed_pct) || 0)));
    const earned = Math.max(0, Math.trunc(Number(ladder.bonus_pct) || 0));
    if (ladder.final) {
        if (ladder.tier === "no_pay") return t.closed(pct, t.closedNoPay);
        if (ladder.tier === "per_task") return t.closed(pct, t.closedPerTask);
        return t.closed(pct, t.closedBonus(earned));
    }
    if (ladder.tier === "no_pay") return t.noPay(pct);
    if (ladder.tier === "per_task") return t.perTask(pct);
    // bonus tier: 80 % early -> +5, 90 % -> +10, 100 % -> +15
    const next = earned < 5 ? [5, 80] : earned < 10 ? [10, 90] : earned < 15 ? [15, 100] : null;
    return t.bonus(earned, next ? next[0] : null, next ? next[1] : 0, deadline);
}

const parse = (iso: unknown): Date | null => {
    if (typeof iso !== "string" || !iso) return null;
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
};

const money = (cents: number, lang: Lang) =>
    `$${Math.round(cents / 100).toLocaleString(lang === "es" ? "es-MX" : "en-US")}`;

export function earlyBirdView(me: any, lang: Lang, now: Date): EarlyBirdView | null {
    // Teens only: for everyone else there is nothing to show.
    const applies = me?.applies === true;
    if (!applies) return null;

    const c = earlyBirdCopy(lang);
    const cutoff = parse(me?.cutoff_at);
    const deadline = parse(me?.deadline_at);
    const today = String(me?.today ?? "");

    let state: CardState = "idle";
    if (today === "missed") state = "missed";
    if (today === "early" || today === "pending") state = "early";
    else if (today === "open" || today === "missed") {
        const openCount = Math.max(0, Math.trunc(Number(me?.open_today) || 0));
        if (openCount > 0) {
            // Past the early deadline the chores are still the kid's all day.
            state = deadline && now.getTime() < deadline.getTime() ? "on_track" : "before_cutoff";
        }
        // Nothing left open: a "missed" day just was not early (state stays "missed").
    }

    const headline = {
        early: c.headlineEarly,
        on_track: c.headlineOnTrack(String(me?.deadline ?? "11:00")),
        before_cutoff: c.headlineBeforeCutoff,
        missed: c.headlineMissed,
        idle: c.headlineIdle,
    }[state];

    const dayEnd = cutoff && now.getTime() < cutoff.getTime() ? cutoff : null;
    const target = state === "on_track" ? deadline : state === "before_cutoff" ? dayEnd : null;
    const countdown = target ? countdownLabel(target, now) : "";

    const dots: DotView[] = (Array.isArray(me?.week) ? me.week : []).map((w: any) => {
        const s = (w?.state in c.dayGlyph ? w.state : "future") as DayState;
        return { date: String(w?.date ?? ""), state: s, glyph: c.dayGlyph[s], label: c.dayLabel[s] };
    });

    const run = runProgress(me);
    const streakCents = Math.max(0, Math.trunc(Number(me?.streak_cents) || 0));

    return {
        applies,
        state,
        headline,
        countdown,
        countdownText: countdown ? c.left(countdown) : "",
        deadlineLabel: String(me?.deadline ?? ""),
        dots,
        runText: run.target ? `${run.done}/${run.target}` : "",
        runLabel: c.run,
        bonusLabel: streakCents > 0 ? c.bonus(money(streakCents, lang)) : "",
        ladderText: ladderMessage(me?.week_ladder, lang, String(me?.deadline ?? "")),
        paycheckBonusPct: Math.max(0, Math.trunc(Number(me?.week_ladder?.bonus_pct) || 0)),
        targetAt: target ? target.toISOString() : "",
    };
}
