/**
 * Early Bird (11:00 chore deadline) kid/teen view-model. The ONLY place the
 * kid-facing copy lives; all numbers and states come from the backend
 * (`GET /api/early-bird/me`, early_bird_service.py).
 */
export type Lang = "es" | "en";

export const RUN_TARGET = 3;

export type DayState = "early" | "pending" | "open" | "missed" | "neutral" | "future";
export type CardState = "early" | "on_track" | "before_deadline" | "late" | "missed" | "idle";

export interface GrabItem {
    id: string;
    title: string;
    points: number;
    ownerName: string;
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
    weekPct: number;
    /** ISO instant the countdown runs to (cutoff, then deadline); "" when none. */
    targetAt: string;
    grabs: GrabItem[];
    takeBlock: string | null;
}

const COPY = {
    es: {
        title: "Madrugador",
        headlineOnTrack: "Termina a tiempo y gana extra",
        headlineBeforeDeadline: (d: string) => `Termina antes de las ${d} o tus tareas quedan libres`,
        headlineEarly: "¡Hoy fuiste madrugador!",
        headlineLate: "Hoy ya pasó la hora madrugadora",
        headlineMissed: "Hoy no se pudo madrugar",
        headlineIdle: "Sin tareas madrugadoras hoy",
        left: (c: string) => `Faltan ${c}`,
        run: "Racha de madrugador",
        bonus: (cents: string) => `${cents} de bono`,
        weekPct: (pct: number) => `+${pct}% en tu pago`,
        grabsTitle: "Para tomar",
        grabsHint: "Tareas de otros que puedes tomar",
        take: "Tomar",
        from: (name: string) => `de ${name}`,
        taken: "¡Tarea tomada!",
        takeFailed: "No se pudo tomar la tarea",
        dayGlyph: { early: "✓", pending: "…", open: "○", missed: "✗", neutral: "–", future: "·" },
        dayLabel: { early: "Madrugaste", pending: "En revisión", open: "Hoy", missed: "Sin madrugar", neutral: "Sin tareas", future: "Pendiente" },
        paycheck: (pct: number) => `incl. +${pct}% madrugador`,
        errors: {
            already_taken: "Otra persona ya tomó esta tarea",
            finish_yours_first: "Termina primero tus tareas",
            role_not_allowed: "Tu perfil no puede tomar esta tarea",
            own_chore: "Esta tarea ya es tuya",
            not_grabbable: "Esta tarea ya no se puede tomar",
            not_kid: "Solo los hijos pueden tomar tareas",
        } as Record<string, string>,
    },
    en: {
        title: "Early bird",
        headlineOnTrack: "Finish on time and earn extra",
        headlineBeforeDeadline: (d: string) => `Finish before ${d} or your chores go up for grabs`,
        headlineEarly: "You were an early bird today!",
        headlineLate: "Today's early window has passed",
        headlineMissed: "No early bird today",
        headlineIdle: "No early chores today",
        left: (c: string) => `${c} left`,
        run: "Early bird run",
        bonus: (cents: string) => `${cents} bonus`,
        weekPct: (pct: number) => `+${pct}% on your pay`,
        grabsTitle: "Up for grabs",
        grabsHint: "Other people's chores you can take",
        take: "Take",
        from: (name: string) => `from ${name}`,
        taken: "Chore taken!",
        takeFailed: "Couldn't take the chore",
        dayGlyph: { early: "✓", pending: "…", open: "○", missed: "✗", neutral: "–", future: "·" },
        dayLabel: { early: "Early", pending: "In review", open: "Today", missed: "Missed", neutral: "No chores", future: "Upcoming" },
        paycheck: (pct: number) => `incl. +${pct}% early bird`,
        errors: {
            already_taken: "Someone else already took this chore",
            finish_yours_first: "Finish your own chores first",
            role_not_allowed: "Your profile can't take this chore",
            own_chore: "This chore is already yours",
            not_grabbable: "This chore can't be taken anymore",
            not_kid: "Only kids can take chores",
        } as Record<string, string>,
    },
} as const;

export function earlyBirdCopy(lang: Lang) {
    return COPY[lang === "en" ? "en" : "es"];
}

/** "45 min" / "1 h 05 min"; never negative. */
export function countdownLabel(target: Date, now: Date, _lang: Lang): string {
    const mins = Math.max(0, Math.floor((target.getTime() - now.getTime()) / 60000));
    if (mins < 60) return `${mins} min`;
    const h = Math.floor(mins / 60);
    return `${h} h ${String(mins % 60).padStart(2, "0")} min`;
}

export function takeErrorMessage(detail: string, lang: Lang): string {
    const c = earlyBirdCopy(lang);
    return c.errors[detail] ?? c.takeFailed;
}

/** Why the caller can take none of the grabs (`take_block` from the API), or
 * null. Lets the list disable its Take buttons instead of failing on tap. */
export function takeBlockHint(block: string | null | undefined, lang: Lang): string | null {
    if (!block) return null;
    return takeErrorMessage(block, lang);
}

/** "incl. +5% early bird" when the projected paycheck carries a bonus. */
export function paycheckBonusLine(bonusCents: unknown, pct: unknown, lang: Lang): string | null {
    const cents = Number(bonusCents) || 0;
    const p = Math.round(Number(pct) || 0);
    if (cents <= 0 || p <= 0) return null;
    return earlyBirdCopy(lang).paycheck(p);
}

const parse = (iso: unknown): Date | null => {
    if (typeof iso !== "string" || !iso) return null;
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
};

const money = (cents: number, lang: Lang) =>
    `$${Math.round(cents / 100).toLocaleString(lang === "es" ? "es-MX" : "en-US")}`;

export function earlyBirdView(me: any, lang: Lang, now: Date): EarlyBirdView | null {
    const grabsRaw: any[] = Array.isArray(me?.grabs) ? me.grabs : [];
    const applies = me?.applies === true;
    if (!applies && grabsRaw.length === 0) return null;

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
            if (cutoff && now.getTime() < cutoff.getTime()) state = "on_track";
            else if (deadline && now.getTime() < deadline.getTime()) state = "before_deadline";
            else state = "late";
        }
        // Nothing left open: a "missed" day just was not early (state stays "missed").
    }

    const headline = {
        early: c.headlineEarly,
        on_track: c.headlineOnTrack,
        before_deadline: c.headlineBeforeDeadline(String(me?.deadline ?? "")),
        late: c.headlineLate,
        missed: c.headlineMissed,
        idle: c.headlineIdle,
    }[state];

    const target = state === "on_track" ? cutoff : state === "before_deadline" ? deadline : null;
    const countdown = target ? countdownLabel(target, now, lang) : "";

    const dots: DotView[] = (Array.isArray(me?.week) ? me.week : []).map((w: any) => {
        const s = (w?.state in c.dayGlyph ? w.state : "future") as DayState;
        return { date: String(w?.date ?? ""), state: s, glyph: c.dayGlyph[s], label: c.dayLabel[s] };
    });

    const run = Math.max(0, Math.trunc(Number(me?.run_weeks) || 0)) % RUN_TARGET;
    const streakCents = Math.max(0, Math.trunc(Number(me?.streak_cents) || 0));

    return {
        applies,
        state,
        headline,
        countdown,
        countdownText: countdown ? c.left(countdown) : "",
        deadlineLabel: String(me?.deadline ?? ""),
        dots,
        runText: `${run}/${RUN_TARGET}`,
        runLabel: c.run,
        bonusLabel: streakCents > 0 ? c.bonus(money(streakCents, lang)) : "",
        weekPct: Math.max(0, Math.round(Number(me?.week_pct) || 0)),
        targetAt: target ? target.toISOString() : "",
        grabs: grabsRaw.map((g) => ({
            id: String(g.assignment_id),
            title: String(g.title ?? ""),
            points: Math.max(0, Math.trunc(Number(g.points) || 0)),
            ownerName: String(g.owner_name ?? ""),
        })),
        takeBlock: me?.take_block ? String(me.take_block) : null,
    };
}
