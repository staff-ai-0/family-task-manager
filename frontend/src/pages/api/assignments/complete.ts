import type { APIRoute } from "astro";

/**
 * POST /api/assignments/complete
 * Marks an assignment as completed
 */
export const POST: APIRoute = async ({ request, cookies, redirect }) => {
    const token = cookies.get("access_token")?.value;
    
    if (!token) {
        return new Response(null, { status: 302, headers: { Location: "/login" } });
    }

    try {
        const formData = await request.formData();
        const assignmentId = formData.get("assignment_id")?.toString();
        const proofTextRaw = formData.get("proof_text")?.toString();
        const proofText = proofTextRaw && proofTextRaw.trim().length > 0 ? proofTextRaw.trim() : null;
        const proofImageRaw = formData.get("proof_image_url")?.toString();
        const proofImageUrl = proofImageRaw && proofImageRaw.trim().length > 0 ? proofImageRaw.trim() : null;

        if (!assignmentId) {
            const headers = new Headers({ Location: "/dashboard" });
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent("Assignment ID is required")}; Path=/`);
            return new Response(null, { status: 302, headers });
        }

        const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://backend:8000";
        const response = await fetch(`${apiUrl}/api/task-assignments/${assignmentId}/complete`, {
            method: "PATCH",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ proof_text: proofText, proof_image_url: proofImageUrl }),
        });

        const headers = new Headers({ Location: "/dashboard" });

        if (!response.ok) {
            const error = await response.json();
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent(error.detail || "Cannot complete task")}; Path=/`);
        } else {
            // Success flash drives the dashboard's confetti + points pulse
            // ([data-flash-success]) — without it the kid's most frequent
            // action gives zero feedback.
            let msg = "🎉";
            try {
                const a = await response.json();
                const es = cookies.get("lang")?.value === "es";
                const title = (es && a.template_title_es) || a.template_title || "";
                const pending = a.approval_status === "pending" || a.template_is_bonus;
                msg = pending
                    ? (es ? `"${title}" enviada para aprobación 🎉` : `"${title}" submitted for approval 🎉`)
                    : (es ? `¡"${title}" completada! 🎉` : `"${title}" completed! 🎉`);
            } catch {
                // keep the bare celebration if the body can't be parsed
            }
            headers.append("Set-Cookie", `flash=${encodeURIComponent(msg)}; Path=/; Max-Age=15`);
        }

        return new Response(null, { status: 302, headers });
    } catch (e) {
        console.error("Complete assignment error:", e);
        const headers = new Headers({ Location: "/dashboard" });
        headers.append("Set-Cookie", `flash_error=${encodeURIComponent("An error occurred")}; Path=/`);
        return new Response(null, { status: 302, headers });
    }
};
