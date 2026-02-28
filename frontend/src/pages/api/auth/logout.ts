import type { APIRoute } from "astro";

/**
 * POST /api/auth/logout
 * Logs out a user by deleting the access_token cookie
 */
export const POST: APIRoute = async () => {
    // Manually construct response with Set-Cookie to ensure cookie deletion
    // works reliably with @astrojs/node adapter
    const headers = new Headers({ Location: "/login" });
    headers.append("Set-Cookie", "access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0");
    return new Response(null, { status: 302, headers });
};
