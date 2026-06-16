import type { APIRoute } from "astro";
import { tryRefreshFor401 } from "../../../lib/server/refresh";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

async function proxy({ request, params }: { request: Request; params: Record<string, string | undefined> }): Promise<Response> {
    const path = params.path ?? "";
    const url = new URL(request.url);
    const backendUrl = `${BACKEND_URL}/api/subscriptions/${path}${url.search}`;

    const forwardHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
        if (key.toLowerCase() === "host") continue;
        forwardHeaders.set(key, value);
    }
    if (!forwardHeaders.has("Authorization") && !path.startsWith("webhook")) {
        const cookieHeader = request.headers.get("cookie") ?? "";
        const match = cookieHeader.match(/(?:^|;\s*)access_token=([^;]+)/);
        if (match) {
            forwardHeaders.set("Authorization", `Bearer ${decodeURIComponent(match[1])}`);
        }
    }
    const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
    const body = hasBody ? await request.arrayBuffer() : undefined;
    try {
        let res = await fetch(backendUrl, {
            method: request.method, headers: forwardHeaders, body, redirect: "manual",
        });
        // Transparently refresh once if the access token expired mid-request.
        // Skip webhook paths, which are unauthenticated (no cookie token injected).
        let refreshedSetCookies: string[] | undefined;
        if (res.status === 401 && !path.startsWith("webhook")) {
            const refreshed = await tryRefreshFor401(res.status, request.headers.get("cookie") ?? "");
            if (refreshed) {
                forwardHeaders.set("Authorization", `Bearer ${refreshed.accessToken}`);
                res = await fetch(backendUrl, {
                    method: request.method, headers: forwardHeaders, body, redirect: "manual",
                });
                refreshedSetCookies = refreshed.setCookies;
            }
        }
        const out = new Headers();
        for (const [k, v] of res.headers.entries()) {
            if (k.toLowerCase() === "transfer-encoding") continue;
            out.set(k, v);
        }
        if (refreshedSetCookies) for (const c of refreshedSetCookies) out.append("Set-Cookie", c);
        return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
    } catch (e: any) {
        return new Response(JSON.stringify({ error: "proxy_error", message: String(e?.message ?? e) }),
            { status: 502, headers: { "Content-Type": "application/json" } });
    }
}

export const GET: APIRoute = proxy;
export const POST: APIRoute = proxy;
export const DELETE: APIRoute = proxy;
export const PATCH: APIRoute = proxy;
