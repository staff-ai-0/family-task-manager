/** Jarvis teen check-in — the only place its copy lives. The backend stores
 *  reason KEYS; labels, tips and the chat opener are here. */

export type Lang = "es" | "en";

export const REASONS = ["too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other"] as const;
export type Reason = (typeof REASONS)[number];

/** Free text is kept only where a tag says too little. */
export const NOTE_REASONS: readonly Reason[] = ["app_problem", "other"];
export const NOTE_MAX = 200;

type Entry = { es: string; en: string; tipEs: string; tipEn: string; chatEs: string; chatEn: string };

const COPY: Record<Reason, Entry> = {
    too_hard: {
        es: "Está muy difícil", en: "It's too hard",
        tipEs: "Divídela: pon 5 minutos en el reloj y haz solo la primera parte.",
        tipEn: "Split it: set a 5-minute timer and do only the first part.",
        chatEs: "está muy difícil", chatEn: "it's too hard",
    },
    not_clear: {
        es: "No sé bien qué hacer", en: "I'm not sure what to do",
        tipEs: "Pide a tu papá o mamá que te muestre una vez cómo debe quedar.",
        tipEn: 'Ask a parent to show you once what "done" looks like.',
        chatEs: "no sé bien qué hacer", chatEn: "I'm not sure what to do",
    },
    no_time: {
        es: "No tengo tiempo", en: "I don't have time",
        tipEs: "Pégala a algo que ya haces: antes de cenar o al llegar de la escuela.",
        tipEn: "Attach it to something you already do — before dinner, or right after school.",
        chatEs: "no tengo tiempo", chatEn: "I don't have time",
    },
    not_fair: {
        es: "No me parece justo", en: "It doesn't feel fair",
        tipEs: "Díselo a tus papás: en la app pueden volver a repartir las tareas de la semana.",
        tipEn: "Tell your parents — they can reshuffle the week's chores in the app.",
        chatEs: "no me parece justo", chatEn: "it doesn't feel fair",
    },
    forgot: {
        es: "Se me olvidó", en: "I forgot",
        tipEs: "Todavía puedes hacerla hoy. Activa las notificaciones para que no se te pase.",
        tipEn: "You can still do it today. Turn on notifications so it doesn't slip.",
        chatEs: "se me olvidó", chatEn: "I forgot",
    },
    app_problem: {
        es: "La app no me deja", en: "The app won't let me",
        tipEs: "Gracias. Lo vamos a revisar.", tipEn: "Thanks. We'll look into it.",
        chatEs: "la app no me deja", chatEn: "the app won't let me",
    },
    other: {
        es: "Otra cosa", en: "Something else",
        tipEs: "Gracias por decirnos.", tipEn: "Thanks for telling us.",
        chatEs: "es otra cosa", chatEn: "it's something else",
    },
};

export const reasonLabel = (r: Reason, lang: Lang): string => COPY[r][lang];
export const tipFor = (r: Reason, lang: Lang): string => (lang === "es" ? COPY[r].tipEs : COPY[r].tipEn);
export const takesNote = (r: Reason): boolean => NOTE_REASONS.includes(r);

export const CHECKIN_COPY = {
    question: { es: "¿Atorado con", en: "Stuck on" },
    yes: { es: "Sí, ayúdame", en: "Yes, help me" },
    notNow: { es: "Ahora no", en: "Not now" },
    pick: { es: "¿Qué pasa?", en: "What's going on?" },
    noteHint: {
        es: "Tu nota llega al equipo de la app, sin tu nombre. No escribas nombres.",
        en: "Your note goes to the app's team, without your name. Please don't write names.",
    },
    notePlaceholder: { es: "Cuéntanos (opcional)", en: "Tell us (optional)" },
    send: { es: "Enviar", en: "Send" },
    chat: { es: "Hablarlo con Jarvis", en: "Talk it through with Jarvis" },
    failed: { es: "No se pudo guardar. Intenta de nuevo.", en: "Could not save. Try again." },
} as const;

export type CheckinView = { assignmentId: string; title: string; canChat: boolean };

/** The card's view of GET /api/jarvis/checkin, or null when nothing is offered. */
export function checkinView(resp: unknown, lang: Lang): CheckinView | null {
    const offer = (resp as { offer?: Record<string, unknown> } | null)?.offer;
    if (!offer || typeof offer.assignment_id !== "string" || typeof offer.title !== "string") return null;
    const titleEs = typeof offer.title_es === "string" && offer.title_es ? offer.title_es : null;
    return {
        assignmentId: offer.assignment_id,
        title: lang === "es" && titleEs ? titleEs : offer.title,
        canChat: (resp as { can_chat?: unknown }).can_chat === true,
    };
}

export function answerBody(assignmentId: string, reason: Reason, note?: string | null) {
    const body: { assignment_id: string; outcome: "answered"; reason: Reason; note?: string } = {
        assignment_id: assignmentId, outcome: "answered", reason,
    };
    const text = (note ?? "").trim().slice(0, NOTE_MAX);
    if (takesNote(reason) && text) body.note = text;
    return body;
}

export const dismissBody = (assignmentId: string) => ({ assignment_id: assignmentId, outcome: "dismissed" as const });

/** Opens the teen's own Jarvis chat with a first message typed. Nothing
 *  reaches the AI until the teen sends it. */
export function chatHref(title: string, reason: Reason, lang: Lang): string {
    const text = lang === "es"
        ? `Estoy atorado con «${title}»: ${COPY[reason].chatEs}. ¿Me ayudas?`
        : `I'm stuck on "${title}": ${COPY[reason].chatEn}. Can you help?`;
    return `/parent/jarvis?q=${encodeURIComponent(text)}`;
}
