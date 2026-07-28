import type { APIRoute } from "astro";
import { tryRefreshFor401 } from "./refresh";

const BACKEND_URL = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";

/** FastAPI's slash-redirect is a single hop; the cap only stops a
 *  misconfigured backend from recursing until the stack blows. */
const MAX_REDIRECTS = 5;

export interface ApiProxyOptions {
    /** Domain segment, e.g. "budget" — only used to label the 502 log line. */
    name: string;
    /** Sub-paths (prefix-matched against the [...path] param) that carry their
     *  own credentials — a query-param token, a provider webhook signature. The
     *  cookie must not be lifted into Authorization there, and a 401 from them
     *  is a real refusal, not an expired session, so it must not trigger a
     *  refresh retry. */
    skipAuthPaths?: string[];
}

export type ApiProxyHandlers = Record<"GET" | "POST" | "PUT" | "DELETE" | "PATCH", APIRoute>;

/**
 * Build the catch-all handlers for a `/api/<name>/[...path]` proxy route.
 *
 * Browser JS cannot reach the backend directly (different port / internal
 * container hostname) and holds only the httpOnly `access_token` cookie, while
 * the backend wants a Bearer header. Every proxy therefore forwards the request
 * verbatim, lifts the cookie into Authorization, follows FastAPI's slash
 * redirects by hand so the method and body survive, and retries once behind a
 * token refresh when the access token expired mid-request.
 */
export function createApiProxy(opts: ApiProxyOptions): ApiProxyHandlers {
    const skipAuthPaths = opts.skipAuthPaths ?? [];

    const proxy: APIRoute = async ({ request, params }) => {
        const path = params.path ?? "";
        const skipAuth = skipAuthPaths.some((prefix) => path.startsWith(prefix));

        // url.pathname verbatim, never a path rebuilt from params: rebuilding
        // drops the trailing slash, FastAPI answers 307, and the proxied POST
        // body is lost on the way to a 502.
        const url = new URL(request.url);
        const backendUrl = `${BACKEND_URL}${url.pathname}${url.search}`;

        // Everything but Host goes through untouched. CF-Connecting-IP riding
        // along matters: the backend rate limiter keys on it, and dropping it
        // would collapse every user into the frontend container's one bucket
        // (lib/client-ip.ts covers the hand-written routes that rebuild headers).
        const forwardHeaders = new Headers();
        for (const [key, value] of request.headers.entries()) {
            if (key.toLowerCase() === "host") continue;
            forwardHeaders.set(key, value);
        }

        // The access_token cookie is httpOnly, so browser JS cannot send it as a
        // header itself — read it server-side here.
        if (!skipAuth && !forwardHeaders.has("Authorization")) {
            const match = (request.headers.get("cookie") ?? "").match(/(?:^|;\s*)access_token=([^;]+)/);
            if (match) {
                forwardHeaders.set("Authorization", `Bearer ${decodeURIComponent(match[1])}`);
            }
        }

        const hasBody = !["GET", "HEAD"].includes(request.method.toUpperCase());
        const body = hasBody ? await request.arrayBuffer() : undefined;

        async function send(targetUrl: string, hops = 0): Promise<Response> {
            const backendRes = await fetch(targetUrl, {
                method: request.method,
                headers: forwardHeaders,
                body,
                redirect: "manual", // re-issue 3xx ourselves so method + body are preserved
            });

            if (backendRes.status >= 300 && backendRes.status < 400 && hops < MAX_REDIRECTS) {
                const location = backendRes.headers.get("location");
                if (location) {
                    // location may be absolute (http://backend:8000/...) or relative
                    const redirectUrl = location.startsWith("http") ? location : `${BACKEND_URL}${location}`;
                    return send(redirectUrl, hops + 1);
                }
            }

            return backendRes;
        }

        try {
            let backendRes = await send(backendUrl);

            let refreshedSetCookies: string[] | undefined;
            if (backendRes.status === 401 && !skipAuth) {
                const refreshed = await tryRefreshFor401(backendRes.status, request.headers.get("cookie") ?? "");
                if (refreshed) {
                    forwardHeaders.set("Authorization", `Bearer ${refreshed.accessToken}`);
                    backendRes = await send(backendUrl);
                    // The caller's cookies still hold the spent pair; hand back the
                    // rotated one or the next request 401s again.
                    refreshedSetCookies = refreshed.setCookies;
                }
            }

            const responseHeaders = new Headers();
            for (const [key, value] of backendRes.headers.entries()) {
                // Node re-chunks the stream itself; forwarding the backend's
                // framing header corrupts it.
                if (key.toLowerCase() === "transfer-encoding") continue;
                responseHeaders.set(key, value);
            }
            if (refreshedSetCookies) {
                for (const cookie of refreshedSetCookies) responseHeaders.append("Set-Cookie", cookie);
            }

            return new Response(backendRes.body, {
                status: backendRes.status,
                statusText: backendRes.statusText,
                headers: responseHeaders,
            });
        } catch (e: any) {
            console.error(`[api/${opts.name} proxy] Error forwarding to ${backendUrl}:`, e?.message ?? e);
            return new Response(
                JSON.stringify({ error: "proxy_error", message: "Could not reach backend" }),
                { status: 502, headers: { "Content-Type": "application/json" } },
            );
        }
    };

    return { GET: proxy, POST: proxy, PUT: proxy, DELETE: proxy, PATCH: proxy };
}
