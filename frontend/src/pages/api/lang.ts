import type { APIRoute } from "astro";

export const POST: APIRoute = async ({ request, cookies }) => {
    const formData = await request.formData();
    const lang = formData.get("lang")?.toString();
    const referer = request.headers.get("referer") || "/dashboard";

    const headers = new Headers({ Location: referer });

    if (lang === "en" || lang === "es") {
        headers.append(
            "Set-Cookie",
            `lang=${lang}; Path=/; Max-Age=${60 * 60 * 24 * 365}; SameSite=Lax`
        );

        // Persist the choice on the account too, so login on another device
        // restores it — otherwise the preference drifts per browser.
        const token = cookies.get("access_token")?.value;
        if (token) {
            try {
                const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://backend:8000";
                await fetch(`${apiUrl}/api/auth/me`, {
                    method: "PUT",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${token}`,
                    },
                    body: JSON.stringify({ preferred_lang: lang }),
                    // Don't let a slow backend hold the toggle's redirect hostage.
                    signal: AbortSignal.timeout(1500),
                });
            } catch {
                // cookie is already set; account sync is best-effort
            }
        }
    }

    return new Response(null, { status: 302, headers });
};
