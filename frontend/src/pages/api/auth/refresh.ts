import type { APIRoute } from "astro";
import { refreshAccessToken } from "../../../lib/server/refresh";

export const POST: APIRoute = async ({ cookies }) => {
    const refreshToken = cookies.get("refresh_token")?.value ?? "";
    const result = await refreshAccessToken(refreshToken);
    if (!result.ok) {
        return new Response(JSON.stringify({ ok: false }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }
    const headers = new Headers({ "Content-Type": "application/json" });
    for (const c of result.setCookies!) headers.append("Set-Cookie", c);
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers });
};
