/** UX-E4 profile switcher on a shared device — the only place its copy lives.
 *  Pure helpers: copy by language, the readable `ftm_sw` marker, status →
 *  message key, and the PIN pad's append rule. The marker is a UX hint only;
 *  the real session state is the httpOnly cookies. */

export type Lang = "es" | "en";

const COPY = {
    title: { es: "¿Quién eres?", en: "Who are you?" },
    pickPrompt: { es: "Toca tu perfil para entrar", en: "Tap your profile to sign in" },
    pinTitle: { es: "Escribe tu PIN", en: "Enter your PIN" },
    wrongPin: { es: "PIN incorrecto. Intenta de nuevo.", en: "Wrong PIN. Try again." },
    locked: {
        es: "Demasiados intentos. Espera un momento e intenta de nuevo.",
        en: "Too many tries. Wait a moment and try again.",
    },
    noPin: { es: "Sin PIN. Pide a un adulto que lo cree.", en: "No PIN yet. Ask a parent to set one." },
    backToParent: { es: "Volver al perfil de papá/mamá", en: "Back to parent" },
    passwordPrompt: { es: "Contraseña de papá/mamá", en: "Parent password" },
    wrongPassword: { es: "Contraseña incorrecta.", en: "Wrong password." },
    shareTitle: { es: "Compartir este dispositivo", en: "Share this device" },
    shareBody: {
        es: "Los niños y adolescentes eligen su perfil y entran con su PIN. Para volver al perfil de adulto se pide tu contraseña.",
        en: "Kids and teens pick their profile and sign in with a PIN. Returning to the parent profile asks for your password.",
    },
    shareCta: { es: "Compartir este dispositivo", en: "Share this device" },
    error: { es: "Algo salió mal. Intenta de nuevo.", en: "Something went wrong. Try again." },
    cancel: { es: "Cancelar", en: "Cancel" },
    sessionExpired: {
        es: "Tu sesión expiró. Inicia sesión de nuevo.",
        en: "Your session expired. Sign in again.",
    },
    clear: { es: "Borrar", en: "Clear" },
} as const;

export type ProfileCopy = { [K in keyof typeof COPY]: string };

export function profileCopy(lang: string): ProfileCopy {
    const l: Lang = lang === "en" ? "en" : "es";
    const out = {} as Record<string, string>;
    for (const k of Object.keys(COPY) as (keyof typeof COPY)[]) out[k] = COPY[k][l];
    return out as ProfileCopy;
}

/** True when the readable `ftm_sw` marker cookie is present (exact name). */
export function isSwitchedSession(cookieHeader: string): boolean {
    return cookieHeader.split(";").some((c) => c.trim().startsWith("ftm_sw="));
}

export function errorKey(status: number): "wrongPin" | "locked" | "error" {
    if (status === 403) return "wrongPin";
    if (status === 429) return "locked";
    return "error";
}

/** Append one digit to the PIN being typed: digits only, max 4. */
export function pinPadAppend(current: string, digit: string): string {
    if (!/^\d$/.test(digit) || current.length >= 4) return current;
    return current + digit;
}
