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
}

export async function apiFetch<T = unknown>(
    path: string,
    options: ApiFetchOptions = {}
): Promise<ApiResponse<T>> {
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
            // Handle Pydantic validation errors (array of objects)
            let errorMessage = "An error occurred";
            if (data?.detail) {
                if (typeof data.detail === 'string') {
                    errorMessage = data.detail;
                } else if (Array.isArray(data.detail)) {
                    // Pydantic validation errors
                    errorMessage = data.detail
                        .map((err: any) => `${err.loc?.join('.')}: ${err.msg}`)
                        .join(', ');
                }
            }
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
