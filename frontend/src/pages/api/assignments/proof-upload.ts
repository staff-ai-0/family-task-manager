import type { APIRoute } from "astro";

/**
 * POST /api/assignments/proof-upload
 * Forwards a multipart file upload to backend's gig proof upload endpoint.
 * Body: multipart/form-data with "file" field.
 * Returns: { proof_image_url: "/uploads/gig-proofs/<id>.<ext>" }
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }

    const apiUrl =
        process.env.API_BASE_URL ||
        process.env.PUBLIC_API_BASE_URL ||
        "http://backend:8000";

    try {
        // Read the inbound form-data and forward as-is. We don't reconstruct
        // a new FormData (which loses the original Content-Type boundary on
        // Node fetch in some versions) — just stream the raw body.
        const inbound = await request.formData();
        const fwd = new FormData();
        const file = inbound.get("file");
        if (!file || typeof file === "string") {
            return new Response(JSON.stringify({ detail: "file required" }), {
                status: 400,
                headers: { "Content-Type": "application/json" },
            });
        }
        fwd.append("file", file);

        const r = await fetch(`${apiUrl}/api/task-assignments/proof-upload`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
            body: fwd,
        });
        const text = await r.text();
        return new Response(text, {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("proof-upload proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
