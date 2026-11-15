/**
 * Show-and-tell (chore baselines) copy, ES + EN. Pure: no DOM, no fetch. The
 * ONLY place this copy lives. Baselines are the parent's reference photos of
 * "what done looks like"; the AI proof review compares kids' photos to them.
 */
export type Lang = "es" | "en";

/** Mirrors the backend cap (409 `baseline_limit`). */
export const BASELINE_MAX = 4;
const MAX_SUGGESTIONS = 5;
const MAX_SUGGESTION_LEN = 160;

export interface BaselineStatusRow {
    template_id: string;
    title: string;
    baseline_count: number;
    last_baseline_at: string | null;
    due: boolean;
}

const L = (lang: string): Lang => (lang === "en" ? "en" : "es");

export function baselineCountLabel(n: number, max: number, lang: string): string {
    return L(lang) === "en" ? `${n} of ${max} photos` : `${n} de ${max} fotos`;
}

export function dueSummary(rows: BaselineStatusRow[], lang: string): string {
    const n = (rows ?? []).filter((r) => r && r.due).length;
    if (!n) return "";
    if (L(lang) === "en") {
        return n === 1
            ? "1 chore needs a fresh show-and-tell"
            : `${n} chores need a fresh show-and-tell`;
    }
    return n === 1
        ? "1 tarea necesita un nuevo show and tell"
        : `${n} tareas necesitan un nuevo show and tell`;
}

export function statusLine(row: BaselineStatusRow, lang: string): string {
    const l = L(lang);
    if (!row.baseline_count) {
        return l === "en" ? "No reference photos yet" : "Aún sin fotos de referencia";
    }
    const count = baselineCountLabel(row.baseline_count, BASELINE_MAX, l);
    const date = row.last_baseline_at ? String(row.last_baseline_at).slice(0, 10) : "";
    if (!date) return count;
    return l === "en" ? `${count}, updated ${date}` : `${count}, actualizado ${date}`;
}

const ERRORS: Record<string, { es: string; en: string }> = {
    baseline_limit: {
        es: `Máximo ${BASELINE_MAX} fotos por tarea. Borra una para subir otra.`,
        en: `Up to ${BASELINE_MAX} photos per chore. Delete one to add another.`,
    },
    "415": {
        es: "Formato no compatible. Usa JPG, PNG o WebP.",
        en: "Unsupported format. Use JPG, PNG or WebP.",
    },
    "413": {
        es: "La foto es demasiado grande.",
        en: "That photo is too large.",
    },
    ai_consent_required: {
        es: "Activa el procesamiento con IA en los ajustes de la familia para pedir ideas.",
        en: "Turn on AI processing in family settings to ask for ideas.",
    },
    upgrade_required: {
        es: "Requiere plan Plus. Ve a Suscripción.",
        en: "Requires the Plus plan. See Subscription.",
    },
    ai_failed: {
        es: "La IA no pudo dar ideas ahora. Intenta más tarde.",
        en: "The AI couldn't suggest ideas right now. Try again later.",
    },
};

export function errorMessage(codeOrStatus: string | number | undefined | null, lang: string): string {
    const l = L(lang);
    const hit = ERRORS[String(codeOrStatus ?? "")];
    if (hit) return hit[l];
    return l === "en" ? "Something went wrong. Try again." : "Algo salió mal. Intenta de nuevo.";
}

/** Trim, drop blanks/non-strings/duplicates, cap count and length. */
export function cleanSuggestions(list: unknown): string[] {
    if (!Array.isArray(list)) return [];
    const out: string[] = [];
    for (const item of list) {
        if (typeof item !== "string") continue;
        const s = item.trim().slice(0, MAX_SUGGESTION_LEN);
        if (!s || out.includes(s)) continue;
        out.push(s);
        if (out.length >= MAX_SUGGESTIONS) break;
    }
    return out;
}

export interface SectionCopy {
    title: string;
    intro: string;
    needsProof: string;
    add: string;
    caption: string;
    ideas: string;
    ideasHint: string;
    remove: string;
    removeTitle: string;
    removeBody: string;
    uploaded: string;
    removed: string;
    empty: string;
    cancel: string;
    ideasLocked: string;
    upgradeCta: string;
}

export function sectionCopy(lang: string): SectionCopy {
    return L(lang) === "en"
        ? {
              title: "Show and tell",
              intro: "Photos of what done looks like. The AI compares kids' proof photos against them.",
              needsProof: "Turn on \"Requires photo proof\" and save: reference photos are used when proof is required.",
              add: "Add photo",
              caption: "Caption (optional)",
              ideas: "Ask for ideas",
              ideasHint: "AI tips from your photos and recent proofs",
              remove: "Delete",
              removeTitle: "Delete this photo?",
              removeBody: "The AI will stop using it as a reference.",
              uploaded: "Photo added",
              removed: "Photo deleted",
              empty: "No photos yet",
              cancel: "Cancel",
              ideasLocked: "Ideas from the AI need the Plus plan.",
              upgradeCta: "See Subscription",
          }
        : {
              title: "Show and tell",
              intro: "Fotos de cómo se ve la tarea bien hecha. La IA compara con ellas las fotos de evidencia.",
              needsProof: "Activa \"Requiere foto de evidencia\" y guarda: las fotos de referencia se usan cuando se pide evidencia.",
              add: "Agregar foto",
              caption: "Descripción (opcional)",
              ideas: "Pedir ideas",
              ideasHint: "Consejos de la IA con tus fotos y evidencias recientes",
              remove: "Borrar",
              removeTitle: "¿Borrar esta foto?",
              removeBody: "La IA dejará de usarla como referencia.",
              uploaded: "Foto agregada",
              removed: "Foto borrada",
              empty: "Aún no hay fotos",
              cancel: "Cancelar",
              ideasLocked: "Las ideas de la IA requieren el plan Plus.",
              upgradeCta: "Ver Suscripción",
          };
}

export function cardCopy(lang: string): { title: string; cta: string; dismiss: string } {
    return L(lang) === "en"
        ? { title: "Show and tell", cta: "Update photos", dismiss: "Not now" }
        : { title: "Show and tell", cta: "Actualizar fotos", dismiss: "Más tarde" };
}

/** localStorage key for the hub card's "not now": one per calendar month. */
export function dismissKey(now: Date = new Date()): string {
    const m = String(now.getMonth() + 1).padStart(2, "0");
    return `ftm-show-tell-dismissed-${now.getFullYear()}-${m}`;
}

/** True when the card was dismissed this calendar month. Never throws. */
export function isDismissed(store: Pick<Storage, "getItem"> | null | undefined, now: Date = new Date()): boolean {
    try {
        return store?.getItem(dismissKey(now)) === "1";
    } catch {
        return false;
    }
}

/** Remember the dismissal for the rest of this calendar month. Never throws. */
export function dismiss(store: Pick<Storage, "setItem"> | null | undefined, now: Date = new Date()): void {
    try {
        store?.setItem(dismissKey(now), "1");
    } catch {
        /* storage blocked: the card simply returns next visit */
    }
}
