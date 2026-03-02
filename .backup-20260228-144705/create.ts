import type { APIRoute } from "astro";

/**
 * POST /api/finance/categories/create
 * Proxy endpoint to create categories in Actual Budget via Finance API
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    
    if (!token) {
        return new Response(
            JSON.stringify({ detail: "Unauthorized" }),
            { status: 401, headers: { "Content-Type": "application/json" } }
        );
    }

    try {
        const body = await request.json();
        const { name, group_name } = body;

        if (!name) {
            return new Response(
                JSON.stringify({ detail: "Category name is required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        // Call Finance API to create category with JWT token for family isolation
        const financeApiUrl = process.env.FINANCE_API_URL ?? "http://localhost:5007";
        const response = await fetch(`${financeApiUrl}/api/finance/categories`, {
            method: "POST",
            headers: { 
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`,
            },
            body: JSON.stringify({ 
                name, 
                group_name: group_name || "Usual Expenses" 
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            return new Response(
                JSON.stringify(data),
                { status: response.status, headers: { "Content-Type": "application/json" } }
            );
        }

        return new Response(
            JSON.stringify(data),
            { status: 200, headers: { "Content-Type": "application/json" } }
        );
    } catch (error) {
        console.error("Create category error:", error);
        return new Response(
            JSON.stringify({ 
                detail: error instanceof Error ? error.message : "Failed to create category"
            }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
