/**
 * Central API helper for the Family Task Manager Astro frontend.
 * Uses runtime environment variable API_BASE_URL for SSR.
 */

import type { ApiResponse } from "../types/api";

// Use runtime environment variable (process.env works in Astro SSR)
export const FALLBACK_API_BASE_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

export interface ApiFetchOptions extends RequestInit {
    token?: string;
    baseUrl?: string;
    /** UI language ("es"/"en") used to pick bilingual error copy. Falls back
     *  to the lang cookie when running in the browser. */
    lang?: string;
}

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

/** Read the lang cookie when running in a browser context (client scripts). */
function langFromDocumentCookie(): string | undefined {
    if (typeof document === "undefined") return undefined;
    return (document.cookie.match(/(?:^|;\s*)lang=([^;]+)/) || [])[1];
}

export async function apiFetch<T = unknown>(
    path: string,
    options: ApiFetchOptions = {}
): Promise<ApiResponse<T>> {
    const { token, baseUrl = FALLBACK_API_BASE_URL, lang, ...rest } = options;

    const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...(rest.headers as Record<string, string>),
    };

    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    try {
        const res = await fetch(`${baseUrl}${path}`, { ...rest, headers });
        if (res.status === 204) {
            return { data: null, ok: true, status: res.status };
        }
        const data = await res.json();
        if (!res.ok) {
            // Normalize string / Pydantic-array / structured-dict details.
            const errorMessage =
                normalizeErrorDetail(data?.detail, lang ?? langFromDocumentCookie())
                ?? "An error occurred";
            return {
                data: null,
                ok: false,
                status: res.status,
                error: errorMessage,
            };
        }
        return { data: data as T, ok: true, status: res.status };
    } catch (e: any) {
        const detail = e?.cause?.message ?? e?.message ?? String(e);
        console.error(`API fetch error [${options.method ?? "GET"} ${baseUrl}${path}]:`, detail, e);
        return { data: null, ok: false, status: 0, error: `Network error: ${detail}` };
    }
}
