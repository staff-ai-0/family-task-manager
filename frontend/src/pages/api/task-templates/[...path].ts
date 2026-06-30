import type { APIRoute } from "astro";
import { tryRefreshFor401 } from "../../../lib/server/refresh";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8000";

/**
 * Wildcard proxy for all /api/task-templates/* requests.
 *
 * Browser-side JS cannot reach the backend directly (different port / internal
 * Docker hostname). This endpoint forwards every method (GET, POST, PUT,
 * DELETE, PATCH) transparently, preserving headers, body, and status codes.
 *
 * Route: /api/task-templates/[...path]  →  <BACKEND>/api/task-templates/<path>
 *
 * Redirect handling: FastAPI redirects e.g. POST /task-templates → /task-templates/
 * We follow 3xx redirects manually so the body is re-sent correctly on POST.
 */
async function proxy({ request, params }: { request: Request; params: Record<string, string | undefined> }): Promise<Response> {
    const path = params.path ?? "";
    const url = new URL(request.url);
    const backendUrl = `${BACKEND_URL}${url.pathname}${url.search}`;

    // Forward all headers except Host (which must point to the backend)
    const forwardHeaders = new Headers();
    for (const [key, value] of request.headers.entries()) {
        if (key.toLowerCase() === "host") continue;
        forwardHeaders.set(key, value);
    }

    // The access_token cookie is httpOnly so browser JS cannot read it.
    // Extract it server-side and inject as Authorization header if not already set.
    if (!forwardHeaders.has("Authorization")) {
        const cookieHeader = request.headers.get("cookie") ?? "";
        const match = cookieHeader.match(/(?:^|;\s*)access_token=([^;]+)/);
        if (match) {
            const token = decodeURIComponent(match[1]);
            forwardHeaders.set("Authorization", `Bearer ${token}`);
        }
    }

    const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
    const body = hasBody ? await request.arrayBuffer() : undefined;

    async function doFetch(targetUrl: string): Promise<Response> {
        const backendRes = await fetch(targetUrl, {
            method: request.method,
            headers: forwardHeaders,
            body: body,
            redirect: "manual", // handle redirects ourselves so POST body is preserved
        });

        // Follow 3xx redirects manually (preserves method + body)
        if (backendRes.status >= 300 && backendRes.status < 400) {
            const location = backendRes.headers.get("location");
            if (location) {
                // location may be absolute (http://backend:8000/...) or relative
                const redirectUrl = location.startsWith("http")
                    ? location
                    : `${BACKEND_URL}${location}`;
                return doFetch(redirectUrl);
            }
        }

        // Stream the response back as-is
        const responseHeaders = new Headers();
        for (const [key, value] of backendRes.headers.entries()) {
            // Skip transfer-encoding — Node handles chunking itself
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
        // Transparently refresh once if the access token expired mid-request.
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
        console.error(`[api/task-templates proxy] Error forwarding to ${backendUrl}:`, e?.message ?? e);
        return new Response(
            JSON.stringify({ error: "proxy_error", message: "Could not reach backend" }),
            { status: 502, headers: { "Content-Type": "application/json" } }
        );
    }
}

export const GET: APIRoute = proxy;
export const POST: APIRoute = proxy;
export const PUT: APIRoute = proxy;
export const DELETE: APIRoute = proxy;
export const PATCH: APIRoute = proxy;
