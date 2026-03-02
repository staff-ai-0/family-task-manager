/**
 * Sync Trigger API Endpoint (Proxy to Backend)
 * 
 * This endpoint proxies sync requests from the frontend to the backend API.
 */
import type { APIRoute } from "astro";

const API_BASE_URL = process.env.PUBLIC_API_URL ?? "http://localhost:8002";

export const POST: APIRoute = async ({ request, cookies, url }) => {
    // Get token from cookies
    const token = cookies.get("access_token")?.value;
    
    if (!token) {
        return new Response(
            JSON.stringify({ detail: "Unauthorized" }),
            { status: 401, headers: { "Content-Type": "application/json" } }
        );
    }

    // Get query parameters
    const direction = url.searchParams.get("direction") || "both";
    const dryRun = url.searchParams.get("dry_run") === "true";

    try {
        // Forward request to backend
        const response = await fetch(
            `${API_BASE_URL}/api/sync/trigger?direction=${direction}&dry_run=${dryRun}`,
            {
                method: "POST",
                headers: {
                    "Authorization": `Bearer ${token}`,
                    "Content-Type": "application/json",
                },
            }
        );

        const data = await response.json();

        return new Response(JSON.stringify(data), {
            status: response.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (error) {
        console.error("Sync trigger error:", error);
        return new Response(
            JSON.stringify({ 
                detail: error instanceof Error ? error.message : "Failed to trigger sync"
            }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
