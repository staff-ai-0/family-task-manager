/**
 * SEO helpers — canonical origin, per-page localized metadata, sitemap route
 * table, and JSON-LD builders.
 *
 * The public marketing/legal surface (landing, register, login, privacy, terms,
 * help/ayuda) is Mexico-first: Spanish is the default language and the metadata
 * below is written Spanish-first for the long-tail keywords documented in
 * `docs/SEO_ASO.md`. Consumed by:
 *   - `components/meta/Head.astro` — canonical + hreflang + Open Graph + JSON-LD
 *   - `pages/sitemap.xml.ts` / `pages/robots.txt.ts` — crawl surface
 *   - the public pages themselves — localized <title> + meta description
 *
 * There is a single URL per page (locale is chosen by the `lang` cookie /
 * Accept-Language, not by path), so canonical is self-referential and the
 * es/en hreflang alternates point at the same URL except for the guide pages
 * (/ayuda ↔ /help) which have genuinely distinct per-language URLs.
 */

/** Canonical production origin (on-prem 10.1.0.91 behind the Cloudflare tunnel). */
export const SITE_URL = "https://family.agent-ia.mx";

/** Default social-share image (1200×630, lives in /public). */
export const DEFAULT_OG_IMAGE = "/og.png";

export type Lang = "en" | "es";

/** Absolutize a path onto the canonical origin; pass through absolute URLs. */
export function absoluteUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  const path = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${SITE_URL}${path}`;
}

/** Normalize a request pathname for use as a canonical (drop trailing slash except root). */
export function canonicalPath(pathname: string): string {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

/** Public, indexable routes enumerated in sitemap.xml — most important first. */
export const SITEMAP_ROUTES: { path: string; changefreq: string; priority: string }[] = [
  { path: "/", changefreq: "weekly", priority: "1.0" },
  { path: "/register", changefreq: "monthly", priority: "0.9" },
  { path: "/ayuda", changefreq: "monthly", priority: "0.7" },
  { path: "/help", changefreq: "monthly", priority: "0.6" },
  { path: "/login", changefreq: "yearly", priority: "0.4" },
  { path: "/privacidad", changefreq: "yearly", priority: "0.3" },
  { path: "/terminos", changefreq: "yearly", priority: "0.3" },
];

interface SeoCopy {
  title: string;
  description: string;
}

/**
 * Localized <title> + meta description for the pages that don't already build
 * their own bilingual meta object. (privacidad/terminos keep their in-file meta
 * objects and add a `description`; help/ayuda pass through GuideShell.)
 */
const PAGE_SEO: Record<string, { es: SeoCopy; en: SeoCopy }> = {
  "/": {
    es: {
      title: "Family Task Manager — App de tareas y recompensas para niños",
      description:
        "App familiar para asignar quehaceres del hogar, premiar a los niños con puntos y recompensas, y llevar el presupuesto familiar. Bilingüe español e inglés. Empieza gratis, sin tarjeta.",
    },
    en: {
      title: "Family Task Manager — Chores, rewards & budget for families",
      description:
        "A gamified family app to assign household chores, reward kids with points and prizes, and manage the family budget. Bilingual English and Spanish. Start free, no card needed.",
    },
  },
  "/register": {
    es: {
      title: "Crear cuenta gratis — Family Task Manager",
      description:
        "Crea tu familia en minutos y empieza a organizar tareas, recompensas y finanzas. Sin tarjeta de crédito. App gamificada de quehaceres para niños de 6 a 17 años.",
    },
    en: {
      title: "Create your free account — Family Task Manager",
      description:
        "Set up your family in minutes and start organizing chores, rewards, and finances. No credit card needed. Gamified chore app for kids ages 6 to 17.",
    },
  },
  "/login": {
    es: {
      title: "Iniciar sesión — Family Task Manager",
      description:
        "Entra a tu cuenta de Family Task Manager para gestionar tareas, puntos, recompensas y el presupuesto de tu familia.",
    },
    en: {
      title: "Sign in — Family Task Manager",
      description:
        "Log in to your Family Task Manager account to manage chores, points, rewards, and your family budget.",
    },
  },
};

/** Localized title + description for a public path, or null if none is centralized here. */
export function seoFor(path: string, lang: string): SeoCopy | null {
  const entry = PAGE_SEO[path];
  if (!entry) return null;
  return lang === "es" ? entry.es : entry.en;
}

/** schema.org Organization node for the landing page. */
export function organizationJsonLd() {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "Family Task Manager",
    url: SITE_URL,
    logo: absoluteUrl("/icon-512.png"),
    image: absoluteUrl(DEFAULT_OG_IMAGE),
    email: "soporte@agent-ia.mx",
    contactPoint: {
      "@type": "ContactPoint",
      email: "soporte@agent-ia.mx",
      contactType: "customer support",
      availableLanguage: ["Spanish", "English"],
    },
  };
}

/** schema.org SoftwareApplication (WebApplication) node for the landing page. */
export function softwareAppJsonLd(lang: string) {
  const es = lang === "es";
  return {
    "@context": "https://schema.org",
    "@type": "WebApplication",
    name: "Family Task Manager",
    url: SITE_URL,
    image: absoluteUrl(DEFAULT_OG_IMAGE),
    applicationCategory: "LifestyleApplication",
    operatingSystem: "Web, iOS, Android",
    inLanguage: ["es", "en"],
    description: es
      ? "App familiar gamificada para asignar tareas y quehaceres del hogar, premiar a los niños con puntos y recompensas, y llevar el presupuesto familiar por sobres."
      : "Gamified family app to assign household chores, reward kids with points and prizes, and run an envelope-style family budget.",
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "MXN",
      description: es
        ? "Plan gratuito disponible; planes de pago opcionales."
        : "Free plan available; optional paid plans.",
    },
  };
}
