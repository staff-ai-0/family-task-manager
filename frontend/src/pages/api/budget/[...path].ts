import type { APIRoute } from "astro";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

/**
 * Wildcard proxy for all /api/budget/* requests.
 *
 * Browser-side JS cannot reach the backend directly (different port / internal
 * Docker hostname). This endpoint forwards every method (GET, POST, PUT,
 * DELETE, PATCH) transparently, preserving headers, body, and status codes.
 *
 * Route: /api/budget/[...path]  →  <BACKEND>/api/budget/<path>
 */
async function proxy({ request, params }: { request: Request; params: Record<string, string | undefined> }): Promise<Response> {
    const path = params.path ?? "";
    const url = new URL(request.url);
    const backendUrl = `${BACKEND_URL}/api/budget/${path}${url.search}`;

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

    try {
        const backendRes = await fetch(backendUrl, {
            method: request.method,
            headers: forwardHeaders,
            body: body,
        });

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
    } catch (e: any) {
        console.error(`[api/budget proxy] Error forwarding to ${backendUrl}:`, e?.message ?? e);
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
