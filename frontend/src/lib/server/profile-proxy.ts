import { clientIpHeaders } from "../client-ip";

export const apiBase = () =>
    process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

export function json(status: number, body: unknown, setCookies: string[] = []): Response {
    const headers = new Headers({ "Content-Type": "application/json" });
    for (const c of setCookies) headers.append("Set-Cookie", c);
    return new Response(JSON.stringify(body), { status, headers });
}

/** Turn a failed backend response into `{success:false,error}` with the same
 *  status (403 / 429 / 401 pass through). Never echoes tokens. */
export async function errorFrom(resp: Response, fallback: string): Promise<Response> {
    let error = fallback;
    try {
        const d = await resp.json();
        if (typeof d?.detail === "string") error = d.detail;
        else if (typeof d?.message === "string") error = d.message;
    } catch { /* keep fallback */ }
    return json(resp.status || 500, { success: false, error });
}

/** Call a backend profile/* endpoint authenticated by the home token. */
export async function callProfile(
    request: Request,
    homeToken: string,
    path: string,
    method: "GET" | "POST",
    body?: unknown
): Promise<Response> {
    const headers: Record<string, string> = {
        Authorization: `Bearer ${homeToken}`,
        ...clientIpHeaders(request),
    };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    return fetch(`${apiBase()}/api/auth/profile/${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });
}
