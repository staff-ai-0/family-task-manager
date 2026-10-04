/** UX-E1 snap a chore chart — copy and the pure pieces of the review page. */

export type Lang = "es" | "en";

export const CHART_COPY = {
    title: { es: "Escanear tablero de tareas", en: "Scan a chore chart" },
    subtitle: { es: "Una foto del tablero del refri, una lista escrita o una captura", en: "A photo of the fridge chart, a handwritten list or a screenshot" },
    pick: { es: "Toma una foto del tablero de tareas (o de una lista)", en: "Take a photo of your chore chart (or a list)" },
    scanning: { es: "Leyendo el tablero…", en: "Reading the chart…" },
    found: { es: "Encontré {n} tareas — revisa y crea", en: "Found {n} chores — review and create" },
    anyone: { es: "Cualquiera (la app reparte)", en: "Anyone (the app balances it)" },
    exists: { es: "Ya existe", en: "Already exists" },
    unmatched: { es: "No encontré a: {names}", en: "Couldn't match: {names}" },
    bonus: { es: "Tarea extra", en: "Bonus task" },
    points: { es: "puntos", en: "points" },
    note: { es: "Nota para el hijo (opcional)", en: "Note for the kid (optional)" },
    create: { es: "Crear {n} tareas", en: "Create {n} chores" },
    creating: { es: "Creando {i} de {n}…", en: "Creating {i} of {n}…" },
    done: { es: "Listo: {n} tareas creadas", en: "Done: {n} chores created" },
    back: { es: "Ver mis tareas", en: "See my chores" },
    unreadable: { es: "No pude leer un tablero en esa foto. Prueba con una foto más clara, de frente.", en: "I couldn't read a chart in that picture. Try a clearer photo, straight on." },
    failed: { es: "No se pudo escanear. Intenta de nuevo.", en: "Could not scan. Try again." },
    tooBig: { es: "La foto pasa de 8 MB. Prueba con una más pequeña.", en: "That photo is over 8 MB. Try a smaller one." },
    createFailed: { es: "No se pudo crear. Intenta de nuevo.", en: "Could not create. Try again." },
    parentTag: { es: "papá/mamá", en: "parent" },
} as const;

export const DAY_LABELS = {
    es: ["L", "M", "X", "J", "V", "S", "D"],
    en: ["M", "T", "W", "T", "F", "S", "S"],
} as const;

export const DAY_NAMES = {
    es: ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    en: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
} as const;

export type Chip = { id: string; label: string };
export type Row = {
    key: string; title: string; points: number; isBonus: boolean; days: number[]; kidIds: string[];
    unmatched: string[]; duplicate: boolean; description: string | null; checked: boolean;
    /** The server's message when the last create attempt failed; cleared on success. */
    error: string | null;
};

const str = (v: unknown) => (typeof v === "string" ? v : "");
const strList = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** The members a proposal can be pinned to: every participating member
 *  (active and approved — the server matches only those), parents labelled.
 *  A chip for everyone the server can match, so a row the chart assigns to a
 *  parent is visible and can be unpinned. */
export function memberChips(members: unknown, lang: Lang): Chip[] {
    if (!Array.isArray(members)) return [];
    const out: Chip[] = [];
    for (const m of members as Array<Record<string, unknown>>) {
        if (!m || typeof m.id !== "string" || typeof m.name !== "string") continue;
        if (m.is_active === false) continue;
        if (typeof m.approval_status === "string" && m.approval_status !== "approved") continue;
        const parent = String(m.role ?? "").toLowerCase() === "parent";
        out.push({ id: m.id, label: parent ? `${m.name} (${CHART_COPY.parentTag[lang]})` : m.name });
    }
    return out;
}

export function proposalRows(resp: unknown): Row[] {
    const chores = (resp as { chores?: unknown } | null)?.chores;
    if (!Array.isArray(chores)) return [];
    const rows: Row[] = [];
    chores.forEach((c, i) => {
        if (!c || typeof c !== "object") return;
        const o = c as Record<string, unknown>;
        const title = str(o.title).trim();
        if (!title) return;
        const duplicate = typeof o.duplicate_of === "string" && o.duplicate_of.length > 0;
        rows.push({
            key: `r${i}`,
            title,
            points: typeof o.points === "number" ? o.points : 10,
            isBonus: o.is_bonus === true,
            days: Array.isArray(o.days_of_week) ? o.days_of_week.filter((d): d is number => Number.isInteger(d) && d >= 0 && d <= 6) : [],
            kidIds: strList(o.assigned_user_ids),
            unmatched: strList(o.unmatched_names),
            duplicate,
            description: str(o.description).trim() || null,
            checked: !duplicate,
            error: null,
        });
    });
    return rows;
}

/** Low confidence or nothing found: show one message, no half-results. */
export function isUnreadable(resp: unknown): boolean {
    const r = resp as { confidence?: unknown; chores?: unknown } | null;
    if (!r) return true;
    const conf = typeof r.confidence === "number" ? r.confidence : 0;
    return conf < 0.3 || proposalRows(r).length === 0;
}

/** The body for POST /api/task-templates/ — an ordinary chore. A Spanish
 *  parent's text goes to the Spanish columns too (what the new-chore form
 *  does), so the backend never "translates" Spanish as if it were English. */
export function templateBody(row: Row, lang: Lang = "en") {
    const points = Math.max(0, Math.min(1000, Math.round(Number(row.points) || 0)));
    const fixed = row.kidIds.length > 0;
    const title = row.title.trim();
    const description = row.description && row.description.trim() ? row.description.trim() : null;
    const body: Record<string, unknown> = {
        title,
        points,
        is_bonus: row.isBonus,
        days_of_week: row.days.length ? [...row.days].sort((a, b) => a - b) : null,
        interval_days: 1,
        assignment_type: fixed ? "fixed" : "auto",
        assigned_user_ids: fixed ? row.kidIds : null,
        description,
    };
    if (lang === "es") {
        body.title_es = title;
        body.description_es = description;
    }
    return body;
}

/** A failed create's message: a string detail, the first message of a
 *  validation list, or the fallback. */
export function errorDetail(body: unknown, fallback: string): string {
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length) {
        const msg = (detail[0] as { msg?: unknown })?.msg;
        if (typeof msg === "string" && msg.trim()) return msg;
    }
    return fallback;
}

export type PostResult = { ok: boolean; detail: string | null };

/** Create every ticked, not-yet-created row, one at a time. A failure stays
 *  on the row as `error` (and is retried next time); a created row joins
 *  `created` and is never posted again. Returns how many were created. */
export async function createRows(
    rows: Row[],
    created: Set<string>,
    post: (body: Record<string, unknown>) => Promise<PostResult>,
    lang: Lang,
    onProgress?: (i: number, n: number) => void,
): Promise<number> {
    const todo = rows.filter((r) => r.checked && !created.has(r.key));
    let ok = 0;
    for (let i = 0; i < todo.length; i++) {
        const row = todo[i];
        onProgress?.(i + 1, todo.length);
        try {
            const result = await post(templateBody(row, lang));
            if (result.ok) {
                created.add(row.key);
                row.error = null;
                ok += 1;
            } else {
                row.error = result.detail || CHART_COPY.createFailed[lang];
            }
        } catch {
            row.error = CHART_COPY.createFailed[lang];
        }
    }
    return ok;
}

export const fill = (s: string, vars: Record<string, string | number>) =>
    s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
