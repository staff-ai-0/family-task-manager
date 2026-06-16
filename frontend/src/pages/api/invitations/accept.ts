import type { APIRoute } from "astro";
import type { LoginResponse } from "../../../types/api";
import { authCookies } from "../../../lib/auth-cookies";

/**
 * POST /api/invitations/accept
 * Accepts a family invitation and creates/links user to family
 * Public endpoint - does not require authentication
 */
export const POST: APIRoute = async ({ request }) => {
    try {
        const body = await request.json();
        const { invitation_code, password, name } = body;

        if (!invitation_code || !password || !name) {
            return new Response(
                JSON.stringify({ success: false, error: "invitation_code, password, and name are required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const response = await fetch(`${apiUrl}/api/invitations/accept`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ invitation_code, password, name }),
        });

        const data = await response.json();

        if (response.ok) {
            const result = data as LoginResponse;
            const cookies = authCookies(result.access_token, result.refresh_token, !import.meta.env.DEV);
            const headers = new Headers({ "Content-Type": "application/json" });
            for (const c of cookies) headers.append("Set-Cookie", c);
            return new Response(
                JSON.stringify({ success: true, redirect: "/dashboard" }),
                { status: 200, headers }
            );
        }

        const errorMessage = data.detail || "Failed to accept invitation";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Accept invitation error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
