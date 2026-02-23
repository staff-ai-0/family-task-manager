/**
 * Central API helper for the Family Task Manager Astro frontend.
 * The baseUrl is passed in from individual .astro pages via process.env.API_BASE_URL.
 */

export const FALLBACK_API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8002";

export interface ApiFetchOptions extends RequestInit {
    token?: string;
    baseUrl?: string;
}

export async function apiFetch<T = unknown>(
    path: string,
    options: ApiFetchOptions = {}
): Promise<{ data: T | null; ok: boolean; status: number; error?: string }> {
    const { token, baseUrl = FALLBACK_API_BASE_URL, ...rest } = options;

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
            return {
                data: null,
                ok: false,
                status: res.status,
                error: data?.detail || "An error occurred",
            };
        }
        return { data: data as T, ok: true, status: res.status };
    } catch (e) {
        return { data: null, ok: false, status: 0, error: "Network error" };
    }
}
