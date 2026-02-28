import type { APIRoute } from "astro";
import type { LoginResponse, ApiError } from "../../../types/api";

/**
 * POST /api/auth/login
 * Authenticates a user and sets an httpOnly access_token cookie
 */
export const POST: APIRoute = async ({ request, cookies, redirect }) => {
    try {
        const formData = await request.formData();
        const email = formData.get("email")?.toString();
        const password = formData.get("password")?.toString();

        if (!email || !password) {
            cookies.set("login_error", "Email and password are required", { path: "/" });
            return redirect("/login", 302);
        }

        const apiUrl = process.env.PUBLIC_API_URL ?? "http://localhost:8002";
        const response = await fetch(`${apiUrl}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });

        if (response.ok) {
            const result: LoginResponse = await response.json();
            
            cookies.set("access_token", result.access_token, {
                path: "/",
                httpOnly: true,
                sameSite: "lax",
                maxAge: 60 * 60 * 24 * 7, // 7 days
                secure: import.meta.env.PROD, // Only use secure in production
            });

            return redirect("/dashboard", 302);
        } else {
            const errData: ApiError = await response.json();
            cookies.set("login_error", errData.detail || "Invalid email or password", { path: "/" });
            return redirect("/login", 302);
        }
    } catch (e) {
        console.error("Login error:", e);
        cookies.set("login_error", "An error occurred connecting to the server", { path: "/" });
        return redirect("/login", 302);
    }
};
