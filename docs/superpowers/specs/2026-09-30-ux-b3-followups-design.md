# UX-B3 follow-ups — Design

**Date:** 2026-09-30
**Status:** approved 2026-09-30; implemented on fix/ux-b3-followups
**Program:** UX/GUI program, follow-up to **B3** (visual consistency, PR #285). Found by the B3 final review and the 2026-09-30 prod screenshot pass.

## What is wrong today

1. **Teen palette fails contrast.** `body[data-ui-mode="teen"]` in `global.css` repaints 8 brand tokens (coral → blue `#5C7CFA`, sun → grey, cream → cool grey, mint → teal). Ink on the teen blue is 4.00:1 (every coral header and primary button a teen sees), ink on the teen hover blue `#3B5BDB` 2.59:1, the `-text` shades on teen cream-deep 3.8–4.2:1, and the orange-red coral text shows on blue chips.
2. **Colored text on tints fails on the page background.** The `-text` shades pass on white/cream, but on a 20–30 % same-hue tint sitting on the cream-deep page (flash banners, chips) sky/mint/coral drop to 3.7–4.5:1 (e.g. `bg-brand-mint/20 text-brand-mint-text` 4.29:1, `coral/15` 4.11:1).
3. **Welcome-tour "Next" button** is white on sky-deep (3.15:1) in `src/lib/tour-theme.css` — the guard does not read CSS files.
4. **13 page titles carry an emoji** via the `PageLayout` `title` prop (⛅ 📅 🛒 📄 ✉️ 🍽️ 🐾 🛍️ 🔔 🗺️ 📺 📊), which renders inside `PageHeader`'s `<h1>` — B3's "no emoji in `<h1>`" rule only reads literal `<h1>` markup.

**Decision (user, 2026-09-30):** option **B — drop the teen colors.** Teens get the same palette as kids; they keep their dark home header (KidHeader teen skin `#1E2230`) and the tighter corner rounding.

## Changes

1. **Teen palette removed.** Delete the whole `body[data-ui-mode="teen"] { --color-brand-… }` token block. Keep `body[data-ui-mode="teen"] .rounded-2xl/.rounded-xl` and the `adult` cream remap. Update the section comment ("Teen UI mode (W4.2)") to say teen mode is corner rounding only.
2. **Darker text shades** in `@theme` (sun unchanged):
   | Token | Old | New |
   |---|---|---|
   | `--color-brand-sky-text` | `#1A6F99` | `#165F84` |
   | `--color-brand-mint-text` | `#1E7552` | `#1B694A` |
   | `--color-brand-coral-text` | `#B8431F` | `#9E3A1B` |
   | `--color-brand-sun-text` | `#8A5A00` | `#8A5A00` |
   Each passes ≥ 4.5:1 on white, cream, cream-deep, adult cream `#FAFAFA` / cream-deep `#EEEEEE`, and on its own hue's tint up to 30 % over each of those.
3. **Contrast test covers every UI mode and tints.** `test/contrast.test.ts` reads each `body[data-ui-mode="<mode>"] { … }` block's `--color-brand-*` overrides and runs the full pair set per mode (default + every declared mode): ink on the five header tones and four `-deep` hovers; each `-text` shade on white, cream, cream-deep; each `-text` shade on its own hue at 30 % over white, cream, cream-deep; white on ink. A future mode (or a re-added teen palette) that fails any pair fails CI.
4. **Tour button** (`src/lib/tour-theme.css`): the Next button becomes the kit look — `background: var(--color-brand-sky)`, `color: var(--color-brand-ink)`, `border: 2px solid var(--color-brand-ink)` (6.52:1). Any hover/focus rule for it keeps ink text.
5. **Guard reads CSS blocks.** `white-on-brand-fill` also flags a CSS declaration block (`{ … }`, in `.css` files and `<style>` blocks) that sets `background`/`background-color` to `var(--color-brand-{sky,mint,coral,sun}[-deep])` and `color` to `#fff`, `#ffffff` or `white`.
6. **Title emoji removed**, text kept, on the 13 pages. The `h1-emoji` rule also flags an emoji inside the `title` attribute value of a `<PageLayout>` or `<PageHeader>` tag (those titles render as the page `<h1>`). Other components' `title`/`icon` props (e.g. `SettingsAccordion icon="🏦"`) are not affected.
7. **Docs.** CLAUDE.md's visual-system paragraph: the contrast test "checks every token pair ≥ 4.5:1 in every UI mode, including tints up to 30 %"; teen mode = default palette + tighter corners.

**Not in scope:** BottomNav's own icon map; TaskDeck/dialog kit look; analytics header color; SettingsAccordion emoji icons; exempt pages.

## Testing

- Contrast test: RED first (teen block + tint pairs fail with today's values), GREEN after changes 1–2.
- Scanner unit tests for the CSS-block pairing and the `title` attribute rule (RED → GREEN), then the strict tree guard goes RED on `tour-theme.css` and the 13 pages and GREEN after fixes.
- vitest, `astro check`, `astro build`; after deploy, a teen (diego.demo) and kid pass on prod at phone width.
