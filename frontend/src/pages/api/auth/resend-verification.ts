import type { APIRoute } from "astro";

const API = import.meta.env.API_BASE_URL ?? "http://backend:8000";

/** POST /api/auth/resend-verification — proxies to backend (requires auth cookie) */
export const POST: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ message: "Not authenticated." }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }
    try {
        const res = await fetch(`${API}/api/auth/resend-verification`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        return new Response(JSON.stringify(data), {
            status: res.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch {
        return new Response(
            JSON.stringify({ message: "Server error. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
