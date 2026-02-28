import type { APIRoute } from "astro";
import type { LoginResponse, ApiError } from "../../../types/api";

/**
 * Helper to build a Set-Cookie header string.
 * We construct this manually because Astro's cookies.set() + redirect()
 * has a known issue in @astrojs/node where cookies may not be attached
 * to redirect responses.
 */
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
 * POST /api/auth/login
 * Authenticates a user and sets an httpOnly access_token cookie.
 * 
 * Supports two submission modes:
 * - JSON body (from fetch): returns JSON response with success/error
 * - Form data (native form): returns redirect response
 */
export const POST: APIRoute = async ({ request }) => {
    const contentType = request.headers.get("content-type") || "";
    const isJsonRequest = contentType.includes("application/json");

    try {
        let email: string | undefined;
        let password: string | undefined;

        if (isJsonRequest) {
            const body = await request.json();
            email = body.email;
            password = body.password;
        } else {
            const formData = await request.formData();
            email = formData.get("email")?.toString();
            password = formData.get("password")?.toString();
        }

        if (!email || !password) {
            if (isJsonRequest) {
                return new Response(
                    JSON.stringify({ success: false, error: "Email and password are required" }),
                    { status: 400, headers: { "Content-Type": "application/json" } }
                );
            }
            const headers = new Headers({ Location: "/login" });
            headers.append("Set-Cookie", buildCookie("login_error", "Email and password are required", { path: "/" }));
            return new Response(null, { status: 302, headers });
        }

        const apiUrl = process.env.PUBLIC_API_URL ?? "http://localhost:8002";
        const response = await fetch(`${apiUrl}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });

        if (response.ok) {
            const result: LoginResponse = await response.json();
            
            const tokenCookie = buildCookie("access_token", result.access_token, {
                path: "/",
                httpOnly: true,
                sameSite: "Lax",
                maxAge: 60 * 60 * 24 * 7, // 7 days
                secure: import.meta.env.PROD,
            });

            if (isJsonRequest) {
                // For fetch-based login: return JSON + Set-Cookie header
                const headers = new Headers({ "Content-Type": "application/json" });
                headers.append("Set-Cookie", tokenCookie);
                return new Response(
                    JSON.stringify({ success: true, redirect: "/dashboard" }),
                    { status: 200, headers }
                );
            }

            // For native form POST: manually construct redirect with cookie
            const headers = new Headers({ Location: "/dashboard" });
            headers.append("Set-Cookie", tokenCookie);
            return new Response(null, { status: 302, headers });
        } else {
            let errorMessage = "Invalid email or password";
            try {
                const errData: ApiError = await response.json();
                errorMessage = errData.detail || errorMessage;
            } catch {
                // If response isn't JSON, use default message
            }

            if (isJsonRequest) {
                return new Response(
                    JSON.stringify({ success: false, error: errorMessage }),
                    { status: 401, headers: { "Content-Type": "application/json" } }
                );
            }

            const headers = new Headers({ Location: "/login" });
            headers.append("Set-Cookie", buildCookie("login_error", errorMessage, { path: "/" }));
            return new Response(null, { status: 302, headers });
        }
    } catch (e) {
        console.error("Login error:", e);
        const errorMessage = "An error occurred connecting to the server";

        if (isJsonRequest) {
            return new Response(
                JSON.stringify({ success: false, error: errorMessage }),
                { status: 500, headers: { "Content-Type": "application/json" } }
            );
        }

        const headers = new Headers({ Location: "/login" });
        headers.append("Set-Cookie", buildCookie("login_error", errorMessage, { path: "/" }));
        return new Response(null, { status: 302, headers });
    }
};
