import type { APIRoute } from "astro";

function buildCookie(name: string, value: string, options: {
    path?: string;
    httpOnly?: boolean;
    sameSite?: string;
    maxAge?: number;
    secure?: boolean;
}): string {
    let cookie = `${name}=${encodeURIComponent(value)}`;
    if (options.path) cookie += `; Path=${options.path}`;
    if (options.httpOnly) cookie += "; HttpOnly";
    if (options.secure) cookie += "; Secure";
    if (options.sameSite) cookie += `; SameSite=${options.sameSite}`;
    if (options.maxAge !== undefined) cookie += `; Max-Age=${options.maxAge}`;
    return cookie;
}

/**
 * POST /api/auth/register
 * Creates a new family + founding PARENT user, sets httpOnly cookie, and returns JSON.
 */
export const POST: APIRoute = async ({ request }) => {
    try {
        const body = await request.json();
        const { family_name, family_code, name, email, password } = body;

        // Validate required fields
        if (!name || !email || !password) {
            return new Response(
                JSON.stringify({ success: false, error: "All fields are required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        // Either family_code or family_name must be provided
        if (!family_code && !family_name) {
            return new Response(
                JSON.stringify({ success: false, error: "Family code or family name is required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const registerBody: Record<string, string> = { name, email, password };
        
        if (family_code) {
            registerBody.family_code = family_code;
        } else {
            registerBody.family_name = family_name;
        }

        const response = await fetch(`${apiUrl}/api/auth/register-family`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(registerBody),
        });

        const data = await response.json();

        if (response.ok) {
            const tokenCookie = buildCookie("access_token", data.access_token, {
                path: "/",
                httpOnly: true,
                sameSite: "Lax",
                maxAge: 60 * 60 * 24 * 7, // 7 days
                secure: !import.meta.env.DEV, // Only secure in production
            });
            const headers = new Headers({ "Content-Type": "application/json" });
            headers.append("Set-Cookie", tokenCookie);
            return new Response(
                JSON.stringify({ success: true, redirect: "/dashboard" }),
                { status: 200, headers }
            );
        }

        const errorMessage = data.detail || "Registration failed. Please try again.";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Register error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
