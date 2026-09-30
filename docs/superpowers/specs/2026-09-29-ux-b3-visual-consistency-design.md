# UX-B3 — Visual Consistency — Design

**Date:** 2026-09-29
**Status:** design approved in chat (2026-09-29), pending written-spec review
**Program:** UX/GUI/engagement program, sub-project **B3** of B (design-system consolidation). A, C1, C2, B1, B4 shipped. B2 (dark mode) was **dropped** in the same brainstorm: the half-built dark theme is removed here, real dark mode only if families ask.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` F2 + F12; static scan of `frontend/src` on 2026-09-29 (numbers below); WCAG 2.x contrast computed from the `@theme` hex values.

## What is wrong today

1. **Every page picks its own header.** 44 pages use ~25 different Tailwind gradients (violet, amber, rose, indigo, emerald, teal, fuchsia, slate…); 32 use the flat brand "sticker" header (`PageHeader` tone + ink border + hard shadow); budget pages use a flat `bg-brand-sky-deep`; chat screens hardcode white text on a gradient. Color means nothing.
2. **Text that fails contrast (WCAG AA needs ≥ 4.5:1 for body text):**
   | Pair | Ratio | Uses |
   |---|---|---|
   | `text-white` on `bg-brand-sky-deep` | 3.15 | 91 white-on-brand-fill spots in 42 files, all colors |
   | `text-white` on `bg-brand-mint-deep` | 2.55 | (incl. above) |
   | `text-white` on `bg-brand-coral-deep` | 3.18 | (incl. above) |
   | `text-brand-sky-deep` on white / cream | 3.15 / 2.99 | 98 |
   | `text-brand-mint-deep` on white | ≈ 2.5 | 126 |
   | `text-brand-coral-deep` on white | 3.18 | 75 |
   | `text-brand-sun-deep` on white | 2.09 | 50 |
   | `text-slate-500` on cream-deep (page bg) | 3.96 | 67 |
   | `text-slate-400` anywhere | < 3 | 6 |
   The kid home hero (child skin) is itself `bg-brand-sky-deep` + white text (3.15).
3. **Emoji and line icons mixed.** Chrome (bottom nav, More sheet) uses one heroicons-outline set, but 6 page titles carry an emoji prefix (🏦 ✉️ 💬 🛟 🤖 ✉️), next to line-icon buttons.
4. **UI kit barely used.** `BottomSheet` 0 imports, `FormField` 0 (dialogs now live in `AppDialog`), `Card` 2, `EmptyState` 1, `Button` 6.
5. **Half-built dark theme.** `Layout.astro` sets `data-theme="dark"` from the OS preference; `global.css` `[data-theme="dark"]` only remaps `--bg/--fg/--surface` + coral/mint, the body stays light — the only visible "dark" is the overscroll edge and the dark `theme-color` status bar.

**Goal:** the app looks like one product — one header shape whose color means the section, readable text everywhere, one icon rule — and CI keeps it that way.

**Decisions from the brainstorm:**
- Headers → **B · color = section**: one shape (flat brand fill, ink title, ink outline, hard shadow); one brand color per section.
- Icons → **split by job**: line icons for chrome; emoji for kid delight + user-picked content.
- Buttons/colored text → **A · dark text on bright fill**: kit `Button` look; new darker text shades; brand fill colors unchanged.
- Cleanup → **readability + guard**: fix what a person can see, add a CI guard; leave illustration/chart hex, white card surfaces and borders.
- UI kit → **use + prune**: `Button` + `PageHeader` become the standard; delete `BottomSheet` + `FormField`.
- Dark mode → **removed now**.

**Not in B3:** real dark mode; rewriting pages onto `Card` / `EmptyState`; border colors, `bg-white` card surfaces, illustration/chart hex; the auth / landing / legal / 404-500 pages (`login`, `register`, `index`, `tdah`, `privacidad`, `terminos`, `forgot/reset-password`, `verify-email`, `accept-invitation`, `404`, `500`); the operator console (`/admin/*`, `AdminShell`); the shared-device kiosk screen (`/kiosk`); the help guide's document styling (`GuideShell`); any backend change; layout or copy changes beyond removing the 6 title emoji.

## Section → color map

| Tone | Means | Pages |
|---|---|---|
| **sky** | Doing things | `parent/tasks`, `parent/tasks/[id]/edit`, `parent/assignments`, `parent/day`, `parent/approvals`, `routines`, `parent/routines`, `calendar`, `calendar/month`, `calendar/scan`, `parent/kiosk` |
| **mint** | Money | `bank`, `envelopes`, `parent/payouts`, `parent/settings/envelopes`, `parent/settings/family-bank`, every budget page that renders a header (`budget/index`, `budget/import`, `budget/recycle-bin`) |
| **sun** | Earning & winning | `gigs/index`, `gigs/my-gigs`, `parent/gigs`, `family-cup` |
| **coral** | Treats, care & home | `rewards`, `parent/rewards`, `parent/rewards/[id]/edit`, `parent/consequences`, `pet`, `pet/quests`, `pet/shop`, `meals`, `shopping` |
| **cream** | Talk & settings | `notifications`, `profile`, `chat`, `dm`, `dm/[id]`, `parent/jarvis`, `parent/jarvis-schedules`, `soporte`, `parent/settings/index`, `parent/settings/family`, `parent/settings/subscription`, `parent/settings/referrals`, `parent/settings/mcp-tokens`, `parent/starter-packs`, `parent/members`, `parent/analytics` |

**Home heroes (exceptions):**
- **Parent hub** (`/parent`) keeps its dark hero: `bg-brand-ink text-white` (14.7:1) instead of `from-slate-800 to-slate-700` — visually the same.
- **Kid home** (`/dashboard`, `KidHeader`): teen skin keeps its dark `#1E2230` + white text (passes); **child skin** becomes `bg-brand-sky` + ink text (6.52:1) instead of sky-deep + white. Every element inside the child hero that is white / white-alpha today becomes ink.

A page not in the table that renders an app header uses **cream**. `parent/settings/a2a` and `parent/settings/subscription/activate` render no app header and are untouched apart from the text rules. Redirect-only pages (`budget/accounts`, `budget/month/*`, `budget/scan-receipt`, `budget/transactions/new`, `budget/reports/*`, `parent/finances/*`, `pricing/upgrade`, `rutinas`) render nothing and are untouched.

## Tokens

Add to `@theme` in `frontend/src/styles/global.css`, next to the palette:

```css
/* Text-safe shades: ≥ 4.5:1 on white, cream and cream-deep. Use for colored
   TEXT; the -deep shades are fills/hovers only. */
--color-brand-sky-text:   #1A6F99;
--color-brand-mint-text:  #1E7552;
--color-brand-coral-text: #B8431F;
--color-brand-sun-text:   #8A5A00;
```

| Token | on white | on cream | on cream-deep |
|---|---|---|---|
| sky-text `#1A6F99` | 5.56 | 5.28 | 4.63 |
| mint-text `#1E7552` | 5.64 | 5.36 | 4.70 |
| coral-text `#B8431F` | 5.44 | 5.16 | 4.53 |
| sun-text `#8A5A00` | 5.93 | 5.63 | 4.94 |

All four also pass on the 15 %-alpha brand tints used for chips (≥ 4.83). No existing token changes value.

## Headers

**One source of header color:** new `frontend/src/lib/headerTone.ts`:

```ts
export type HeaderTone = "sky" | "mint" | "sun" | "coral" | "cream";
export const HEADER_TONES: readonly HeaderTone[];
/** Fill + ink outline + ink text for a section header. */
export function headerToneClass(tone: HeaderTone): string;
// sky → "bg-brand-sky border-b-4 border-brand-ink text-brand-ink", etc.
```

- **`PageHeader` / `PageLayout`:** props `headerClass`, `dark`, `backClass` are **removed**; `tone` is typed `HeaderTone` (default `"cream"`). The shell class comes from `headerToneClass(tone)`. The back link is `text-brand-ink` (ink-soft is 4.47 on sky / 4.35 on coral — below AA). Every text inside a tone header is ink; secondary text is smaller/lighter weight, never a lighter color.
- **`ChatShell`:** prop `headerClass` → `tone: HeaderTone` (required); the hardcoded `text-white` goes; header uses `headerToneClass`.
- **`BudgetShell`:** doc comment updated (no `headerClass`/`dark`); budget pages that render their own `<header>` use `headerToneClass("mint")`.
- **Custom hero headers** (`slot="header"` / `slot="before-nav"` / page-level `<header>`): `bank`, `envelopes`, `gigs/index`, `parent/assignments`, `profile`, `calendar/month`, `chat`, `dm/[id]`, `parent/jarvis`, `soporte`, `budget/index`, `budget/import`, `budget/recycle-bin` keep their extra content (balances, stats, pickers) but take their fill + text from `headerToneClass(<tone from the map>)`, and their inner white / white-alpha text becomes ink. Where a custom header is just title + back link + sub line, it is replaced by `PageHeader` with the `sub` / `actions` slots.
- **Title emoji:** the 6 `<h1>` emoji prefixes are removed (`bank`, `envelopes`, `chat`, `soporte`, `parent/jarvis`, `dm/[id]`).
- **Shape stays** as today's `PageHeader`: `pt-12 pb-6 px-6 rounded-b-[var(--radius-tile)] shadow-[var(--shadow-card)]`.

## Buttons and colored fills

**One source of button classes:** new `frontend/src/lib/buttonClasses.ts`:

```ts
export type ButtonVariant = "primary" | "secondary" | "mint" | "sun" | "ghost";
export type ButtonSize = "sm" | "md" | "lg" | "icon";
export function buttonClass(variant?: ButtonVariant, size?: ButtonSize): string;
```

- Returns exactly the classes `Button.astro` renders today (base + size + variant: coral / sky / mint / sun fills with **ink** text, ink outline, hard shadow, `-deep` hover). Destructive CTAs that used white on coral use `primary` (coral fill + ink text, 6.34:1). `Button.astro` imports `buttonClass` instead of holding its own map.
- Client-rendered markup (page `<script>` blocks that build HTML strings) imports `buttonClass` — `is:inline` / `define:vars` scripts can't import, so they use the literal class string and are covered by the guard.
- **Rule:** text on a brand fill (`bg-brand-{sky,mint,coral,sun}` or their `-deep`) is **ink**, never white. A brand-filled call-to-action (`<button>`, `<a>` styled as a button) uses `buttonClass` / `<Button>`; other brand-filled elements (chips, badges, pills, avatars, progress labels) just switch `text-white` → `text-brand-ink`. Existing `-deep` hover fills stay (ink on `-deep` ≥ 4.62).
- Red/rose destructive buttons that are not brand fills (`bg-red-600 text-white` etc.) are out of scope — they pass today.

## Colored and faint text

- `text-brand-{sky,mint,coral,sun}-deep` → `text-brand-{sky,mint,coral,sun}-text`, including variant prefixes (`hover:`, `group-hover:`, `focus:`, …). `border-*-deep`, `bg-*-deep`, `ring-*-deep`, `fill-*`/`stroke-*` are untouched.
- **Exception — dark backgrounds:** where a `-deep` text sits on a dark fill (`bg-brand-ink`, `bg-slate-800/900`, `#1E2230`), the darker shade would fail; those use the plain brand color (`text-brand-sky`, …) instead. Found by review of each hit whose element or nearest filled ancestor is dark.
- `text-slate-400`, `text-slate-500`, `text-gray-400`, `text-gray-500` → `text-brand-ink-soft` (9.55:1 on cream). On dark backgrounds they become `text-white/70` or stay as the page's existing light-on-dark treatment.

## Icons

- New `frontend/src/lib/icons.ts`: the 22 heroicons-outline path strings now inlined in `MoreSheet.astro` (`bell`, `help`, `routines`, `jarvis`, `support`, `pet`, `meals`, `shopping`, `calendar`, `dm`, `profile`, `tasks`, …), exported as `ICONS: Record<IconName, string>`, plus the header back chevron.
- New `frontend/src/components/ui/Icon.astro` (`name`, `class`) renders the 24×24 outline `<svg>` (stroke `currentColor`, width 2). `MoreSheet`, `PageHeader` (back chevron) and header `actions` use it.
- **Rule:** chrome (nav, More sheet, header titles + actions, toolbars, list-row action buttons) = line icons; emoji = big action tiles, empty states, celebrations/toasts, and user-picked content (goal / task / reward emoji). Existing inline heroicon `<svg>` elsewhere are already the same set and are not rewritten.

## UI kit

- Delete `frontend/src/components/ui/BottomSheet.astro` and `frontend/src/components/ui/FormField.astro` (0 imports).
- `Button` and `PageHeader` are the standard for their jobs; `Card`, `EmptyState`, `SectionHeader`, `Badge` stay available, pages are not rewritten onto them.

## Dark mode removal

- `Layout.astro`: drop the `theme` prop, the `data-theme` attribute on `<html>`, and the `prefers-color-scheme` `is:inline` script. `AdminShell` stops passing `theme="light"`.
- `global.css`: drop the `[data-theme="dark"]` block; keep `:root { color-scheme: light; … }`.
- `components/meta/Head.astro`: drop the dark `theme-color` meta; keep one `theme-color` `#4FB8E6` without a `media` query.
- `login.astro`'s `data-theme="outline"` is a Google sign-in button option, not ours — untouched.

## Guard and tests

**`frontend/test/visual-consistency.test.ts`** (vitest, node env; scans `src/**/*.{astro,ts,css}`; reuses the quote/comment-aware reading from `test/support/native-dialog-scan.ts` where it applies). Each rule reports `file:line` offenders; the test fails on any:

1. `bg-gradient-to-*` in the class of a `<header>` element (pages + components).
2. `text-white` in the same class attribute / class string as `bg-brand-{sky,mint,coral,sun}` or its `-deep` (with or without variant prefixes).
3. `text-brand-{sky,mint,coral,sun}-deep` anywhere (with or without variant prefix).
4. `text-slate-400|500`, `text-gray-400|500`.
5. An emoji inside an `<h1>` element's text.
6. `[data-theme="dark"]` or `prefers-color-scheme: dark` in any source file.
7. `headerClass=` passed to `PageLayout` / `PageHeader` / `ChatShell` (belt-and-braces; the removed prop already fails `astro check`).

Out-of-scope files listed in "Not in B3" are exempt by an explicit path allowlist in the test (auth/landing/legal/404-500 pages, `admin/*`, `AdminShell`, `kiosk.astro`, `GuideShell`) — each entry commented with why.

**`frontend/test/contrast.test.ts`:** reads the hex values of the brand tokens straight from `global.css` (so a future token edit is checked) and asserts ≥ 4.5:1 for: ink on each header tone and each `-deep` hover fill; each `*-text` shade on white, cream, cream-deep; white on `brand-ink` (parent hub). Implements the WCAG relative-luminance formula locally (no dependency).

**Unit tests:** `headerToneClass` (every tone → its fill + `border-brand-ink` + `text-brand-ink`, no `text-white`, no gradient; `HEADER_TONES` lists all five); `buttonClass` (defaults = primary/md; every variant has `text-brand-ink`, none has `text-white`; `Button.astro` renders the same string — asserted by importing the lib from the component, not by snapshot).

**E2E:** Playwright specs that assert header classes, emoji titles (e.g. "💬 …") or white-text classes are updated to the new text/markup.

**Verification after deploy (demo family `b8312b5a-c9c0-469f-992f-8dbd412db4a7`, phone width, parent + kid):** `/parent`, `/dashboard` (child skin), `/parent/tasks`, `/parent/approvals`, `/bank`, `/budget`, `/gigs`, `/parent/gigs`, `/rewards`, `/parent/consequences`, `/pet`, `/chat`, `/notifications`, `/parent/settings`, `/profile` — each header in its section color, ink text, no white-on-light text, no dark overscroll/status bar on an OS in dark mode.

## Risks

- **`-deep` text on dark surfaces** (codemod would lower contrast there): handled by the dark-background exception, reviewed per hit, caught visually in the screenshot pass.
- **Kid home hero** changes most visibly (child skin sky-deep → sky, white → ink): kids see it daily; the new look is the same family as every other page.
- **Large, mechanical diff** (~60 pages): the guard + contrast tests are the gate; `astro check` catches the removed props; screenshots catch the rest.
