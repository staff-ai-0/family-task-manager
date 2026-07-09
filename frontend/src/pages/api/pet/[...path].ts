import type { APIRoute } from "astro";
import { tryRefreshFor401 } from "../../../lib/server/refresh";
import { clientIpHeaders } from "../../../lib/client-ip";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

/**
 * Wildcard proxy for all /api/pet/* requests.
 *
 * The pet quest/evolution loop (care actions, cosmetics buy/equip/unequip,
 * quest-view refetches) is driven client-side, but browser JS holds only the
 * httpOnly access_token cookie and cannot reach the backend directly. This
 * route forwards every method transparently, lifts the cookie into an
 * Authorization header, and forwards the Cloudflare client IP so the backend's
 * per-user rate-limit buckets stay intact. Mirrors api/family-cup/[...path].ts.
 *
 * Route: /api/pet/[...path]  →  <BACKEND>/api/pet/<path>
 */
async function proxy({ request }: { request: Request; params: Record<string, string | undefined> }): Promise<Response> {
    const url = new URL(request.url);
    const backendUrl = `${BACKEND_URL}${url.pathname}${url.search}`;

    // Forward all headers except Host (which must point at the backend).
    const forwardHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
        if (key.toLowerCase() === "host") continue;
        forwardHeaders.set(key, value);
    }

    // Preserve the real client IP for the backend rate limiter.
    for (const [k, v] of Object.entries(clientIpHeaders(request))) {
        forwardHeaders.set(k, v);
    }

    // The access_token cookie is httpOnly so browser JS cannot read it — extract
    // it server-side and inject as Authorization if not already present.
    if (!forwardHeaders.has("Authorization")) {
        const cookieHeader = request.headers.get("cookie") ?? "";
        const match = cookieHeader.match(/(?:^|;\s*)access_token=([^;]+)/);
        if (match) {
            forwardHeaders.set("Authorization", `Bearer ${decodeURIComponent(match[1])}`);
        }
    }

    const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
    const body = hasBody ? await request.arrayBuffer() : undefined;

    async function doFetch(targetUrl: string): Promise<Response> {
        const backendRes = await fetch(targetUrl, {
            method: request.method,
            headers: forwardHeaders,
            body,
            redirect: "manual", // handle redirects ourselves so POST body is preserved
        });

        if (backendRes.status >= 300 && backendRes.status < 400) {
            const location = backendRes.headers.get("location");
            if (location) {
                const redirectUrl = location.startsWith("http") ? location : `${BACKEND_URL}${location}`;
                return doFetch(redirectUrl);
            }
        }

        const responseHeaders = new Headers();
        for (const [key, value] of backendRes.headers.entries()) {
            if (key.toLowerCase() === "transfer-encoding") continue;
            responseHeaders.set(key, value);
        }
        return new Response(backendRes.body, {
            status: backendRes.status,
            statusText: backendRes.statusText,
            headers: responseHeaders,
        });
    }

    try {
        let res = await doFetch(backendUrl);
        if (res.status === 401) {
            const refreshed = await tryRefreshFor401(res.status, request.headers.get("cookie") ?? "");
            if (refreshed) {
                forwardHeaders.set("Authorization", `Bearer ${refreshed.accessToken}`);
                res = await doFetch(backendUrl);
                for (const c of refreshed.setCookies) res.headers.append("Set-Cookie", c);
            }
        }
        return res;
    } catch (e: any) {
        console.error(`[api/pet proxy] Error forwarding to ${backendUrl}:`, e?.message ?? e);
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
