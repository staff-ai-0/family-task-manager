import type { APIRoute } from "astro";

/**
 * POST /api/families/join-code/generate
 * Proxy to backend to generate a new family join code
 * Requires authentication
 */
export const POST: APIRoute = async ({ locals }) => {
  try {
    const token = locals.token;
    if (!token) {
      return new Response(
        JSON.stringify({ detail: "Unauthorized" }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }

    const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
    const response = await fetch(`${apiUrl}/api/families/join-code/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });

    const data = await response.json();

    if (response.ok) {
      return new Response(
        JSON.stringify({ success: true, data }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    const errorMessage = typeof data === "string" ? data : data.detail || "Failed to generate join code";
    return new Response(
      JSON.stringify({ success: false, error: errorMessage }),
      { status: response.status, headers: { "Content-Type": "application/json" } }
    );
  } catch (error) {
    console.error("Join code generate error:", error);
    return new Response(
      JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
};
