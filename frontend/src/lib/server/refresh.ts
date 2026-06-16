import { authCookies } from "../auth-cookies";

const API = () => process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

export interface RefreshResult {
    ok: boolean;
    accessToken?: string;
    setCookies?: string[];
}

/** Exchange a refresh token for a new pair by calling the backend.
 *  Returns the new access token + Set-Cookie header values on success. */
export async function refreshAccessToken(refreshToken: string): Promise<RefreshResult> {
    if (!refreshToken) return { ok: false };
    const resp = await fetch(`${API()}/api/auth/refresh`, {
        method: "POST",
        headers: { Authorization: `Bearer ${refreshToken}` },
    });
    if (!resp.ok) return { ok: false };
    const body = await resp.json();
    return {
        ok: true,
        accessToken: body.access_token,
        setCookies: authCookies(body.access_token, body.refresh_token, !import.meta.env.DEV),
    };
}

/** Read a cookie value from a raw Cookie header. */
export function readCookie(cookieHeader: string, name: string): string | undefined {
    const m = cookieHeader.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
    return m ? decodeURIComponent(m[1]) : undefined;
}

/** If a backend response is 401 and a refresh token is present, refresh once
 *  and let the caller retry with the new access token. Returns the new token
 *  + Set-Cookie list, or null if refresh isn't possible. */
export async function tryRefreshFor401(
    status: number,
    cookieHeader: string
): Promise<{ accessToken: string; setCookies: string[] } | null> {
    if (status !== 401) return null;
    const refreshToken = readCookie(cookieHeader, "refresh_token");
    if (!refreshToken) return null;
    const r = await refreshAccessToken(refreshToken);
    if (!r.ok) return null;
    return { accessToken: r.accessToken!, setCookies: r.setCookies! };
}
