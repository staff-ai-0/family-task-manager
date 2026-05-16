import type { APIRoute } from "astro";

/**
 * POST /api/assignments/patch
 *
 * Forwards a form submission to PATCH /api/task-assignments/{id} on the backend.
 * Form fields: assignment_id, assigned_to?, assigned_date?, status?
 * Empty string fields are stripped from the payload.
 */
export const POST: APIRoute = async ({ request, cookies, redirect }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(null, { status: 302, headers: { Location: "/login" } });
    }

    const referer = request.headers.get("referer") || "/parent/assignments";

    try {
        const formData = await request.formData();
        const assignmentId = formData.get("assignment_id")?.toString();
        if (!assignmentId) {
            const headers = new Headers({ Location: referer });
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent("Assignment ID missing")}; Path=/`);
            return new Response(null, { status: 302, headers });
        }

        const payload: Record<string, unknown> = {};
        const assignedTo = formData.get("assigned_to")?.toString();
        const assignedDate = formData.get("assigned_date")?.toString();
        const status = formData.get("status")?.toString();
        if (assignedTo) payload.assigned_to = assignedTo;
        if (assignedDate) payload.assigned_date = assignedDate;
        if (status) payload.status = status;

        if (Object.keys(payload).length === 0) {
            const headers = new Headers({ Location: referer });
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent("No changes provided")}; Path=/`);
            return new Response(null, { status: 302, headers });
        }

        const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://backend:8000";
        const response = await fetch(`${apiUrl}/api/task-assignments/${assignmentId}`, {
            method: "PATCH",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });

        const headers = new Headers({ Location: referer });
        if (!response.ok) {
            let detail = "Failed to update assignment";
            try {
                const err = await response.json();
                detail = err.detail || detail;
            } catch {}
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent(detail)}; Path=/`);
        } else {
            headers.append("Set-Cookie", `flash=${encodeURIComponent("Assignment updated")}; Path=/`);
        }
        return new Response(null, { status: 302, headers });
    } catch (e) {
        console.error("Patch assignment error:", e);
        const headers = new Headers({ Location: referer });
        headers.append("Set-Cookie", `flash_error=${encodeURIComponent("Server error")}; Path=/`);
        return new Response(null, { status: 302, headers });
    }
};
