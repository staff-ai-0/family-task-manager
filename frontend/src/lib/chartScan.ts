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
    create: { es: "Crear {n} tareas", en: "Create {n} chores" },
    done: { es: "Listo: {n} tareas creadas", en: "Done: {n} chores created" },
    back: { es: "Ver mis tareas", en: "See my chores" },
    unreadable: { es: "No pude leer un tablero en esa foto. Prueba con una foto más clara, de frente.", en: "I couldn't read a chart in that picture. Try a clearer photo, straight on." },
    failed: { es: "No se pudo escanear. Intenta de nuevo.", en: "Could not scan. Try again." },
} as const;

export const DAY_LABELS = {
    es: ["L", "M", "X", "J", "V", "S", "D"],
    en: ["M", "T", "W", "T", "F", "S", "S"],
} as const;

export type Kid = { id: string; name: string };
export type Row = {
    key: string; title: string; points: number; isBonus: boolean; days: number[]; kidIds: string[];
    unmatched: string[]; duplicate: boolean; description: string | null; checked: boolean;
};

const str = (v: unknown) => (typeof v === "string" ? v : "");
const strList = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

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

/** The body for POST /api/task-templates/ — an ordinary chore. */
export function templateBody(row: Row) {
    const points = Math.max(0, Math.min(1000, Math.round(Number(row.points) || 0)));
    const fixed = row.kidIds.length > 0;
    return {
        title: row.title.trim(),
        points,
        is_bonus: row.isBonus,
        days_of_week: row.days.length ? [...row.days].sort((a, b) => a - b) : null,
        interval_days: 1,
        assignment_type: fixed ? "fixed" : "auto",
        assigned_user_ids: fixed ? row.kidIds : null,
        description: row.description && row.description.trim() ? row.description.trim() : null,
    };
}

export const fill = (s: string, vars: Record<string, string | number>) =>
    s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
