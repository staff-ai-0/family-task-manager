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
  // Themed content landing — "rutinas para niños con TDAH" (SEO_ASO.md §2.4),
  // a high-empathy, low-competition Spanish long-tail wedge.
  { path: "/tdah", changefreq: "monthly", priority: "0.8" },
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
      title: "Family Task Manager — Tareas, dinero y finanzas para toda la familia",
      description:
        "El sistema operativo de tu familia: tareas que se reparten solas, puntos y dinero real, presupuesto por sobres nivel pro con escáner de recibos IA y copiloto, más comidas, compras, calendario y mascota. Bilingüe. Empieza gratis, sin tarjeta.",
    },
    en: {
      title: "Family Task Manager — Chores, money & finances for the whole family",
      description:
        "Your family's operating system: self-assigning chores, points and real cash, pro-grade envelope budgeting with an AI receipt scanner and copilot, plus meals, shopping, calendar and a virtual pet. Bilingual. Start free, no card needed.",
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
  "/tdah": {
    es: {
      title: "Rutinas para niños con TDAH — tablero visual y hábitos | Family Task",
      description:
        "Crea rutinas para niños con TDAH que sí funcionan: tablero visual, pasos pequeños y logros frecuentes. Cada rutina completada alimenta a la mascota de tu hijo(a) y suma puntos canjeables. Empieza gratis, en español.",
    },
    en: {
      title: "Routines for kids with ADHD — visual board & habits | Family Task",
      description:
        "Build ADHD routines that actually stick: a visual board, small steps, and frequent wins. Every finished routine feeds your kid's pet and earns redeemable points. Start free, bilingual Spanish/English.",
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

/**
 * FAQ for the /tdah landing page. Kept here (not inline in the page) so the
 * visible <details> list and the FAQPage JSON-LD render from a single source —
 * Google requires the structured answers to match the on-page text.
 */
export interface FaqItem {
  q: string;
  a: string;
}

export function tdahFaq(lang: string): FaqItem[] {
  const es = lang === "es";
  return es
    ? [
        {
          q: "¿Cómo ayudan las rutinas a un niño con TDAH?",
          a: "El cerebro con TDAH responde mejor a estructuras visibles y a recompensas inmediatas. Un tablero visual divide el día en pasos pequeños y cada paso completado da un logro al instante, así se reduce la fricción para empezar y se refuerza el hábito sin regaños.",
        },
        {
          q: "¿Family Task es un tratamiento médico para el TDAH?",
          a: "No. Es una herramienta de apoyo para crear rutinas y hábitos en casa. No reemplaza la evaluación ni el tratamiento de un profesional de la salud; funciona muy bien como complemento del plan que ya sigan en familia.",
        },
        {
          q: "¿Cómo funciona el bucle de mascota + rutina?",
          a: "Cada rutina o tarea completada suma puntos y alimenta a la mascota virtual de tu hijo(a). Ver a la mascota feliz da una recompensa inmediata y visual que motiva a volver mañana, convirtiendo la constancia en un juego en lugar de una pelea.",
        },
        {
          q: "¿Los puntos se convierten en dinero?",
          a: "No. Los puntos se canjean por privilegios y premios que la familia define (tiempo de pantalla, elegir la música, tiempo especial 1 a 1). El dinero real vive aparte, en el tablero de gigs, para trabajos extra de adolescentes.",
        },
        {
          q: "¿Está en español y es gratis para empezar?",
          a: "Sí. La app es bilingüe español e inglés, pensada primero para México, y puedes empezar con el plan gratuito sin tarjeta. Incluye un paquete de inicio 'TDAH y rutinas' listo para cargar en un toque.",
        },
      ]
    : [
        {
          q: "How do routines help a child with ADHD?",
          a: "The ADHD brain responds best to visible structure and immediate rewards. A visual board breaks the day into small steps and every finished step gives an instant win, lowering the friction to start and reinforcing the habit without nagging.",
        },
        {
          q: "Is Family Task a medical treatment for ADHD?",
          a: "No. It is a support tool for building routines and habits at home. It does not replace evaluation or treatment by a health professional; it works well alongside whatever plan your family already follows.",
        },
        {
          q: "How does the pet + routine loop work?",
          a: "Every completed routine or task earns points and feeds your kid's virtual pet. Seeing the pet happy is an immediate, visual reward that motivates them to come back tomorrow — turning consistency into a game instead of a fight.",
        },
        {
          q: "Do points turn into money?",
          a: "No. Points are redeemed for privileges and rewards your family defines (screen time, picking the music, special 1-on-1 time). Real cash lives separately, on the gigs board, for extra jobs teens take on.",
        },
        {
          q: "Is it in Spanish and free to start?",
          a: "Yes. The app is bilingual Spanish/English, Mexico-first, and you can start on the free plan with no card. It ships with an 'ADHD & routines' starter pack you can load in one tap.",
        },
      ];
}

/** schema.org FAQPage node built from a q/a list (matches the visible FAQ). */
export function faqPageJsonLd(items: FaqItem[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((it) => ({
      "@type": "Question",
      name: it.q,
      acceptedAnswer: { "@type": "Answer", text: it.a },
    })),
  };
}
