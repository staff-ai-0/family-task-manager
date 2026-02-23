import type { APIRoute } from "astro";

export const POST: APIRoute = async ({ request, cookies, redirect }) => {
    const formData = await request.formData();
    const lang = formData.get("lang")?.toString();
    const referer = request.headers.get("referer") || "/dashboard";

    if (lang === "en" || lang === "es") {
        cookies.set("lang", lang, {
            path: "/",
            maxAge: 60 * 60 * 24 * 365, // 1 year
            sameSite: "lax",
        });
    }

    return redirect(referer, 302);
};
