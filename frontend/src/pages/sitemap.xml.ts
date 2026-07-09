/**
 * /sitemap.xml — enumerates the public, indexable routes for search engines.
 * Server endpoint (Astro `output: 'server'`). Whitelisted in middleware.ts so
 * it is reachable without auth. Routes + priorities live in lib/seo.ts.
 */
import type { APIRoute } from "astro";
import { SITE_URL, SITEMAP_ROUTES } from "../lib/seo";

export const prerender = false;

export const GET: APIRoute = () => {
  const lastmod = new Date().toISOString().slice(0, 10);

  const urls = SITEMAP_ROUTES.map((r) => {
    const loc = `${SITE_URL}${r.path}`;
    return [
      "  <url>",
      `    <loc>${loc}</loc>`,
      `    <lastmod>${lastmod}</lastmod>`,
      `    <changefreq>${r.changefreq}</changefreq>`,
      `    <priority>${r.priority}</priority>`,
      "  </url>",
    ].join("\n");
  }).join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
};
