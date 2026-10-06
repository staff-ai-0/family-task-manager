/** Pay the week from a bank-transfer receipt — copy and the pure pieces of the
 *  review page. The scan stores nothing; each reviewed row is recorded through
 *  POST /api/bank/payout-receipts/confirm, one at a time. */

export type Lang = "es" | "en";

export const RECEIPT_COPY = {
    title: { es: "Pagar con comprobante", en: "Pay with a receipt" },
    subtitle: { es: "Sube las capturas de tus transferencias y la app calcula todo", en: "Upload your transfer screenshots and the app works out the rest" },
    pick: { es: "Elige una o varias capturas del comprobante", en: "Pick one or more receipt screenshots" },
    scanning: { es: "Leyendo comprobantes…", en: "Reading receipts…" },
    found: { es: "Leí {n} comprobantes — revisa y registra", en: "Read {n} receipts — review and record" },
    kid: { es: "Para", en: "For" },
    chooseKid: { es: "Elige a quién se pagó", en: "Choose who was paid" },
    weeks: { es: "Semanas que paga", en: "Weeks it pays" },
    weekOf: { es: "Semana del", en: "Week of" },
    addWeek: { es: "+ Agregar semana", en: "+ Add week" },
    removeWeek: { es: "Quitar", en: "Remove" },
    total: { es: "Total del comprobante", en: "Receipt total" },
    mustAdd: { es: "Los montos deben sumar {total}.", en: "Amounts must add up to {total}." },
    needKid: { es: "Elige a quién se pagó.", en: "Choose who was paid." },
    needWeek: { es: "Agrega al menos una semana.", en: "Add at least one week." },
    duplicate: { es: "Este folio ya está registrado — no se volverá a pagar.", en: "This folio is already recorded — it won't be paid again." },
    alreadyPaid: { es: "Esa semana ya estaba pagada: se suma como pago extra.", en: "That week was already paid: it is added as an extra payment." },
    mismatch: { es: "Difiere de lo que salía por las tareas ({projected}). Se registra lo que transferiste.", en: "Differs from the chore math ({projected}). What you transferred is recorded." },
    guessed: { es: "No decía la semana: sugerí la más antigua sin pagar.", en: "No week was named: I suggested the oldest unpaid one." },
    unreadable: { es: "No pude leer este comprobante.", en: "Couldn't read this receipt." },
    record: { es: "Registrar {n} pagos", en: "Record {n} payments" },
    recording: { es: "Registrando {i} de {n}…", en: "Recording {i} of {n}…" },
    done: { es: "Listo: {n} pagos registrados", en: "Done: {n} payments recorded" },
    back: { es: "Volver a pagos", en: "Back to payouts" },
    failed: { es: "No se pudo leer. Intenta de nuevo.", en: "Could not read. Try again." },
    tooMany: { es: "Máximo 10 comprobantes a la vez.", en: "At most 10 receipts at a time." },
    recordFailed: { es: "No se pudo registrar. Intenta de nuevo.", en: "Could not record. Try again." },
    parentTag: { es: "papá/mamá", en: "parent" },
} as const;

export type Kid = { id: string; label: string };
export type WeekRow = { weekOf: string; amountCents: number; alreadyPaid: boolean; projectedCents: number };
export type Row = {
    key: string;
    filename: string;
    folio: string;
    receiptDate: string | null;
    concept: string;
    beneficiary: string;
    amountCents: number;
    userId: string | null;
    allocations: WeekRow[];
    duplicate: boolean;
    mismatch: boolean;
    guessedWeeks: boolean;
    checked: boolean;
    error: string | null;
};

const str = (v: unknown) => (typeof v === "string" ? v : "");
const int = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v) : 0);

export const fill = (s: string, vars: Record<string, string | number>) =>
    s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));

export const fmtMoney = (cents: number) => `$${(cents / 100).toFixed(2)}`;
export const pesosToCents = (pesos: string | number) => Math.round((parseFloat(String(pesos)) || 0) * 100);

/** Kids a receipt can be assigned to: active, approved children and teens. */
export function kidChips(members: unknown): Kid[] {
    if (!Array.isArray(members)) return [];
    const out: Kid[] = [];
    for (const m of members as Array<Record<string, unknown>>) {
        if (!m || typeof m.id !== "string" || typeof m.name !== "string") continue;
        if (m.is_active === false) continue;
        if (typeof m.approval_status === "string" && m.approval_status !== "approved") continue;
        const role = String(m.role ?? "").toLowerCase();
        if (role === "child" || role === "teen") out.push({ id: m.id, label: m.name });
    }
    return out;
}

/** Scan response → review rows. Unreadable slips are returned separately so
 *  the page can say which file failed without offering to record it. */
export function proposalRows(data: unknown): { rows: Row[]; unreadable: string[] } {
    const list = Array.isArray((data as { receipts?: unknown })?.receipts) ? ((data as { receipts: unknown[] }).receipts) : [];
    const rows: Row[] = [];
    const unreadable: string[] = [];
    list.forEach((raw, i) => {
        const r = (raw ?? {}) as Record<string, unknown>;
        if (!r.readable || !str(r.folio) || int(r.amount_cents) <= 0) {
            unreadable.push(str(r.filename) || `#${i + 1}`);
            return;
        }
        const allocations: WeekRow[] = (Array.isArray(r.allocations) ? r.allocations : []).map((a) => {
            const w = (a ?? {}) as Record<string, unknown>;
            return { weekOf: str(w.week_of), amountCents: int(w.amount_cents), alreadyPaid: w.already_paid === true, projectedCents: int(w.projected_cents) };
        });
        const duplicate = r.duplicate_folio === true;
        rows.push({
            key: `${str(r.folio)}-${i}`,
            filename: str(r.filename),
            folio: str(r.folio),
            receiptDate: str(r.receipt_date) || null,
            concept: str(r.concept),
            beneficiary: str(r.beneficiary),
            amountCents: int(r.amount_cents),
            userId: typeof r.user_id === "string" ? r.user_id : null,
            allocations,
            duplicate,
            mismatch: r.mismatch === true,
            guessedWeeks: allocations.length > 0 && r.weeks_from_concept !== true,
            checked: !duplicate,
            error: null,
        });
    });
    return { rows, unreadable };
}

/** Why a row cannot be recorded yet, or null when it can. */
export function rowProblem(row: Row, lang: Lang): string | null {
    if (!row.userId) return RECEIPT_COPY.needKid[lang];
    if (row.allocations.length === 0) return RECEIPT_COPY.needWeek[lang];
    const sum = row.allocations.reduce((n, a) => n + a.amountCents, 0);
    if (sum !== row.amountCents) return fill(RECEIPT_COPY.mustAdd[lang], { total: fmtMoney(row.amountCents) });
    return null;
}

/** The body for POST /api/bank/payout-receipts/confirm. */
export function confirmBody(row: Row) {
    return {
        folio: row.folio,
        user_id: row.userId,
        receipt_date: row.receiptDate,
        concept: row.concept,
        amount_cents: row.amountCents,
        allocations: row.allocations.map((a) => ({ week_of: a.weekOf, amount_cents: a.amountCents })),
    };
}

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

/** Record every ticked, not-yet-recorded row, one at a time. A failure stays on
 *  the row (retried next time); a recorded row joins `recorded` and is never
 *  posted again — the folio is the server-side backstop for the same rule. */
export async function recordRows(
    rows: Row[],
    recorded: Set<string>,
    post: (body: ReturnType<typeof confirmBody>) => Promise<PostResult>,
    lang: Lang,
    onProgress?: (i: number, n: number) => void,
): Promise<number> {
    const todo = rows.filter((r) => r.checked && !recorded.has(r.key));
    let ok = 0;
    for (let i = 0; i < todo.length; i++) {
        const row = todo[i];
        onProgress?.(i + 1, todo.length);
        const problem = rowProblem(row, lang);
        if (problem) {
            row.error = problem;
            continue;
        }
        try {
            const result = await post(confirmBody(row));
            if (result.ok) {
                recorded.add(row.key);
                row.error = null;
                ok += 1;
            } else {
                row.error = result.detail || RECEIPT_COPY.recordFailed[lang];
            }
        } catch {
            row.error = RECEIPT_COPY.recordFailed[lang];
        }
    }
    return ok;
}
