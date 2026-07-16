import type { APIRoute } from "astro";
import { apiFetch } from "../../../lib/api";

export const POST: APIRoute = async ({ params, request, cookies }) => {
    const { id } = params;
    const token = cookies.get("access_token")?.value;

    if (!token) {
        return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401 });
    }

    const { ok, data, error, status } = await apiFetch(`/api/task-templates/${id}/translate`, {
        method: "POST",
        token,
    });

    if (!ok) {
        // Pass the backend status through (e.g. 403 upgrade_required for the
        // ai_features plan gate) instead of flattening everything to 500.
        return new Response(JSON.stringify({ error }), { status: status || 500 });
    }

    return new Response(JSON.stringify(data), { status: 200 });
};
