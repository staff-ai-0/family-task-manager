/**
 * Forward the Cloudflare-set client IP to the backend (WS-F1).
 *
 * The backend rate limiter keys on CF-Connecting-IP (set/overwritten by the
 * Cloudflare edge, so not client-forgeable through the tunnel). Browser
 * traffic reaches the backend through these SSR proxy routes, whose fetch()
 * would otherwise arrive from the frontend container's IP — collapsing every
 * real user into ONE shared rate-limit bucket. Spreading these headers into
 * the proxied request keeps per-user buckets intact.
 *
 * Returns {} when the header is absent (local dev, tests, direct access) so
 * the backend falls back to its socket-peer key as before.
 */
export function clientIpHeaders(request: Request): Record<string, string> {
    const ip = request.headers.get("cf-connecting-ip");
    return ip ? { "CF-Connecting-IP": ip } : {};
}
