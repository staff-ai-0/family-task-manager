import type { APIRoute } from "astro";

const API = import.meta.env.API_BASE_URL ?? "http://backend:8000";

/** GET /api/auth/me-status
 *  Returns email_verified status for the current user (uses httpOnly cookie).
 *  Returns {verified: true} if not logged in (no banner needed).
 */
export const GET: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ verified: true }), {
            headers: { "Content-Type": "application/json" },
        });
    }
    try {
        const res = await fetch(`${API}/api/auth/me`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
            return new Response(JSON.stringify({ verified: true }), {
                headers: { "Content-Type": "application/json" },
            });
        }
        const user = await res.json();
        return new Response(JSON.stringify({ verified: !!user.email_verified, email: user.email }), {
            headers: { "Content-Type": "application/json" },
        });
    } catch {
        return new Response(JSON.stringify({ verified: true }), {
            headers: { "Content-Type": "application/json" },
        });
    }
};
