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
    streakPesos: number;
    cutoff: string;
    grabEnd: string;
    alarm1: string;
    alarm2: string;
}

export type EarlyBirdField = "deadline" | "days" | "bonus" | "streak" | "cutoff" | "grabEnd" | "alarms";
export type RulesField = "deadline" | "cutoff" | "grabEnd" | "alarms";
export type Lang = "es" | "en";

/** "HH:MM" -> minutes since midnight, or null when malformed. */
function clockMinutes(v: string): number | null {
    const m = /^(\d{2}):(\d{2})$/.exec(v);
    if (!m) return null;
    const h = Number(m[1]);
    const mm = Number(m[2]);
    if (h > 23 || mm > 59) return null;
    return h * 60 + mm;
}

const RULES_MSG = {
    es: {
        deadline: "La hora madrugadora va de 07:00 a 22:00, en pasos de 5 minutos.",
        cutoff: "La hora de corte va de 17:00 a 23:00, en pasos de 5 minutos, y debe ser después de la hora madrugadora.",
        grabEnd: "El fin de \"para tomar\" debe ser después de la hora de corte y a más tardar 23:30, en pasos de 5 minutos.",
        alarms: "Las alarmas van de 06:00 a la hora de corte, en pasos de 5 minutos, la primera antes que la segunda.",
    },
    en: {
        deadline: "The early deadline runs from 07:00 to 22:00 in 5-minute steps.",
        cutoff: "The cutoff runs from 17:00 to 23:00 in 5-minute steps and must be after the early deadline.",
        grabEnd: "The end of \"up for grabs\" must be after the cutoff and no later than 23:30, in 5-minute steps.",
        alarms: "Alarms run from 06:00 to the cutoff in 5-minute steps, the first before the second.",
    },
} as const;

export function rulesMessage(field: RulesField, lang: Lang): string {
    return RULES_MSG[lang === "en" ? "en" : "es"][field];
}

/** Mirrors the backend ranges (schemas/family.py + family_service.py) so the
 * form fails before the round trip. Returns the first problem, or null. */
export function validateRulesForm(
    v: { deadline: string; cutoff: string; grabEnd: string; alarm1: string; alarm2: string },
    lang: Lang,
): { field: RulesField; message: string } | null {
    const bad = (field: RulesField) => ({ field, message: rulesMessage(field, lang) });
    const step = (m: number | null) => m !== null && m % 5 === 0;
    const deadline = clockMinutes(v.deadline);
    if (!step(deadline) || deadline! < 7 * 60 || deadline! > 22 * 60) return bad("deadline");
    const cutoff = clockMinutes(v.cutoff);
    if (!step(cutoff) || cutoff! < 17 * 60 || cutoff! > 23 * 60 || cutoff! <= deadline!) return bad("cutoff");
    const grab = clockMinutes(v.grabEnd);
    if (!step(grab) || grab! <= cutoff! || grab! > 23 * 60 + 30) return bad("grabEnd");
    const a1 = clockMinutes(v.alarm1);
    const a2 = clockMinutes(v.alarm2);
    if (!step(a1) || !step(a2) || a1! < 6 * 60 || a2! > cutoff! || a1! >= a2!) return bad("alarms");
    return null;
}

const BASIC_MSG = {
    es: { days: "Elige al menos un día.", bonus: "El bono por tarea va de 0 a 100.", streak: "El premio va de 0 a 10,000 pesos." },
    en: { days: "Pick at least one day.", bonus: "The per-chore bonus is 0 to 100.", streak: "The prize is 0 to 10,000 pesos." },
} as const;

type PayloadResult =
    | { ok: true; body: Record<string, unknown> }
    | { ok: false; field: EarlyBirdField; message: string };

/** Returns the PATCH body, or the first invalid field with its message. */
export function buildPayload(f: EarlyBirdForm, lang: Lang = "es"): PayloadResult {
    const basic = BASIC_MSG[lang === "en" ? "en" : "es"];
    const rules = validateRulesForm(f, lang);
    if (rules?.field === "deadline") return { ok: false, ...rules };
    if (f.days.length === 0) return { ok: false, field: "days", message: basic.days };
    if (!Number.isInteger(f.bonusPct) || f.bonusPct < 0 || f.bonusPct > 100) return { ok: false, field: "bonus", message: basic.bonus };
    if (!Number.isInteger(f.streakPesos) || f.streakPesos < 0 || f.streakPesos > 10000) return { ok: false, field: "streak", message: basic.streak };
    if (rules) return { ok: false, ...rules };
    return {
        ok: true,
        body: {
            early_bird_enabled: f.enabled,
            early_bird_deadline: f.deadline,
            early_bird_days: daysToPayload(f.days),
            early_bird_bonus_pct: f.bonusPct,
            early_bird_streak_cents: pesosToCents(f.streakPesos),
            chore_cutoff: f.cutoff,
            grab_window_end: f.grabEnd,
            teen_alarm_1: f.alarm1,
            teen_alarm_2: f.alarm2,
        },
    };
}

/** The weekly ladder in five lines for the settings page (parent-facing). */
export function ladderExplainer(deadline: string, lang: Lang): string[] {
    return lang === "en"
        ? [
              "Under 60% of the week's chores done: no base pay.",
              "60-99%: each completed task pays.",
              `100% done: the weekly bonus depends on the share finished before ${deadline} (the early deadline):`,
              "80% or more early: +5%. 90% or more: +10%. 100% early: +15%.",
              "Chores left open after the cutoff go up for grabs and do not count as done.",
          ]
        : [
              "Menos de 60 % de las tareas de la semana: sin pago base.",
              "De 60 a 99 %: cada tarea completada paga.",
              `100 % terminado: el bono semanal depende de cuántas se hicieron antes de las ${deadline} (la hora madrugadora):`,
              "80 % o más temprano: +5 %. 90 % o más: +10 %. 100 % temprano: +15 %.",
              "Las tareas abiertas después de la hora de corte quedan para tomar y no cuentan como hechas.",
          ];
}

/** Parent-facing "today" line per teen (/api/early-bird/family). Worded for
 * the parent, so deliberately not the kid's dayLabel in lib/earlyBird.ts. */
const TEEN_TODAY = {
    es: { early: "Hoy: a tiempo", pending: "Hoy: en espera", open: "Hoy: en curso", missed: "Hoy: se pasó", neutral: "Hoy: sin tareas" },
    en: { early: "Today: on time", pending: "Today: waiting", open: "Today: in progress", missed: "Today: missed", neutral: "Today: no chores" },
} as const;

export function teenTodayLabel(state: unknown, lang: string): string {
    const labels: Record<string, string> = TEEN_TODAY[lang === "es" ? "es" : "en"];
    return typeof state === "string" ? labels[state] ?? "" : "";
}
