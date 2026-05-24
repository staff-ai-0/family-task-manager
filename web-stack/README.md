# Family Task Manager — Web Stack Handoff

Drop-in folder for an **Astro + Tailwind v4** project. Every brand token,
component, asset, and meta tag the front-end needs in one place.

> Companion to `Brand Guide.html` — the guide documents the system, this
> folder ships the system.

---

## 0 · Install

```bash
cd web-stack
pnpm install        # or: npm install / yarn / bun
pnpm dev            # localhost:4321
```

Tested against Astro 5.x and Tailwind v4.

---

## 1 · What's inside

```
web-stack/
├── astro.config.mjs              ← Tailwind v4 vite plugin + i18n (EN/ES)
├── tsconfig.json
├── package.json
├── public/                       ← static assets, served at /
│   ├── favicon.svg               ← full mark, modern browsers
│   ├── favicon-16.png            ← check-badge fallback
│   ├── favicon-32.png
│   ├── apple-touch-icon.png      ← 180×180
│   ├── icon-192.png              ← PWA
│   ├── icon-512.png              ← PWA
│   ├── icon-maskable-192.png     ← PWA (80% safe zone, full-bleed sky bg)
│   ├── icon-maskable-512.png
│   ├── ios-icon-1024.png         ← App Store upload
│   ├── og.png                    ← 1200×630 social share
│   └── manifest.webmanifest      ← PWA manifest
└── src/
    ├── styles/
    │   └── global.css            ← Tailwind @theme block, base layer, utilities
    ├── layouts/
    │   └── BaseLayout.astro      ← wraps every page; pulls in <Head/>
    ├── components/
    │   ├── meta/Head.astro       ← favicons, OG, manifest, theme-color, fonts
    │   ├── brand/
    │   │   ├── Mark.astro        ← <Mark size={96} variant="huddle" />
    │   │   ├── Wordmark.astro
    │   │   └── Logo.astro        ← composed lockup
    │   └── ui/
    │       ├── Button.astro      ← press-down hard-shadow button
    │       ├── Card.astro
    │       ├── Badge.astro
    │       └── RoleBadge.astro   ← parent / teen / child
    ├── assets/
    │   └── brand/
    │       ├── mark-huddle.svg   ← raw source SVGs
    │       ├── mark-heart.svg
    │       ├── mark-star.svg
    │       └── favicon-badge.svg
    └── pages/
        └── index.astro           ← demo page using every component
```

---

## 2 · Tailwind v4 setup

`astro.config.mjs` already wires `@tailwindcss/vite`. `src/styles/global.css`
exposes every brand token via the `@theme` block, so you get utilities like:

```html
<div class="bg-brand-sky text-brand-ink">
  <button class="bg-brand-coral border-2 border-brand-ink rounded-full
                 shadow-[var(--shadow-card)] press">
    Start a chore →
  </button>
</div>
```

Tokens shipped: `brand-sky`, `brand-sky-deep`, `brand-coral`, `brand-coral-deep`,
`brand-mint`, `brand-mint-deep`, `brand-sun`, `brand-sun-deep`, `brand-ink`,
`brand-ink-soft`, `brand-cream`, `brand-cream-deep`.

Display sizes: `text-display-1`, `text-display-2`, `text-title`.

Shadows: `shadow-[var(--shadow-card)]` (4px), `--shadow-pop` (6px), `--shadow-stamp` (8px).

Helpers: `.press` (button down-press), `.clip-squircle` (mark-shaped mask),
`.num` (tabular numerals for balances).

---

## 3 · Fonts — pick one strategy

`Head.astro` ships with **Google Fonts CDN** loading by default (simpler, no
extra dep). For prod, prefer self-hosting:

```bash
pnpm add @fontsource-variable/plus-jakarta-sans @fontsource-variable/nunito
```

Then in `src/styles/global.css`, add at the top:

```css
@import "@fontsource-variable/plus-jakarta-sans";
@import "@fontsource-variable/nunito";
```

…and delete the `<link>` block at the bottom of `Head.astro`.

---

## 4 · Dark mode

Dark mode is a `data-theme="dark"` attribute on `<html>` — not a token swap.
`BaseLayout.astro` ships a 4-line inline script that flips the attribute
based on `prefers-color-scheme` before paint, so there's no flash.

To force-pin a page:

```astro
<BaseLayout theme="dark">…</BaseLayout>
```

---

## 5 · i18n (EN · ES)

`astro.config.mjs` registers `en` (default, no prefix) and `es` (`/es/...`).
Routing follows Astro's built-in i18n. Pass `lang="es"` into `<Head/>` and
`<BaseLayout/>` to set OG locale + html lang correctly.

---

## 6 · Re-generating the PNG assets

All PNGs in `/public` are rasterized from `/src/assets/brand/*.svg`. To
regenerate after editing an SVG:

```bash
pnpm add -D sharp
node scripts/rasterize.mjs        # (write this once if you need it)
```

Or use any SVG → PNG pipeline. Required sizes:

| File                       | Size       | Source SVG          | Notes                          |
|---                         |---         |---                  |---                             |
| `favicon-16.png`           | 16×16      | favicon-badge.svg   | Just the check disc            |
| `favicon-32.png`           | 32×32      | favicon-badge.svg   |                                |
| `apple-touch-icon.png`     | 180×180    | mark-huddle.svg     | No alpha. iOS auto-rounds      |
| `icon-192.png`             | 192×192    | mark-huddle.svg     | PWA                            |
| `icon-512.png`             | 512×512    | mark-huddle.svg     | PWA                            |
| `icon-maskable-192.png`    | 192×192    | mark-huddle.svg     | 10% pad + brand-sky bg         |
| `icon-maskable-512.png`    | 512×512    | mark-huddle.svg     | 10% pad + brand-sky bg         |
| `ios-icon-1024.png`        | 1024×1024  | mark-huddle.svg     | App Store, no alpha            |
| `og.png`                   | 1200×630   | composed            | Re-render after copy changes   |

---

## 7 · Voice + copy hooks

Centralize EN/ES strings in `src/i18n/strings.ts` (you'll create this when you
wire pages). Three sanctioned headlines from the brand guide:

```ts
export const taglines = {
  en:    "Chores, rewards, budget — together.",
  es:    "Tareas, premios y presupuesto — en familia.",
  short: "Family, gamified.",
};
```

Voice rules: name the small win, share credit, never punish a missed streak.
See **Brand Guide §10**.

---

## 8 · What's deliberately not here

- **Figma file / ICNS / EPS / brand-guide.pdf** — generate from the SVGs +
  the HTML brand guide as needed.
- **Backend, auth, db** — this is the front-end visual stack only.
- **Component framework choice** — components are plain `.astro`. If you need
  React/Solid/Svelte islands, port the SVG bodies; tokens stay the same.
- **Tests** — add Playwright + axe at the app level, not here.

---

## 9 · License + ownership

Brand mark, palette, type pairings: © Family Task Manager / agent-ia.mx.
Fonts: SIL Open Font License (Plus Jakarta Sans, Nunito).
