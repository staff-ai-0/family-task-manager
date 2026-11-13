/**
 * Early Bird (early chore deadline) kid/teen view-model. The ONLY place the
 * kid-facing copy lives; all numbers and states come from the backend
 * (`GET /api/early-bird/me`, early_bird_service.py).
 */
export type Lang = "es" | "en";

export type DayState = "early" | "pending" | "open" | "missed" | "neutral" | "future";
/** on_track = before the early deadline; before_cutoff = past it but the
 * chore is still the kid's until the evening cutoff; late = past the cutoff. */
export type CardState = "early" | "on_track" | "before_cutoff" | "late" | "missed" | "idle";

export type LadderTier = "neutral" | "no_pay" | "per_task" | "bonus";
export interface WeekLadder {
    completed_pct: number;
    early_pct: number;
    tier: LadderTier | string;
    bonus_pct: number;
    final: boolean;
}

export interface GrabItem {
    id: string;
    title: string;
    points: number;
    ownerName: string;
    /** False when the caller cannot take it (parents' list; kids' /me rows are always takeable). */
    canTake: boolean;
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
    /** ISO instant the countdown runs to (deadline, then cutoff); "" when none. */
    targetAt: string;
    grabs: GrabItem[];
    takeBlock: string | null;
}

const COPY = {
    es: {
        title: "Madrugador",
        headlineOnTrack: (d: string) => `Termina antes de las ${d} y gana extra`,
        headlineBeforeCutoff: "Tus tareas siguen siendo tuyas hasta la hora de corte; después quedan libres para la familia",
        headlineEarly: "¡Hoy fuiste madrugador!",
        headlineLate: "Tus tareas abiertas ya quedaron libres para la familia",
        headlineMissed: "Hoy no se pudo madrugar",
        headlineIdle: "Sin tareas madrugadoras hoy",
        left: (c: string) => `Faltan ${c}`,
        run: "Racha de madrugador",
        bonus: (cents: string) => `${cents} de bono`,
        grabsTitle: "Para tomar",
        grabsHint: "Tareas de otros que puedes tomar",
        grabsHintParent: "Tareas que quedaron libres para la familia. Quien las toma gana los puntos",
        take: "Tomar",
        from: (name: string) => `de ${name}`,
        taken: "¡Tarea tomada!",
        takeFailed: "No se pudo tomar la tarea",
        takeConfirmTitle: "¿Tomar esta tarea?",
        takeConfirmBody: "Quedará a tu nombre y no se puede deshacer.",
        dayGlyph: { early: "✓", pending: "…", open: "○", missed: "✗", neutral: "–", future: "·" },
        dayLabel: { early: "Madrugaste", pending: "En revisión", open: "Hoy", missed: "Sin madrugar", neutral: "Sin tareas", future: "Pendiente" },
        paycheck: (pct: number) => `incl. +${pct}% madrugador`,
        errors: {
            already_taken: "Otra persona ya tomó esta tarea",
            grab_window_closed: "Ya no es horario para tomar tareas",
            not_eligible: "Ahora no puedes tomar esta tarea",
            own_chore: "Esta tarea ya es tuya",
            role_not_allowed: "Tu perfil no puede tomar esta tarea",
            not_grabbable: "Esta tarea ya no se puede tomar",
        } as Record<string, string>,
    },
    en: {
        title: "Early bird",
        headlineOnTrack: (d: string) => `Finish before ${d} and earn extra`,
        headlineBeforeCutoff: "Your chores stay yours until the evening cutoff, then they open to the family",
        headlineEarly: "You were an early bird today!",
        headlineLate: "Your open chores are open to the family now",
        headlineMissed: "No early bird today",
        headlineIdle: "No early chores today",
        left: (c: string) => `${c} left`,
        run: "Early bird run",
        bonus: (cents: string) => `${cents} bonus`,
        grabsTitle: "Up for grabs",
        grabsHint: "Other people's chores you can take",
        grabsHintParent: "Chores that are open to the family. Whoever takes one earns the points",
        take: "Take",
        from: (name: string) => `from ${name}`,
        taken: "Chore taken!",
        takeFailed: "Couldn't take the chore",
        takeConfirmTitle: "Take this chore?",
        takeConfirmBody: "It will be yours and it can't be undone.",
        dayGlyph: { early: "✓", pending: "…", open: "○", missed: "✗", neutral: "–", future: "·" },
        dayLabel: { early: "Early", pending: "In review", open: "Today", missed: "Missed", neutral: "No chores", future: "Upcoming" },
        paycheck: (pct: number) => `incl. +${pct}% early bird`,
        errors: {
            already_taken: "Someone else already took this chore",
            grab_window_closed: "It's not time to take chores right now",
            not_eligible: "You can't take this chore right now",
            own_chore: "This chore is already yours",
            role_not_allowed: "Your profile can't take this chore",
            not_grabbable: "This chore can't be taken anymore",
        } as Record<string, string>,
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

export function takeErrorMessage(detail: string, lang: Lang): string {
    const c = earlyBirdCopy(lang);
    return c.errors[detail] ?? c.takeFailed;
}

/** The reason key of a failed take: the API's error body carries it in
 * "message" (FamilyAppException handlers) or "detail" (FastAPI). */
export function takeErrorReason(body: any): string {
    const reason = body?.message ?? body?.detail;
    return typeof reason === "string" ? reason : "";
}

/** Progress toward the next streak payout: run_weeks modulo the API's
 * streak_weeks (the backend STREAK_WEEKS — never a copy here). Works on the
 * kid's /me payload and on a /family teen row alike. */
export function runProgress(src: any): { done: number; target: number } {
    const target = Math.max(0, Math.trunc(Number(src?.streak_weeks) || 0));
    if (!target) return { done: 0, target: 0 };
    return { done: Math.max(0, Math.trunc(Number(src?.run_weeks) || 0)) % target, target };
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

/** Rows of /api/early-bird/grabs (or the `grabs` of /me) as list items. */
export function grabItems(rows: unknown, lang: Lang): GrabItem[] {
    if (!Array.isArray(rows)) return [];
    return rows.map((g: any) => ({
        id: String(g.assignment_id),
        title: String((lang === "es" && g.title_es) || g.title || ""),
        points: Math.max(0, Math.trunc(Number(g.points) || 0)),
        ownerName: String(g.owner_name ?? ""),
        canTake: g.can_take !== false,
    }));
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
            if (deadline && now.getTime() < deadline.getTime()) state = "on_track";
            else if (cutoff && now.getTime() < cutoff.getTime()) state = "before_cutoff";
            else state = "late";
        }
        // Nothing left open: a "missed" day just was not early (state stays "missed").
    }

    const headline = {
        early: c.headlineEarly,
        on_track: c.headlineOnTrack(String(me?.deadline ?? "11:00")),
        before_cutoff: c.headlineBeforeCutoff,
        late: c.headlineLate,
        missed: c.headlineMissed,
        idle: c.headlineIdle,
    }[state];

    const target = state === "on_track" ? deadline : state === "before_cutoff" ? cutoff : null;
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
        grabs: grabItems(grabsRaw, lang),
        takeBlock: me?.take_block ? String(me.take_block) : null,
    };
}
