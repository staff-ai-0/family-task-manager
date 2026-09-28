/**
 * Standalone page for /kiosk when it cannot show a board: no token, a bad or
 * revoked token, or a backend that is down (e.g. a wall tablet mid-deploy).
 * Returned as a plain HTML string because /kiosk bails out before its own
 * template renders. Only constant copy is interpolated — no user input.
 */
export type UnpairedReason = "missing" | "invalid" | "unavailable";

const COPY = {
    es: {
        unpairedTitle: "Esta pantalla no está vinculada",
        unavailableTitle: "Tablero no disponible",
        missing: "Abre el enlace de kiosko desde Ajustes → Kiosko en el teléfono de un papá o mamá.",
        invalid: "El enlace de kiosko expiró o fue revocado. Genera uno nuevo en Ajustes → Kiosko.",
        unavailable: "No pudimos cargar el tablero. Intenta de nuevo en un momento.",
        pair: "Vincular esta pantalla",
        login: "Iniciar sesión",
        retry: "Reintentar",
    },
    en: {
        unpairedTitle: "This screen isn't paired",
        unavailableTitle: "Board unavailable",
        missing: "Open the kiosk link from Settings → Kiosk on a parent's phone.",
        invalid: "This kiosk link expired or was revoked. Create a new one in Settings → Kiosk.",
        unavailable: "We couldn't load the board. Try again in a moment.",
        pair: "Pair this screen",
        login: "Sign in",
        retry: "Try again",
    },
} as const;

export function kioskFailureReason(apiStatus: number | null | undefined): UnpairedReason {
    return !apiStatus || apiStatus >= 500 ? "unavailable" : "invalid";
}

export function kioskUnpairedStatus(reason: UnpairedReason, apiStatus?: number | null): number {
    if (reason === "missing") return 400;
    if (reason === "unavailable") return 503;
    return apiStatus && apiStatus >= 400 && apiStatus < 500 ? apiStatus : 401;
}

export function renderKioskUnpaired(opts: {
    lang: string;
    reason: UnpairedReason;
    signedIn: boolean;
}): string {
    const htmlLang = opts.lang === "en" ? "en" : "es";
    const c = COPY[htmlLang];
    const title = opts.reason === "unavailable" ? c.unavailableTitle : c.unpairedTitle;
    const action = opts.reason === "unavailable"
        ? `<button type="button" onclick="location.reload()">${c.retry}</button>`
        : `<a href="${opts.signedIn ? "/parent/kiosk" : "/login"}">${opts.signedIn ? c.pair : c.login}</a>`;
    // A wall-mounted kiosk has no one to tap "retry" — auto-refresh only when
    // the backend is transiently down, never for a missing/revoked link
    // (that needs a human to re-pair, not a retry loop).
    const autoRetry = opts.reason === "unavailable"
        ? `\n<meta http-equiv="refresh" content="30">`
        : "";
    return `<!doctype html>
<html lang="${htmlLang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">${autoRetry}
<title>${title}</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0F1A24;color:#FFF8F0;font-family:Nunito,ui-sans-serif,system-ui,sans-serif}
main{max-width:28rem;padding:2rem;text-align:center}
.icon{font-size:3.5rem;line-height:1}
h1{font-family:"Plus Jakarta Sans",ui-sans-serif,system-ui,sans-serif;font-weight:800;font-size:1.75rem;margin:1rem 0 .5rem}
p{color:#A8C3D4;margin:0 0 1.5rem;line-height:1.5}
a,button{display:inline-block;background:#FF8A65;color:#1F2937;font:inherit;font-weight:800;padding:.85rem 1.5rem;border-radius:999px;border:2px solid #1F2937;box-shadow:4px 4px 0 #1F2937;text-decoration:none;cursor:pointer}
</style>
</head>
<body>
<main>
<div class="icon" aria-hidden="true">📺</div>
<h1>${title}</h1>
<p>${c[opts.reason]}</p>
${action}
</main>
</body>
</html>`;
}
