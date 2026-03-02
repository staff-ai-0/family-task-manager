import type { APIRoute } from "astro";

const API = import.meta.env.API_BASE_URL ?? "http://backend:8000";

/** POST /api/auth/verify-email  — proxies to backend */
export const POST: APIRoute = async ({ request }) => {
    try {
        const body = await request.json();
        const res = await fetch(`${API}/api/auth/verify-email`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
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
