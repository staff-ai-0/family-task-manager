/**
 * /robots.txt — allow crawling of the public marketing/legal/help surface,
 * disallow the authenticated app + API/upload routes, and point at the sitemap.
 * Server endpoint (Astro `output: 'server'`). Whitelisted in middleware.ts.
 */
import type { APIRoute } from "astro";
import { SITE_URL } from "../lib/seo";

export const prerender = false;

// Authenticated app + utility routes that add no SEO value and should stay out
// of the index (crawlers bounce off the /login redirect anyway; this is belt +
// suspenders so we don't have to noindex each page file individually).
const DISALLOW = [
  "/api/",
  "/uploads/",
  "/dashboard",
  "/parent",
  "/budget",
  "/gigs",
  "/rewards",
  "/bank",
  "/pet",
  "/profile",
  "/notifications",
  "/chat",
  "/dm",
  "/calendar",
  "/meals",
  "/shopping",
  "/kiosk",
  "/pricing",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/accept-invitation",
];

export const GET: APIRoute = () => {
  const body = [
    "User-agent: *",
    "Allow: /",
    ...DISALLOW.map((p) => `Disallow: ${p}`),
    "",
    `Sitemap: ${SITE_URL}/sitemap.xml`,
    "",
  ].join("\n");

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
};
