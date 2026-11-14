/**
 * Chore-rules acceptance copy (ES + EN). Pure: no DOM, no fetch. The ONLY place
 * this copy lives. Every number is rendered from the family's rule values
 * (`GET /api/rules/status` -> rules), never hardcoded, so the text the member
 * accepts is the text the backend computes with.
 */
export type Lang = "es" | "en";

export interface RulesValues {
    version?: number;
    deadline: string;
    cutoff: string;
    grab_end: string;
    alarm_1: string;
    alarm_2: string;
    streak_cents: number;
    chore_bonus_pct: number;
    floor_pct: number;
    bonus_tiers: { early_pct: number; bonus_pct: number }[];
}

export interface AcceptanceRow {
    user_id?: string;
    name: string;
    role?: string;
    accepted_at: string | null;
}

const L = (lang: string): Lang => (lang === "en" ? "en" : "es");

/** Integer pesos from cents (floor), "$380" style. No floats. */
function pesos(cents: number): string {
    const n = Math.trunc(Number(cents) || 0);
    return `$${Math.trunc(n / 100)}`;
}

export function rulesLines(rules: RulesValues, lang: Lang): string[] {
    const tiers = [...(rules.bonus_tiers ?? [])].sort((a, b) => a.early_pct - b.early_pct);
    if (L(lang) === "en") {
        const ladder = tiers.map((t) => `${t.early_pct}% or more early: +${t.bonus_pct}%`).join(". ");
        return [
            `Early deadline: finish your chores before ${rules.deadline}.`,
            `Evening cutoff: at ${rules.cutoff} your open chores go up for grabs and do not count as done.`,
            `Up for grabs: until ${rules.grab_end}, any family member can take a chore that was left open.`,
            `Weekly pay: under ${rules.floor_pct}% of the week's chores done, no base pay; from ${rules.floor_pct}% to 99%, each completed chore pays.`,
            `Weekly bonus: at 100% done, the bonus depends on the share finished before ${rules.deadline}. ${ladder}.`,
            `Per-chore bonus: +${rules.chore_bonus_pct}% extra points on a chore completed before ${rules.deadline}.`,
            `Reminders: teens get a nudge at ${rules.alarm_1} and again at ${rules.alarm_2}.`,
            `Streak prize: ${pesos(rules.streak_cents)} MXN for every 3rd consecutive early week.`,
        ];
    }
    const ladder = tiers.map((t) => `${t.early_pct} % o más temprano: +${t.bonus_pct} %`).join(". ");
    return [
        `Hora madrugadora: termina tus tareas antes de las ${rules.deadline}.`,
        `Hora de corte: a las ${rules.cutoff} tus tareas abiertas quedan para tomar y no cuentan como hechas.`,
        `Para tomar: hasta las ${rules.grab_end}, cualquier miembro de la familia puede tomar una tarea que quedó abierta.`,
        `Pago semanal: con menos de ${rules.floor_pct} % de las tareas de la semana, sin pago base; de ${rules.floor_pct} a 99 %, cada tarea completada paga.`,
        `Bono semanal: con 100 % terminado, el bono depende de cuántas se hicieron antes de las ${rules.deadline}. ${ladder}.`,
        `Bono por tarea: +${rules.chore_bonus_pct} % de puntos extra en una tarea completada antes de las ${rules.deadline}.`,
        `Recordatorios: los adolescentes reciben un aviso a las ${rules.alarm_1} y otro a las ${rules.alarm_2}.`,
        `Premio de racha: ${pesos(rules.streak_cents)} MXN por cada 3.ª semana madrugadora seguida.`,
    ];
}

export function acceptLabel(lang: Lang): string {
    return L(lang) === "en"
        ? "I understand the rules and accept them; I won't make future claims about results calculated under them."
        : "Entiendo las reglas y las acepto; no haré reclamos futuros sobre resultados calculados con ellas.";
}

export function statusSummary(rows: AcceptanceRow[], lang: Lang): string {
    if (!rows.length) return "";
    const done = rows.filter((r) => !!r.accepted_at).length;
    return L(lang) === "en" ? `${done} of ${rows.length} accepted` : `${done} de ${rows.length} aceptaron`;
}

export function pendingNames(rows: AcceptanceRow[]): string[] {
    return rows.filter((r) => !r.accepted_at).map((r) => r.name);
}

export function announceResultMessage(sent: number, lang: Lang): string {
    const n = Math.max(0, Math.trunc(Number(sent) || 0));
    return L(lang) === "en" ? `Rules sent to ${n} member${n === 1 ? "" : "s"}.` : `Reglas enviadas a ${n} ${n === 1 ? "miembro" : "miembros"}.`;
}

export function acceptErrorMessage(code: string, lang: Lang): string {
    const en = L(lang) === "en";
    if (code === "stale_version") {
        return en ? "The rules changed, please read the new version." : "Las reglas cambiaron, mira la versión nueva.";
    }
    return en ? "Couldn't save your acceptance. Please try again." : "No se pudo guardar tu aceptación. Intenta de nuevo.";
}

export function announceErrorMessage(code: string, lang: Lang): string {
    const en = L(lang) === "en";
    if (code === "early_bird_off") return en ? "Turn on Early Bird to send the rules." : "Activa Madrugador para enviar las reglas.";
    if (code === "announce_too_soon") return en ? "You sent them less than an hour ago." : "Ya las enviaste hace menos de una hora.";
    return en ? "Couldn't send the rules. Please try again." : "No se pudieron enviar las reglas. Intenta de nuevo.";
}

const SHEET = {
    es: { title: "Reglas de tareas", accept: "Aceptar", later: "Más tarde", saved: "Gracias, reglas aceptadas." },
    en: { title: "Chore rules", accept: "Accept", later: "Later", saved: "Thanks, rules accepted." },
} as const;

export function sheetCopy(lang: Lang) {
    return SHEET[L(lang)];
}

const CARD = {
    es: { title: "Reglas de tareas", send: "Enviar reglas a todos", pending: "Faltan" },
    en: { title: "Chore rules", send: "Send rules to everyone", pending: "Pending" },
} as const;

export function cardCopy(lang: Lang) {
    return CARD[L(lang)];
}
