import type { APIRoute } from "astro";

export const POST: APIRoute = async ({ request }) => {
    const formData = await request.formData();
    const lang = formData.get("lang")?.toString();
    const referer = request.headers.get("referer") || "/dashboard";

    const headers = new Headers({ Location: referer });
    
    if (lang === "en" || lang === "es") {
        headers.append(
            "Set-Cookie",
            `lang=${lang}; Path=/; Max-Age=${60 * 60 * 24 * 365}; SameSite=Lax`
        );
    }

    return new Response(null, { status: 302, headers });
};
