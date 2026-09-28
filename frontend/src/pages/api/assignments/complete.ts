import type { APIRoute } from "astro";

import { completeErrorMessage, completeSuccessMessage } from "../../../lib/completeMessages";

/**
 * POST /api/assignments/complete — marks an assignment completed.
 *
 * Two response modes:
 * - Form posts (default): 302 back to `next` with a flash cookie (legacy
 *   pages).
 * - `Accept: application/json` (the swipe deck, UX-C1): JSON
 *   `{ ok, message, approval_status? }` with the backend's status, so the
 *   deck can keep a card on failure instead of navigating.
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const wantsJson = (request.headers.get("accept") ?? "").includes("application/json");
    const json = (status: number, body: Record<string, unknown>) =>
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    const token = cookies.get("access_token")?.value;
    const es = (cookies.get("lang")?.value ?? "es") === "es";

    if (!token) {
        return wantsJson
            ? json(401, { ok: false, message: es ? "Inicia sesión de nuevo." : "Please sign in again." })
            : new Response(null, { status: 302, headers: { Location: "/login" } });
    }

    let returnTo = "/dashboard";
    try {
        const formData = await request.formData();
        const assignmentId = formData.get("assignment_id")?.toString();
        const proofTextRaw = formData.get("proof_text")?.toString();
        const proofText = proofTextRaw && proofTextRaw.trim().length > 0 ? proofTextRaw.trim() : null;
        const proofImageRaw = formData.get("proof_image_url")?.toString();
        const proofImageUrl = proofImageRaw && proofImageRaw.trim().length > 0 ? proofImageRaw.trim() : null;
        // Where to land after completing — parents complete their own tasks
        // from /parent, kids from /dashboard. Same-origin relative paths only:
        // reject protocol-relative (//) and backslashes (browsers normalize
        // "\" to "/" in Location, so "/\evil.com" would become "//evil.com").
        const nextRaw = formData.get("next")?.toString() ?? "";
        returnTo =
            nextRaw.startsWith("/") && !nextRaw.startsWith("//") && !nextRaw.includes("\\")
                ? nextRaw
                : "/dashboard";

        if (!assignmentId) {
            const msg = es ? "Falta la tarea." : "Assignment ID is required";
            if (wantsJson) return json(400, { ok: false, message: msg });
            const headers = new Headers({ Location: returnTo });
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent(msg)}; Path=/`);
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

        if (!response.ok) {
            const error = await response.json().catch(() => ({}) as any);
            const detail = typeof error?.detail === "string" ? error.detail : "";
            const msg = completeErrorMessage(response.status, detail, es);
            if (wantsJson) return json(response.status, { ok: false, message: msg });
            const headers = new Headers({ Location: returnTo });
            headers.append("Set-Cookie", `flash_error=${encodeURIComponent(msg)}; Path=/`);
            return new Response(null, { status: 302, headers });
        }

        const assignment = await response.json().catch(() => ({}) as any);
        const msg = completeSuccessMessage(assignment, es);
        if (wantsJson) {
            return json(200, { ok: true, message: msg, approval_status: assignment?.approval_status ?? null });
        }
        // Success flash drives the page's celebration ([data-flash-success]).
        const headers = new Headers({ Location: returnTo });
        headers.append("Set-Cookie", `flash=${encodeURIComponent(msg)}; Path=/; Max-Age=15`);
        return new Response(null, { status: 302, headers });
    } catch (e) {
        console.error("Complete assignment error:", e);
        const msg = completeErrorMessage(500, "", es);
        if (wantsJson) return json(500, { ok: false, message: msg });
        const headers = new Headers({ Location: returnTo });
        headers.append("Set-Cookie", `flash_error=${encodeURIComponent(msg)}; Path=/`);
        return new Response(null, { status: 302, headers });
    }
};
