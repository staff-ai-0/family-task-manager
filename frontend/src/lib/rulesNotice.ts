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

/** Pages where the sheet never mounts (public / unauthenticated / kiosk / operator console), even with a stale session cookie. */
export const RULES_SHEET_SKIP_PATHS = [
    "/kiosk",
    "/admin",
    "/login",
    "/register",
    "/accept-invitation",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/privacidad",
    "/terminos",
    "/soporte",
    "/pricing",
    "/tdah",
    "/404",
    "/500",
] as const;

export function shouldSkipRulesSheet(pathname: string): boolean {
    if (pathname === "/") return true;
    return RULES_SHEET_SKIP_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/**
 * The rule lines, in display order. The per-chore bonus and the streak prize
 * are paid to teens only (backend: `maybe_award_early_bonus` and the streak
 * settle skip every other role), so those lines say so; each is left out when
 * its value is 0 (nothing to promise, no "+0 %" / "$0 MXN").
 */
export function rulesLines(rules: RulesValues, lang: Lang): string[] {
    const tiers = [...(rules.bonus_tiers ?? [])].sort((a, b) => a.early_pct - b.early_pct);
    const bonusOn = Number(rules.chore_bonus_pct) > 0;
    const streakOn = Number(rules.streak_cents) > 0;
    if (L(lang) === "en") {
        const ladder = tiers.map((t) => `${t.early_pct}% or more early: +${t.bonus_pct}%`).join(". ");
        return [
            `Early deadline: finish your chores before ${rules.deadline}.`,
            `Evening cutoff: at ${rules.cutoff} your open chores go up for grabs and do not count as done.`,
            `Up for grabs: until ${rules.grab_end}, any family member can take a chore that was left open.`,
            `Weekly pay: under ${rules.floor_pct}% of the week's chores done, no base pay; from ${rules.floor_pct}% to 99%, each completed chore pays.`,
            ...(tiers.length
                ? [`Weekly bonus: at 100% done, the bonus depends on the share finished before ${rules.deadline}. ${ladder}.`]
                : []),
            ...(bonusOn
                ? [`Per-chore bonus (teens): +${rules.chore_bonus_pct}% extra points on a chore completed before ${rules.deadline}.`]
                : []),
            `Reminders: teens get a nudge at ${rules.alarm_1} and again at ${rules.alarm_2}.`,
            ...(streakOn
                ? [`Streak prize (teens): ${pesos(rules.streak_cents)} MXN for every 3rd consecutive early week.`]
                : []),
        ];
    }
    const ladder = tiers.map((t) => `${t.early_pct} % o más temprano: +${t.bonus_pct} %`).join(". ");
    return [
        `Hora madrugadora: termina tus tareas antes de las ${rules.deadline}.`,
        `Hora de corte: a las ${rules.cutoff} tus tareas abiertas quedan para tomar y no cuentan como hechas.`,
        `Para tomar: hasta las ${rules.grab_end}, cualquier miembro de la familia puede tomar una tarea que quedó abierta.`,
        `Pago semanal: con menos de ${rules.floor_pct} % de las tareas de la semana, sin pago base; de ${rules.floor_pct} a 99 %, cada tarea completada paga.`,
        ...(tiers.length
            ? [`Bono semanal: con 100 % terminado, el bono depende de cuántas se hicieron antes de las ${rules.deadline}. ${ladder}.`]
            : []),
        ...(bonusOn
            ? [`Bono por tarea (adolescentes): +${rules.chore_bonus_pct} % de puntos extra en una tarea completada antes de las ${rules.deadline}.`]
            : []),
        `Recordatorios: los adolescentes reciben un aviso a las ${rules.alarm_1} y otro a las ${rules.alarm_2}.`,
        ...(streakOn
            ? [`Premio de racha (adolescentes): ${pesos(rules.streak_cents)} MXN por cada 3.ª semana madrugadora seguida.`]
            : []),
    ];
}

/**
 * `url` without its `rules` query parameter, as a same-origin path
 * (path + remaining query + hash) for `history.replaceState`. The sheet reads
 * `?rules=1` once; leaving it in the address bar would reopen the sheet on
 * every later reload, even after "Later".
 */
export function stripRulesParam(url: string): string {
    const u = new URL(url, "http://local.invalid");
    u.searchParams.delete("rules");
    const q = u.searchParams.toString();
    return `${u.pathname}${q ? `?${q}` : ""}${u.hash}`;
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

/** Toast after Announce. The server notifies only members still pending, so 0 means everyone already accepted. */
export function announceResultMessage(sent: number, lang: Lang): string {
    const n = Math.max(0, Math.trunc(Number(sent) || 0));
    const en = L(lang) === "en";
    if (n === 0) return en ? "Everyone has already accepted the rules." : "Todos ya aceptaron las reglas.";
    return en ? `Rules sent to ${n} member${n === 1 ? "" : "s"}.` : `Reglas enviadas a ${n} ${n === 1 ? "miembro" : "miembros"}.`;
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
    // Neutral voice: an automatic send (settings save) also starts the hour.
    if (code === "announce_too_soon") return en ? "The rules were sent less than an hour ago." : "Las reglas se enviaron hace menos de una hora.";
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
    es: { title: "Reglas de tareas", send: "Enviar reglas a quienes faltan", pending: "Faltan" },
    en: { title: "Chore rules", send: "Send rules to those pending", pending: "Pending" },
} as const;

export function cardCopy(lang: Lang) {
    return CARD[L(lang)];
}
