import type { APIRoute } from "astro";
import { tryRefreshFor401 } from "../../../lib/server/refresh";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

async function proxy({ request, params }: { request: Request; params: Record<string, string | undefined> }): Promise<Response> {
    const path = params.path ?? "";
    const url = new URL(request.url);
    const backendUrl = `${BACKEND_URL}${url.pathname}${url.search}`;

    const forwardHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
        if (key.toLowerCase() === "host") continue;
        forwardHeaders.set(key, value);
    }

    // /snapshot is token-gated via query param; no Authorization needed there.
    // For /devices CRUD endpoints, lift the cookie token into Authorization.
    if (!forwardHeaders.has("Authorization") && !path.startsWith("snapshot")) {
        const cookieHeader = request.headers.get("cookie") ?? "";
        const match = cookieHeader.match(/(?:^|;\s*)access_token=([^;]+)/);
        if (match) {
            const token = decodeURIComponent(match[1]);
            forwardHeaders.set("Authorization", `Bearer ${token}`);
        }
    }

    const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
    const body = hasBody ? await request.arrayBuffer() : undefined;

    try {
        let backendRes = await fetch(backendUrl, {
            method: request.method,
            headers: forwardHeaders,
            body,
            redirect: "manual",
        });
        // Transparently refresh once if the access token expired mid-request.
        // Skip snapshot paths, which are token-gated via query param (no cookie auth).
        let refreshedSetCookies: string[] | undefined;
        if (backendRes.status === 401 && !path.startsWith("snapshot")) {
            const refreshed = await tryRefreshFor401(backendRes.status, request.headers.get("cookie") ?? "");
            if (refreshed) {
                forwardHeaders.set("Authorization", `Bearer ${refreshed.accessToken}`);
                backendRes = await fetch(backendUrl, {
                    method: request.method,
                    headers: forwardHeaders,
                    body,
                    redirect: "manual",
                });
                refreshedSetCookies = refreshed.setCookies;
            }
        }
        const responseHeaders = new Headers();
        for (const [key, value] of backendRes.headers.entries()) {
            if (key.toLowerCase() === "transfer-encoding") continue;
            responseHeaders.set(key, value);
        }
        if (refreshedSetCookies) for (const c of refreshedSetCookies) responseHeaders.append("Set-Cookie", c);
        return new Response(backendRes.body, {
            status: backendRes.status,
            statusText: backendRes.statusText,
            headers: responseHeaders,
        });
    } catch (e: any) {
        console.error(`[api/kiosk proxy] Error forwarding to ${backendUrl}:`, e?.message ?? e);
        return new Response(
            JSON.stringify({ error: "proxy_error", message: "Could not reach backend" }),
            { status: 502, headers: { "Content-Type": "application/json" } },
        );
    }
}

export const GET: APIRoute = proxy;
export const POST: APIRoute = proxy;
export const PUT: APIRoute = proxy;
export const DELETE: APIRoute = proxy;
export const PATCH: APIRoute = proxy;
