import type { APIRoute } from "astro";

/**
 * POST /api/auth/logout
 * Logs out a user by deleting the access_token cookie
 */
export const POST: APIRoute = async ({ request }) => {
    // Delete cookie both with and without Secure flag to handle HTTP and HTTPS environments
    const headers = new Headers({ Location: "/login" });
    headers.append("Set-Cookie", "access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0");
    headers.append("Set-Cookie", "access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Secure");
    return new Response(null, { status: 302, headers });
};
