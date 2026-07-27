/**
 * Error-message normalization shared between SSR code and browser
 * <script> blocks.
 *
 * Split out of lib/api.ts on purpose: that module's FALLBACK_API_BASE_URL
 * reads `process.env` at module load, which is fine server-side (Astro
 * frontmatter, API routes) but would throw `ReferenceError: process is not
 * defined` if the module were ever imported into a client bundle — there is
 * no `process` global in the browser and nothing in this app's Vite config
 * polyfills one. This file has no such side effect, so it is safe to import
 * from either side.
 */

/**
 * Normalize a FastAPI error `detail` payload to a human-readable string.
 * Handles the three shapes the backend emits:
 * - plain string
 * - Pydantic validation errors (array of {loc, msg})
 * - structured dicts like {error, message, message_es} (e.g. the 403
 *   email_not_verified guard) — picks message_es/message by lang so the
 *   bilingual copy shows instead of "[object Object]".
 */
export function normalizeErrorDetail(detail: unknown, lang?: string): string | null {
    if (detail == null) return null;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
        return detail
            .map((err: any) => `${err.loc?.join('.')}: ${err.msg}`)
            .join(', ');
    }
    if (typeof detail === "object") {
        const d = detail as Record<string, unknown>;
        const message = lang === "es"
            ? (d.message_es ?? d.message)
            : (d.message ?? d.message_es);
        if (typeof message === "string") return message;
        if (typeof d.error === "string") return d.error;
        try {
            return JSON.stringify(detail);
        } catch {
            return String(detail);
        }
    }
    return String(detail);
}
