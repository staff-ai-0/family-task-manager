import type { APIRoute } from "astro";
import type { LoginResponse } from "../../../types/api";
import { authCookies } from "../../../lib/auth-cookies";

/**
 * POST /api/auth/register
 * Creates a new family + founding PARENT user, sets httpOnly cookie, and returns JSON.
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    try {
        const body = await request.json();
        const { family_name, family_code, name, email, password, preferred_lang, role } = body;
        // Carry the UI language into the account so the welcome email + first
        // login render in the user's language. Fall back to the lang cookie.
        const lang = preferred_lang === "es" || preferred_lang === "en"
            ? preferred_lang
            : (cookies.get("lang")?.value === "es" ? "es" : "en");

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
        const registerBody: Record<string, string> = { name, email, password, preferred_lang: lang };

        if (family_code) {
            registerBody.family_code = family_code;
            if (role === "child" || role === "teen" || role === "parent") {
                registerBody.role = role;
            }
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
            const result = data as LoginResponse;
            const authCks = authCookies(result.access_token, result.refresh_token, !import.meta.env.DEV);
            const headers = new Headers({ "Content-Type": "application/json" });
            for (const c of authCks) headers.append("Set-Cookie", c);
            // Seed the UI language cookie so the dashboard renders in the chosen language.
            cookies.set("lang", lang, { path: "/", sameSite: "lax", maxAge: 60 * 60 * 24 * 365 });
            // Parents land on the parent dashboard (getting-started checklist);
            // kids/teens land on the kid task dashboard.
            const isParent = (data as any)?.user?.role === "parent";
            return new Response(
                JSON.stringify({ success: true, redirect: isParent ? "/parent" : "/dashboard" }),
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
